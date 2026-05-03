"""Bridge lifecycle management — start, stop, interrupt, sleep, wake, restart."""
import os
import shlex

import sublime

from .rpc import JsonRpcClient
from .session_env import _find_python_310_plus, _resolve_model_id, load_saved_sessions


BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "main.py")
CODEX_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "codex_main.py")
COPILOT_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "copilot_main.py")
OPENAI_BRIDGE_SCRIPT = os.path.join(os.path.dirname(__file__), "bridge", "openai_main.py")


class BridgeManager:
    """Manages the bridge process lifecycle for a Session."""

    def __init__(self, session):
        self._s = session

    def start(self, resume_session_at: str = None) -> None:
        """Start the bridge process and send initialize."""
        s = self._s
        s._ui.show_connecting()

        settings = sublime.load_settings("ClaudeCode.sublime-settings")
        python_path = settings.get("python_path", "python3")
        if python_path == "python3":
            detected = _find_python_310_plus()
            if detected != python_path:
                print(f"[Claude] Auto-detected Python 3.10+: {detected}")
                python_path = detected

        # Build profile docs list early (before init) so we can add to system prompt
        self._build_profile_docs_list()

        # Load environment variables from settings and profile
        env = self._load_env(settings)

        # Resolve virtual model ID (e.g. @400k suffix) → real model + context limit
        default_models = settings.get("default_models", {})
        _backend_fallback_models = {"deepseek": "deepseek-v4-pro", "codex": "gpt-5.5"}
        default_model = default_models.get(s.backend) or _backend_fallback_models.get(s.backend) or settings.get("default_model")
        model_for_env = (s.profile.get("model") if s.profile else None) or default_model
        if model_for_env:
            _, ctx = _resolve_model_id(model_for_env)
            if ctx:
                env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(ctx)

        # Sync sublime project retain content to file for hook
        self._sync_project_retain()

        # Claude/Kimi API settings from Sublime config → passed as env vars to claude CLI
        if s.backend in ("claude", "kimi", "default", ""):
            api_key = settings.get("anthropic_api_key")
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            base_url = settings.get("anthropic_base_url")
            if base_url:
                env["ANTHROPIC_BASE_URL"] = base_url
            model = settings.get("anthropic_model")
            if model:
                env["ANTHROPIC_MODEL"] = model

        # DeepSeek uses the Claude bridge with Anthropic-compatible endpoint
        if s.backend == "deepseek":
            ds_key = settings.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
            env["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
            # Forcibly clear ANTHROPIC_API_KEY — if it leaked from parent process
            # (e.g. set in shell rc), the SDK would prefer it over ANTHROPIC_AUTH_TOKEN
            # and send Anthropic creds to api.deepseek.com, causing 401 errors.
            env["ANTHROPIC_API_KEY"] = ""
            if ds_key:
                env["ANTHROPIC_AUTH_TOKEN"] = ds_key
            else:
                print("[Claude] WARNING: deepseek backend has no API key set "
                      "(settings.deepseek_api_key or DEEPSEEK_API_KEY env var). "
                      "Requests will likely fail with 401.")
            env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
            env.setdefault("CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK", "1")

        if s.backend == "openai":
            oai_url = settings.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")
            oai_key = settings.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            oai_model = settings.get("openai_model") or os.environ.get("OPENAI_MODEL", "")
            if oai_url:
                env["OPENAI_BASE_URL"] = oai_url
            if oai_key:
                env["OPENAI_API_KEY"] = oai_key
            if oai_model:
                env["OPENAI_MODEL"] = oai_model

        if s.backend == "codex":
            bridge_script = CODEX_BRIDGE_SCRIPT
        elif s.backend == "copilot":
            bridge_script = COPILOT_BRIDGE_SCRIPT
        elif s.backend == "openai":
            bridge_script = OPENAI_BRIDGE_SCRIPT
        else:
            bridge_script = BRIDGE_SCRIPT
        s.client = JsonRpcClient(s._on_notification)
        s.client.start([python_path, bridge_script], env=env)
        s._status_mgr.status("connecting...")

        permission_mode = settings.get("permission_mode", "acceptEdits")
        if permission_mode == "default":
            allowed_tools = []
        else:
            allowed_tools = settings.get("allowed_tools", [])

        print(f"[Claude] initialize: permission_mode={permission_mode}, allowed_tools={allowed_tools}, resume={s.resume_id}, fork={s.fork}, profile={s.profile}, default_model={default_model}, subsession_id={getattr(s, 'subsession_id', None)}")
        additional_dirs = s.window.folders()[1:] if len(s.window.folders()) > 1 else []
        project_data = s.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        extra_dirs = project_settings.get("claude_additional_dirs", [])
        if extra_dirs:
            expanded = [os.path.expanduser(d) for d in extra_dirs]
            additional_dirs = additional_dirs + expanded
            print(f"[Claude] extra additional_dirs from project: {expanded}")
        init_params = {
            "cwd": s._cwd(),
            "additional_dirs": additional_dirs,
            "allowed_tools": allowed_tools,
            "permission_mode": permission_mode,
            "view_id": str(s.output.view.id()) if s.output and s.output.view else None,
        }
        if s.resume_id:
            init_params["resume"] = s.resume_id
            if s.fork:
                init_params["fork_session"] = True
            for saved in load_saved_sessions():
                if saved.get("session_id") == s.resume_id:
                    saved_project = saved.get("project", "")
                    if saved_project and saved_project != init_params["cwd"]:
                        print(f"[Claude] resume: using saved project {saved_project}")
                        init_params["cwd"] = saved_project
                    break
            if resume_session_at:
                init_params["resume_session_at"] = resume_session_at
        if hasattr(s, 'subsession_id') and s.subsession_id:
            init_params["subsession_id"] = s.subsession_id
        if not s.resume_id:
            effort = settings.get("effort", "high")
            if s.profile and s.profile.get("effort"):
                effort = s.profile["effort"]
            init_params["effort"] = effort
        elif s.profile and s.profile.get("effort"):
            init_params["effort"] = s.profile["effort"]

        if s.profile:
            if s.profile.get("model"):
                real_model, _ = _resolve_model_id(s.profile["model"])
                init_params["model"] = real_model
            if s.profile.get("betas"):
                init_params["betas"] = s.profile["betas"]
            if s.profile.get("pre_compact_prompt"):
                init_params["pre_compact_prompt"] = s.profile["pre_compact_prompt"]
            system_prompt = s.profile.get("system_prompt", "")
            if s.profile_docs:
                docs_info = f"\n\nProfile Documentation: {len(s.profile_docs)} files available. Use list_profile_docs to see them and read_profile_doc(path) to read their contents."
                system_prompt = system_prompt + docs_info if system_prompt else docs_info.strip()
            if system_prompt:
                init_params["system_prompt"] = system_prompt
        else:
            if default_model:
                real_model, _ = _resolve_model_id(default_model)
                init_params["model"] = real_model

        extra_args_str = settings.get("claude_extra_args", "")
        if extra_args_str:
            try:
                parsed = shlex.split(extra_args_str)
                extra_dict = {}
                it = iter(parsed)
                for arg in it:
                    key = arg.lstrip("-").replace("-", "_")
                    val = next(it, "")
                    extra_dict[key] = val
                if extra_dict:
                    init_params["extra_args"] = extra_dict
            except Exception as e:
                print(f"[Claude] Failed to parse claude_extra_args: {e}")

        s.client.send("initialize", init_params, s._on_init)

    def _load_env(self, settings) -> dict:
        """Load environment variables from settings and project profile."""
        s = self._s
        env = {}
        settings_env = settings.get("env", {})
        if isinstance(settings_env, dict):
            env.update(settings_env)
        project_data = s.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        project_env = project_settings.get("claude_env", {})
        if isinstance(project_env, dict):
            env.update(project_env)
        cwd = s._cwd()
        if cwd:
            project_settings_path = os.path.join(cwd, ".claude", "settings.json")
            if os.path.exists(project_settings_path):
                try:
                    with open(project_settings_path, "r") as f:
                        import json
                        proj_settings = json.load(f)
                    claude_env = proj_settings.get("env", {})
                    if isinstance(claude_env, dict):
                        env.update(claude_env)
                except Exception as e:
                    print(f"[Claude] Failed to load project env: {e}")
        if s.profile:
            profile_env = s.profile.get("env", {})
            if isinstance(profile_env, dict):
                env.update(profile_env)
        if env:
            print(f"[Claude] Custom env vars: {env}")
        return env

    def _sync_project_retain(self):
        """Sync sublime project retain content to file for hook."""
        s = self._s
        project_data = s.window.project_data() or {}
        project_settings = project_data.get("settings", {})
        retain_content = project_settings.get("claude_retain", "")
        s._state.sync_project_retain(retain_content)

    def _build_profile_docs_list(self) -> None:
        """Build list of available docs from profile preload_docs patterns (no reading yet)."""
        s = self._s
        if not s.profile or not s.profile.get("preload_docs"):
            return

        import glob as glob_module

        patterns = s.profile["preload_docs"]
        if isinstance(patterns, str):
            patterns = [patterns]

        cwd = s._cwd()

        try:
            for pattern in patterns:
                full_pattern = os.path.join(cwd, pattern)
                for filepath in glob_module.glob(full_pattern, recursive=True):
                    if os.path.isfile(filepath):
                        rel_path = os.path.relpath(filepath, cwd)
                        s.profile_docs.append(rel_path)

            if s.profile_docs:
                print(f"[Claude] Profile docs available: {len(s.profile_docs)} files")
        except Exception as e:
            print(f"[Claude] preload_docs error: {e}")

    def interrupt(self, break_channel: bool = True) -> None:
        """Interrupt current query."""
        s = self._s
        if s.client:
            sent = s.client.send("interrupt", {})
            s._status_mgr.status("interrupting...")
            s._queued_prompts.clear()
            if not sent:
                s.working = False
                s._status_mgr.status("error: bridge died")
                s.output.text("\n\n*Bridge process died. Please restart the session.*\n")
                s._enter_input_with_draft()

        if break_channel and s.output.view:
            from . import notalone
            notalone.interrupt_channel(s.output.view.id())

    def stop(self) -> None:
        """Stop session and clean up."""
        s = self._s
        self._abort_background_tools("session stopped")
        s._task_tool_map.clear()
        s._persist_state("closed")
        s._stop_heartbeat()
        if s.persona_session_id and s.persona_url:
            s._release_persona()

        if s.client:
            client = s.client
            client.send("shutdown", {}, lambda _: client.stop())
        s._status_mgr.clear()

        if s.output:
            s.output.conversations.clear()
        s.pending_context.clear()
        s._queued_prompts.clear()

    def sleep(self, force: bool = False) -> bool:
        """Put session to sleep — kill bridge, keep view.

        Returns True if the session was put to sleep, False if refused.
        Refuses (returns False) when background tools are running unless
        force=True. Caller can re-invoke with force=True to abort + sleep.
        """
        s = self._s
        if not s.session_id:
            return False
        if s.working:
            self.interrupt()
            sublime.set_timeout(lambda: self.sleep(force=force), 500)
            return False
        # Refuse to sleep if background processes are alive — they'd be killed
        # silently with the bridge subprocess. force=True overrides.
        if not force and s.output:
            bg = s.output.active_background_tools()
            if bg:
                names = ", ".join(t.name for t in bg[:3])
                more = f" (+{len(bg) - 3} more)" if len(bg) > 3 else ""
                msg = f"refusing to sleep: {len(bg)} background tool(s) running: {names}{more}"
                print(f"[Claude] {msg}")
                sublime.status_message(f"Claude: {msg}")
                return False
        s._stop_heartbeat()
        # If we got here with force=True and bg tools, abort their UI state.
        self._abort_background_tools("session slept")
        s._task_tool_map.clear()
        if s.client:
            client = s.client
            s.client = None
            client.send("shutdown", {}, lambda _: client.stop())
        s.initialized = False
        s._persist_state("sleeping")
        s._apply_sleep_ui()
        return True

    def wake(self) -> None:
        """Wake a sleeping session — re-spawn bridge with resume."""
        s = self._s
        if s.client or s.initialized:
            return
        if not s.session_id:
            return
        s._ui.clear_overlay()
        if s.output and s.output.view:
            view = s.output.view
            view.settings().erase("claude_sleeping")
            end = view.size()
            view.sel().clear()
            view.sel().add(end)
            view.show(end)
        s.resume_id = s.session_id
        s.fork = False
        resume_at = s._pending_resume_at
        s.current_tool = "waking..."
        self.start(resume_session_at=resume_at)
        s._persist_state("open")
        if s.output and s.output.view:
            s.output.set_name(s.display_name)

    def restart(self) -> None:
        """Restart session — sleep then immediately wake.

        Restart is an explicit user action (typically used to fix a stuck
        session), so background tools are aborted via force=True.
        """
        def do_wake():
            if self._s.output and self._s.output.view and self._s.output.view.settings().get("claude_sleeping"):
                self.wake()
        if self.sleep(force=True):
            sublime.set_timeout(do_wake, 600)

    def _abort_background_tools(self, reason: str) -> None:
        """Mark all in-flight background tools as errored (their subprocess is gone)."""
        s = self._s
        if not s.output:
            return
        try:
            from .output_models import ERROR
            bg = s.output.active_background_tools()
            for tool in bg:
                old_status = tool.status
                tool.status = ERROR
                tool.result = f"(aborted: {reason})"
                s.output._patch_tool_symbol(tool, old_status)
            if bg:
                print(f"[Claude] aborted {len(bg)} background tool(s): {reason}")
        except Exception as e:
            print(f"[Claude] _abort_background_tools error: {e}")

    def ensure_alive(self, silent: bool = False) -> bool:
        """Check bridge health; auto-restart if dead."""
        s = self._s
        if s.client and s.client.is_alive() and s.initialized:
            return True
        if not silent:
            s.output.text("\n*Bridge process died. Auto-restarting...*\n")
        return self.auto_restart()

    def auto_restart(self) -> bool:
        """Kill dead bridge and restart with resume."""
        s = self._s
        if s.client:
            try:
                s.client.stop()
            except Exception:
                pass
            s.client = None
        s.initialized = False
        s.working = False
        s._clear_deferred_state()

        if not s.session_id:
            return False

        s.resume_id = s.session_id
        s.fork = False
        resume_at = s._pending_resume_at
        s.current_tool = "reconnecting..."
        s._status_mgr.status("reconnecting...")
        try:
            self.start(resume_session_at=resume_at)
            s._persist_state("open")
            return True
        except Exception as e:
            print(f"[Claude] Auto-restart failed: {e}")
            s._status_mgr.status("error: restart failed")
            return False

    def release_persona(self) -> None:
        """Release acquired persona."""
        import threading
        from . import persona_client

        s = self._s
        session_id = s.persona_session_id
        persona_url = s.persona_url

        def release():
            result = persona_client.release_persona(session_id, base_url=persona_url)
            if "error" not in result:
                print(f"[Claude] Released persona for session {session_id}")

        threading.Thread(target=release, daemon=True).start()

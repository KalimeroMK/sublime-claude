"""Context management for Session — pending files, selections, images, related files."""
import os

from .constants import MAX_RELATED_FILES


class ContextManager:
    """Manages pending context items (files, selections, images, folders)."""

    def __init__(self, session):
        self._s = session

    def add_file(self, path: str, content: str) -> None:
        """Add a file to pending context, plus auto-detect related files."""
        from .session_core import ContextItem
        name = os.path.basename(path)
        self._s.pending_context.append(ContextItem("file", name, f"File: {path}\n```\n{content}\n```"))
        self._add_related_files(path, content)
        self._update_display()

    def _add_related_files(self, path: str, content: str) -> None:
        """Auto-detect and add related files (tests, imports, siblings) to context."""
        import re

        dirname = os.path.dirname(path)
        basename = os.path.basename(path)
        name_no_ext = os.path.splitext(basename)[0]
        ext = os.path.splitext(basename)[1]

        candidates = set()

        # Naming convention siblings
        suffix_variants = ["_test", "_spec", "Test", "Spec", ".test", ".spec"]
        prefix_variants = ["test_", "spec_"]
        for suffix in suffix_variants:
            candidates.add(os.path.join(dirname, name_no_ext + suffix + ext))
        for prefix in prefix_variants:
            candidates.add(os.path.join(dirname, prefix + name_no_ext + ext))

        # Parent/child folders (e.g. controllers)
        if dirname:
            parent = os.path.dirname(dirname)
            if parent:
                candidates.add(os.path.join(parent, "controllers", name_no_ext + "Controller" + ext))
                candidates.add(os.path.join(parent, "models", name_no_ext + ext))
                candidates.add(os.path.join(parent, "views", name_no_ext + ext))

        # Parse imports from first 30 lines
        lines = content.split("\n")[:30]
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # Python
            if line.startswith("from ") and " import " in line:
                mod = line.split()[1].replace(".", "/")
                candidates.add(os.path.join(dirname, mod + ".py"))
                for folder in self._s.window.folders():
                    candidates.add(os.path.join(folder, mod + ".py"))
                    candidates.add(os.path.join(folder, mod, "__init__.py"))
            elif line.startswith("import "):
                mod = line.split()[1].split(".")[0]
                candidates.add(os.path.join(dirname, mod + ".py"))
                for folder in self._s.window.folders():
                    candidates.add(os.path.join(folder, mod + ".py"))

            # JS/TS
            elif ("from '" in line or 'from "' in line) or "require(" in line:
                m = re.search(r"[from\srequire]\s*['\"]([^'\"]+)['\"]", line)
                if m:
                    rel = m.group(1)
                    if rel.startswith("."):
                        resolved = os.path.normpath(os.path.join(dirname, rel))
                        candidates.add(resolved)
                        for e in (".js", ".ts", ".jsx", ".tsx", ".vue"):
                            candidates.add(resolved + e)
                            if not resolved.endswith(ext):
                                candidates.add(os.path.join(resolved, "index" + e))

            # PHP
            elif line.startswith("use ") and "\\" in line:
                ns = line[4:].rstrip(";").strip()
                parts = ns.split("\\")
                for folder in self._s.window.folders():
                    candidates.add(os.path.join(folder, *parts) + ".php")
                    candidates.add(os.path.join(folder, "src", *parts) + ".php")
            elif line.startswith("require") or line.startswith("include"):
                m = re.search(r"['\"]([^'\"]+)['\"]", line)
                if m:
                    rel = m.group(1)
                    if not rel.startswith("http"):
                        candidates.add(os.path.normpath(os.path.join(dirname, rel)))

            # Go
            elif line.startswith('import "') or line.startswith("import '"):
                m = re.search(r'["\']([^"\']+)["\']', line)
                if m:
                    pkg = m.group(1).split("/")[-1]
                    candidates.add(os.path.join(dirname, pkg + ".go"))
                    for folder in self._s.window.folders():
                        candidates.add(os.path.join(folder, pkg + ".go"))

        # Filter candidates
        already = set()
        for item in self._s.pending_context:
            if item.content.startswith("File: ") or item.content.startswith("Related file: "):
                first_line = item.content.split("\n")[0]
                if first_line.startswith("File: "):
                    already.add(os.path.abspath(first_line[6:]))
                elif first_line.startswith("Related file: "):
                    already.add(os.path.abspath(first_line[14:]))

        added = 0
        for cand in candidates:
            if added >= MAX_RELATED_FILES:
                break
            if not cand or cand == path:
                continue
            if not os.path.isfile(cand):
                continue
            abs_cand = os.path.abspath(cand)
            if abs_cand in already:
                continue
            if "/node_modules/" in abs_cand or "/vendor/" in abs_cand or "/__pycache__/" in abs_cand:
                continue
            try:
                with open(cand, "r", encoding="utf-8", errors="ignore") as f:
                    related_content = f.read()
                rel_name = os.path.basename(cand)
                from .session_core import ContextItem
                self._s.pending_context.append(ContextItem(
                    "file", rel_name,
                    f"Related file: {cand}\n```\n{related_content}\n```"
                ))
                already.add(abs_cand)
                added += 1
            except Exception:
                continue

        if added:
            print(f"[Claude] Smart Context: added {added} related file(s) for {basename}")

    def add_selection(self, path: str, content: str) -> None:
        """Add a selection to pending context."""
        from .session_core import ContextItem
        name = os.path.basename(path) if path else "selection"
        self._s.pending_context.append(ContextItem("selection", name, f"Selection from {path}:\n```\n{content}\n```"))
        self._update_display()

    def add_folder(self, path: str) -> None:
        """Add a folder path to pending context."""
        from .session_core import ContextItem
        name = os.path.basename(path) + "/"
        self._s.pending_context.append(ContextItem("folder", name, f"Folder: {path}"))
        self._update_display()

    def add_image(self, image_data: bytes, mime_type: str) -> None:
        """Add an image to pending context."""
        import base64
        import tempfile

        ext = ".png" if "png" in mime_type else ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".img"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(image_data)
            temp_path = f.name

        encoded = base64.b64encode(image_data).decode('utf-8')
        name = f"image{ext}"
        from .session_core import ContextItem
        self._s.pending_context.append(ContextItem(
            "image", name,
            f"__IMAGE__:{mime_type}:{encoded}"
        ))
        print(f"[Claude] Added image to context: {name} ({len(image_data)} bytes, saved to {temp_path})")
        self._update_display()

    def clear(self) -> None:
        """Clear pending context."""
        self._s.pending_context = []
        self._update_display()

    def _update_display(self) -> None:
        """Update output view with pending context."""
        self._s.output.set_pending_context(self._s.pending_context)

    def build_prompt(self, prompt: str) -> tuple:
        """Build full prompt with pending context.

        Returns:
            (full_prompt, images) where images is list of {"mime_type": str, "data": str}
        """
        if not self._s.pending_context:
            return prompt, []

        parts = []
        images = []
        for item in self._s.pending_context:
            if item.content.startswith("__IMAGE__:"):
                _, mime_type, data = item.content.split(":", 2)
                images.append({"mime_type": mime_type, "data": data})
            else:
                parts.append(item.content)
        parts.append(prompt)
        return "\n\n".join(parts), images

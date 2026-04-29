# Roadmap

## Done

### Skills Marketplace
Browse and install 27 curated skills with one click. Install globally (`~/.claude/CLAUDE.md`) or per-project (`./CLAUDE.md`). Skills from everything-claude-code and community.

- `Claude: Skills Marketplace` — browse and install
- `Claude: List Active Skills` — view active skills and scope
- `Claude: Disable All Skills` — disable global/project/all skills
- Hybrid scope: ask user on each install whether to apply globally or per-project
- User content in CLAUDE.md is preserved via `<!-- [Claude Sublime Skills] START/END -->` markers

### Session Sleep/Wake
Sessions can be put to sleep to free bridge subprocess resources while keeping the view open.

- `Claude: Sleep Session` — kills bridge, view shows `⏸` prefix and phantom hint
- `Claude: Wake Session` / press Enter — re-spawns bridge with resume, shows "Connecting..." phantom
- Switch panel (`Cmd+\`) shows sleeping sessions with `⏸` marker
- On Sublime restart, all orphaned claude views are auto-registered as sleeping
- Auto-sleep: `auto_sleep_minutes` setting (0 = disabled) sleeps idle sessions after timeout
- Session state (`open`/`sleeping`/`closed`) and `backend` persisted in `.sessions.json`

## Planned

### Remote Control via Claude Code Channels
Use Claude Code's native Channels feature (v2.1.80+) to remote-control sessions
from Telegram or Discord.

- Requires claude.ai subscription login (not API key)
- Bridge passes `--channels plugin:telegram@claude-plugins-official` at startup
- User runs `/telegram:configure <token>` once to pair
- Messages from phone arrive as `<channel>` events in the session
- Session can reply back through the same channel

## Backlog

- Streaming text (currently waits for full response)
- Image/file drag-drop to context
- Cost tracking dashboard
- Session search/filter (basic impl done, needs refinement)
- Click to expand/collapse tool sections
- MCP tool parameters (pass args to saved tools)
- notalone channel mode (`CHANNEL_SPEC.md`)

---
name: session-manager
description: Manage Claude Code session history — list, preview, rename, delete, backup, and clean test sessions. Triggers on /session-manager or when user asks about CC sessions/resume.
---

# Session Manager

Manages Claude Code session files in `~/.claude/projects/`. Works through the CLI tool at `~/.claude/tools/session-manager.py`.

## Quick Install

Copy the two files into place:

```bash
cp session-manager.py ~/.claude/tools/session-manager.py
cp session-manager.md  ~/.claude/skills/session-manager.md
```

Then restart Claude Code or type `/session-manager`.

## Tool path

```
python ~/.claude/tools/session-manager.py <command> [args...]
```

## Available commands

| Command | Description |
|---------|-------------|
| `list` | List all sessions across all projects (sorted by date, newest first) |
| `list --verbose` / `list -v` | List sessions with full UUID and file path |
| `list --trash` | List soft-deleted sessions in trash |
| `list --project=<PROJ>` | List sessions for a specific project only |
| `preview <N>` | Show detailed preview of session #N (user messages, tools, stats) |
| `preview <N> --all` | Show ALL user messages |
| `preview <N> --msgs N` | Show N user messages (default: 5) |
| `rename <N> <"new title">` | Rename session #N — updates both JSONL (cc resume sync) and metadata |
| `delete <N>` | Soft-delete session #N → moves to `~/.claude/session-manager/trash/` |
| `undelete` | Restore ALL trashed sessions |
| `undelete <N>` | Restore specific trashed session |
| `clean-test` | Detect "who are you" / test sessions (dry-run, no deletion) |
| `clean-test --force` | Delete all detected test sessions → trash |
| `backup <path>` | Full backup (projects + metadata + trash) to target directory |
| `restore <path>` | Restore from backup directory |
| `tag <N> <tag1,tag2>` | Add tags to session #N |
| `note <N> <"text">` | Add note to session #N |
| `web [port]` | Start web-based visual UI (default port 8765), auto-opens browser |

## Behavior rules

1. **Always run via Bash tool.** The tool prints human-readable output — show it to the user.
2. **Preview before delete.** When the user asks to delete, run `preview` first so they can confirm.
3. **clean-test is dry-run by default.** Always run without `--force` first. Ask for confirmation before re-running with `--force`.
4. **rename updates both sides.** JSONL first user message + meta.json. A backup (`.jsonl.bak`) is always created.
5. **restore asks first.** Before full restore, tell the user what will be overwritten.
6. **Indices change.** After any delete/undelete, the index numbering shifts. Re-run `list` to show updated indices.
7. **Web UI.** The `web` command starts an HTTP server on 127.0.0.1:8765 and auto-opens the browser. The UI provides sortable table, search/project filters, side-drawer preview, and modal dialogs for rename/backup/clean-test.

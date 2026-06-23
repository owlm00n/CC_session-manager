# Session Manager for Claude Code

A full-featured Claude Code session history management tool with CLI and Web UI. Zero external dependencies (pure Python stdlib).

## Features

- **Session list** — Browse all sessions across projects, with project name, date, size, message count, and title
- **Preview** — View session details including user messages and tools used (`--all` / `--msgs N`)
- **Rename** — Rename sessions, synced to `cc resume` list by updating the JSONL first user message + metadata
- **Delete / Undelete** — Soft-delete sessions to trash, restore anytime
- **Tag & Note** — Add custom tags and notes to sessions for organization
- **Test session detection** — Auto-detect "who are you" / test sessions (`clean-test`)
- **Backup / Restore** — Full backup of all projects + metadata + trash
- **Web UI** — Sortable table, search/project filters, side-drawer preview

## Setup

Copy the two files into your Claude Code config directory:

```bash
cp session-manager.py ~/.claude/tools/session-manager.py
cp session-manager.md  ~/.claude/skills/session-manager.md
```

Restart Claude Code or type `/session-manager` to start.

## Requirements

- Python 3.6+ (standard library only, zero dependencies)
- Works on Windows, macOS, Linux

## Quick start

```bash
# CLI mode
python ~/.claude/tools/session-manager.py list
python ~/.claude/tools/session-manager.py preview 1
python ~/.claude/tools/session-manager.py list -v

# Web UI mode
python ~/.claude/tools/session-manager.py web
# → opens http://127.0.0.1:8765

# Detect test/trash sessions
python ~/.claude/tools/session-manager.py clean-test
```

## Commands

| Command | Description |
|---------|-------------|
| `list` | List all sessions across all projects |
| `list -v` | List with full UUID and file path |
| `list --trash` | List soft-deleted sessions |
| `list --project=<NAME>` | Filter by project |
| `preview <N>` | Session detail (5 user messages) |
| `preview <N> --all` | Session detail (all messages) |
| `preview <N> --msgs N` | Session detail (N messages) |
| `rename <N> <title>` | Rename (syncs to cc resume) |
| `delete <N>` | Soft-delete → trash |
| `undelete [N]` | Restore from trash |
| `clean-test` | Detect test sessions (dry-run) |
| `clean-test --force` | Delete all test sessions |
| `backup <path>` | Full backup |
| `restore <path>` | Restore from backup |
| `tag <N> <tags>` | Add comma-separated tags |
| `note <N> <text>` | Add note |
| `web [port]` | Start web UI (default :8765) |

## File structure

```
~/.claude/
├── tools/
│   └── session-manager.py      ← the tool
├── skills/
│   └── session-manager.md      ← CC skill trigger
└── session-manager/
    ├── meta.json               ← custom titles, tags, notes
    ├── trash/                  ← soft-deleted sessions
    └── backups/                ← backup snapshots
```

## How it works

`cc resume` displays the **latest `type: "last-prompt"` entry** from each session's `.jsonl` file as the title (not the first user message). Rename updates:
1. All `last-prompt` entries in the JSONL → reflected in `/resume` after restart
2. `meta.json` → used by the session manager tool for display
3. A `.jsonl.bak` backup is created before writing

If a session has no `last-prompt` entry yet, one is appended.

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

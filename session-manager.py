#!/usr/bin/env python
"""
Session Manager for Claude Code sessions.
Dual-mode: standalone CLI + importable from CC Skill.

Usage:
  python session-manager.py list [--project PROJ] [--trash]
  python session-manager.py preview <index> [--project PROJ]
  python session-manager.py rename <index> <new-title> [--project PROJ]
  python session-manager.py delete <index> [--project PROJ]
  python session-manager.py undelete [<index>]
  python session-manager.py clean-test [--force] [--project PROJ]
  python session-manager.py backup <path>
  python session-manager.py restore <path>
  python session-manager.py tag <index> <tag1,tag2,...>
  python session-manager.py note <index> <text>
"""

import os
import json
import shutil
import sys
import datetime
import re
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
CLAUDE_DIR = HOME / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
MGR_DIR = CLAUDE_DIR / "session-manager"
META_FILE = MGR_DIR / "meta.json"
TRASH_DIR = MGR_DIR / "trash"


# ─── Helpers ──────────────────────────────────────────────────

def load_meta():
    if META_FILE.exists():
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sessions": {}}


def save_meta(meta):
    MGR_DIR.mkdir(parents=True, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def get_first_user_message(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "user" and not obj.get("isMeta"):
                        content = obj.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            texts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    texts.append(c.get("text", ""))
                            content = " ".join(texts)
                        return str(content).replace("\n", " ").strip()
                except json.JSONDecodeError:
                    pass
    except Exception:
        return "[READ ERROR]"
    return ""


def get_session_stats(filepath):
    user_count = 0
    assistant_count = 0
    total_lines = 0
    first_ts = None
    last_ts = None
    first_user_msg = ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp")
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                    t = obj.get("type", "")
                    if t == "user" and not obj.get("isMeta"):
                        user_count += 1
                        if not first_user_msg:
                            content = obj.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                texts = []
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        texts.append(c.get("text", ""))
                                content = " ".join(texts)
                            first_user_msg = str(content).replace("\n", " ").strip()
                    elif t == "assistant":
                        assistant_count += 1
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return user_count, assistant_count, total_lines, first_ts, last_ts, first_user_msg


def get_session_summary(filepath, max_user_msgs=5):
    lines = []
    user_msgs = []
    tool_names = set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines.append(line)
                try:
                    obj = json.loads(line)
                    t = obj.get("type", "")
                    if t == "user" and not obj.get("isMeta"):
                        content = obj.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            texts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    texts.append(c.get("text", ""))
                            content = " ".join(texts)
                        content = str(content).replace("\n", " ").strip()
                        if content:
                            user_msgs.append(content[:200])
                    elif t == "assistant":
                        content = obj.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict):
                                    if c.get("type") == "tool_use":
                                        tool_names.add(c.get("name", "unknown"))
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    # max_user_msgs=0 means return all
    truncated = user_msgs if max_user_msgs == 0 else user_msgs[:max_user_msgs]
    return {
        "total_lines": len(lines),
        "user_msg_count": len(user_msgs),
        "user_msgs": truncated,
        "tools_used": sorted(tool_names),
    }


def is_test_session(filepath):
    stats = get_session_stats(filepath)
    user_count = stats[0]
    assistant_count = stats[1]
    first_msg = stats[5].lower().strip()
    total_lines = stats[2]
    if user_count == 0:
        return True
    test_patterns = [
        "who are you", "who are your", "what are you",
        "你是谁", "你是谁?", "你好", "hello", "hi", "hey",
        "ls", "ls -la", "pwd", "dir",
        "session stopped",
        "当前模型是", "当前模型", "你是什么模型",
        "test", "测试", "test session",
        "what model", "which model",
        "help", "/help",
    ]
    is_test_msg = any(first_msg == p or first_msg.startswith(p) for p in test_patterns)
    if not is_test_msg:
        # Also catch sessions with very short first message + trivial activity
        if len(first_msg) < 8 and user_count <= 2 and assistant_count <= 2 and total_lines < 15:
            return True
        if len(first_msg) < 15 and user_count <= 1 and assistant_count <= 1 and total_lines < 10:
            return True
        return False
    # Test-pattern message matched — check if session is trivial
    if user_count <= 3 and assistant_count <= 4:
        return True
    if total_lines < 30 and user_count <= 2:
        return True
    if total_lines < 15:
        return True
    return False


def get_project_sessions(project_dir):
    sessions = []
    dir_path = PROJECTS_DIR / project_dir
    if not dir_path.is_dir():
        return sessions
    for fname in sorted(os.listdir(dir_path)):
        if fname.endswith(".jsonl"):
            uuid = fname.replace(".jsonl", "")
            sessions.append((uuid, dir_path / fname))
    return sessions


def all_sessions_flat(project_filter=None, include_deleted=False):
    meta = load_meta()
    result = []
    for project_dir in sorted(os.listdir(PROJECTS_DIR)):
        if not (PROJECTS_DIR / project_dir).is_dir():
            continue
        if project_filter and project_dir != project_filter:
            continue
        for uuid, fpath in get_project_sessions(project_dir):
            entry = meta.get("sessions", {}).get(uuid, {})
            if not include_deleted and entry.get("deleted_at"):
                continue
            result.append((project_dir, uuid, fpath, entry))
    result.sort(key=lambda x: os.path.getmtime(x[2]), reverse=True)
    return result


def find_session(index, project_filter=None):
    sessions = all_sessions_flat(project_filter=project_filter)
    try:
        idx = int(index) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]
    except ValueError:
        pass
    return None, None, None, None


def find_trash(index):
    meta = load_meta()
    trashed = []
    for uuid, entry in meta.get("sessions", {}).items():
        if entry.get("deleted_at"):
            trashed.append((uuid, entry))
    try:
        idx = int(index) - 1
        if 0 <= idx < len(trashed):
            return trashed[idx]
    except ValueError:
        pass
    return None, None


# ─── Commands ─────────────────────────────────────────────────

def cmd_list(project_filter=None, show_trash=False, verbose=False):
    meta = load_meta()
    if show_trash:
        trashed = []
        for uuid, entry in meta.get("sessions", {}).items():
            if entry.get("deleted_at"):
                trashed.append((uuid, entry))
        if not trashed:
            print("Trash is empty.")
            return
        print(f"{'#':>3}  {'UUID':<38}  {'Deleted':<20}  {'Title'}")
        print("-" * 110)
        for i, (uuid, entry) in enumerate(trashed, 1):
            deleted = entry.get("deleted_at", "")[:19]
            title = (entry.get("custom_title") or "")[:50]
            print(f"{i:>3}  {uuid:<38}  {deleted:<20}  {title}")
        return

    sessions = all_sessions_flat(project_filter=project_filter)
    if not sessions:
        print("No sessions found.")
        return

    multi_project = project_filter is None

    if verbose:
        print(f"{'#':>3}  {'UUID':<38}  {'Project':<34}  {'Date':<12}  {'Size':>7}  {'Msgs':>5}  Title")
        print("-" * 160)
        for i, (project_dir, uuid, fpath, entry) in enumerate(sessions, 1):
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            date_str = mtime.strftime("%m-%d %H:%M")
            size_kb = os.path.getsize(fpath) // 1024
            size_str = f"{size_kb}KB"

            custom_title = entry.get("custom_title", "")
            if custom_title:
                title = custom_title
            else:
                title = get_first_user_message(fpath)
                if len(title) > 60:
                    title = title[:57] + "..."

            stats = get_session_stats(fpath)
            msg_count = stats[0] + stats[1]

            print(f"{i:>3}  {uuid:<38}  {project_dir:<34}  {date_str:<12}  {size_str:>7}  {msg_count:>5}  {title}")
            print(f"     {'':>38}  Path: {fpath}")
    else:
        print(f"{'#':>3}  {'UUID':>10}  {'Project':<28}  {'Date':<12}  {'Size':>7}  {'Msgs':>5}  Title")
        print("-" * 140)
        for i, (project_dir, uuid, fpath, entry) in enumerate(sessions, 1):
            proj_display = project_dir
            if multi_project and len(proj_display) > 28:
                proj_display = proj_display[:25] + "..."

            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            date_str = mtime.strftime("%m-%d %H:%M")
            size_kb = os.path.getsize(fpath) // 1024
            size_str = f"{size_kb}KB"

            custom_title = entry.get("custom_title", "")
            if custom_title:
                title = custom_title
            else:
                title = get_first_user_message(fpath)
                if len(title) > 45:
                    title = title[:42] + "..."

            stats = get_session_stats(fpath)
            msg_count = stats[0] + stats[1]
            uuid_short = uuid[:8]

            print(f"{i:>3}  {uuid_short:>10}  {proj_display:<28}  {date_str:<12}  {size_str:>7}  {msg_count:>5}  {title}")

    projects = set(s[0] for s in sessions)
    print(f"\n{len(sessions)} sessions across {len(projects)} projects.")


def cmd_preview(index, project_filter=None, max_msgs=5):
    project_dir, uuid, fpath, entry = find_session(index, project_filter)
    if not fpath or not fpath.exists():
        print(f"Session #{index} not found.")
        return

    stats = get_session_stats(fpath)
    summary = get_session_summary(fpath, max_user_msgs=max_msgs)

    print("=" * 70)
    print(f"Session #{index}  —  {uuid}")
    print("=" * 70)
    print(f"  Project:      {project_dir}")
    print(f"  File size:    {os.path.getsize(fpath) // 1024} KB")
    print(f"  Total lines:  {summary['total_lines']}")
    print(f"  User msgs:    {summary['user_msg_count']}")
    print(f"  Assistant:    {stats[1]}")
    print(f"  Tools used:   {', '.join(summary['tools_used']) if summary['tools_used'] else '(none)'}")
    print(f"  File path:    {fpath}")

    if stats[3]:
        first = str(stats[3])[:19]
        last = str(stats[4])[:19]
        print(f"  First ts:     {first}")
        print(f"  Last ts:      {last}")

    if entry:
        custom_title = entry.get("custom_title", "")
        if custom_title:
            print(f"  Custom title: {custom_title}")
        if entry.get("tags"):
            print(f"  Tags:         {', '.join(entry['tags'])}")
        if entry.get("notes"):
            print(f"  Notes:        {entry['notes']}")

    current_title = stats[5]
    if len(current_title) > 80:
        current_title = current_title[:77] + "..."
    print(f"\n  [Current cc resume title: {current_title}]")

    print(f"\n  User messages ({len(summary['user_msgs'])} shown):")
    for j, msg in enumerate(summary["user_msgs"], 1):
        if len(msg) > 120:
            msg = msg[:117] + "..."
        print(f"    {j}. {msg}")
    print()


def cmd_rename(index, new_title, project_filter=None):
    project_dir, uuid, fpath, entry = find_session(index, project_filter)
    if not fpath or not fpath.exists():
        print(f"Session #{index} not found.")
        return

    # 1. Update meta.json
    meta = load_meta()
    meta.setdefault("sessions", {}).setdefault(uuid, {})
    meta["sessions"][uuid]["custom_title"] = new_title
    meta["sessions"][uuid]["renamed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_meta(meta)

    # 2. Update JSONL last-prompt entries (string replacement preserves original formatting)
    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    replaced = 0
    for line in lines:
        stripped = line.strip()
        if '"type":"last-prompt"' in stripped:
            new_line = re.sub(
                r'(?<="lastPrompt":)".*?(?<!\\)"',
                f'"{new_title}"',
                stripped,
                count=1
            )
            new_lines.append(new_line + "\n")
            replaced += 1
        else:
            new_lines.append(line)

    # If no last-prompt entry exists, append one so /resume picks it up
    if replaced == 0:
        new_lines.append(
            '{"type":"last-prompt","lastPrompt":"%s","sessionId":"%s"}\n'
            % (new_title.replace('"', '\\"'), uuid)
        )

    backup_path = fpath.with_suffix(".jsonl.bak")
    shutil.copy2(fpath, backup_path)
    with open(fpath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Renamed #{index} -> {new_title}")
    print(f"  {replaced} last-prompt entries updated" if replaced else "  Appended new last-prompt entry")
    print(f"  metadata saved + backup at .jsonl.bak")


def cmd_delete(index, project_filter=None):
    project_dir, uuid, fpath, entry = find_session(index, project_filter)
    if not fpath or not fpath.exists():
        print(f"Session #{index} not found.")
        return

    stats = get_session_stats(fpath)
    title = get_first_user_message(fpath)[:80]
    print(f"Deleting #{index}:")
    print(f"  Project: {project_dir}")
    print(f"  Title:   {title}")
    print(f"  Msgs:    {stats[0]} user + {stats[1]} assistant")
    print()

    trash_project = TRASH_DIR / project_dir
    trash_project.mkdir(parents=True, exist_ok=True)
    trash_path = trash_project / f"{uuid}.jsonl"
    shutil.move(str(fpath), str(trash_path))

    bak_path = fpath.with_suffix(".jsonl.bak")
    if bak_path.exists():
        shutil.move(str(bak_path), str(trash_project / f"{uuid}.jsonl.bak"))

    meta = load_meta()
    meta.setdefault("sessions", {}).setdefault(uuid, {})
    meta["sessions"][uuid]["deleted_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta["sessions"][uuid]["original_project_dir"] = project_dir
    save_meta(meta)

    print(f"Moved to trash. Use 'undelete' to restore.")


def cmd_undelete(index=None):
    if index:
        uuid, entry = find_trash(index)
        if not uuid:
            print(f"Trash #{index} not found.")
            return
        to_restore = [(uuid, entry)]
    else:
        meta = load_meta()
        to_restore = []
        for uuid, entry in meta.get("sessions", {}).items():
            if entry.get("deleted_at"):
                to_restore.append((uuid, entry))
        if not to_restore:
            print("Trash is empty.")
            return
        print(f"Restoring all {len(to_restore)} sessions...")

    meta = load_meta()
    for uuid, entry in to_restore:
        project_dir = entry.get("original_project_dir", "")
        if not project_dir:
            print(f"  [SKIP] {uuid}: no project dir in metadata")
            continue
        trash_file = TRASH_DIR / project_dir / f"{uuid}.jsonl"
        original_file = PROJECTS_DIR / project_dir / f"{uuid}.jsonl"
        if not trash_file.exists():
            print(f"  [SKIP] {uuid}: not found in trash")
            continue
        (PROJECTS_DIR / project_dir).mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_file), str(original_file))
        trash_bak = TRASH_DIR / project_dir / f"{uuid}.jsonl.bak"
        if trash_bak.exists():
            shutil.move(str(trash_bak), str(PROJECTS_DIR / project_dir / f"{uuid}.jsonl.bak"))
        meta["sessions"][uuid]["deleted_at"] = None
        print(f"  Restored: {uuid}")
    save_meta(meta)
    print("Done.")


def cmd_clean_test(force=False, project_filter=None):
    meta = load_meta()
    test_sessions = []
    sessions = all_sessions_flat(project_filter=project_filter)
    for project_dir, uuid, fpath, entry in sessions:
        if is_test_session(fpath):
            title = get_first_user_message(fpath)[:60]
            size_kb = os.path.getsize(fpath) // 1024
            test_sessions.append((project_dir, uuid, fpath, title, size_kb))

    if not test_sessions:
        print("No test sessions detected.")
        return

    test_sessions.sort(key=lambda x: os.path.getmtime(x[2]), reverse=True)

    print(f"Found {len(test_sessions)} suspected test sessions:\n")
    print(f"{'#':>3}  {'Project':<32}  {'Size':>6}  Title")
    print("-" * 100)
    for i, (proj, uuid, fpath, title, size) in enumerate(test_sessions, 1):
        proj_display = proj[:30] + ".." if len(proj) > 32 else proj
        print(f"{i:>3}  {proj_display:<32}  {size:>4}KB  {title}")

    if not force:
        print(f"\nRun with --force to delete all {len(test_sessions)} test sessions.")
        return

    for proj, uuid, fpath, title, size in test_sessions:
        trash_proj = TRASH_DIR / proj
        trash_proj.mkdir(parents=True, exist_ok=True)
        shutil.move(str(fpath), str(trash_proj / f"{uuid}.jsonl"))
        bak = fpath.with_suffix(".jsonl.bak")
        if bak.exists():
            shutil.move(str(bak), str(trash_proj / f"{uuid}.jsonl.bak"))
        meta.setdefault("sessions", {}).setdefault(uuid, {})
        meta["sessions"][uuid]["deleted_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["sessions"][uuid]["original_project_dir"] = proj
    save_meta(meta)
    print(f"\nDeleted {len(test_sessions)} test sessions -> trash.")


def cmd_backup(target_path):
    target = Path(target_path)
    target.mkdir(parents=True, exist_ok=True)
    session_count = 0
    for project_dir in os.listdir(PROJECTS_DIR):
        src_dir = PROJECTS_DIR / project_dir
        if not src_dir.is_dir():
            continue
        dst_dir = target / "projects" / project_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        for fname in os.listdir(src_dir):
            if fname.endswith(".jsonl") or fname.endswith(".jsonl.bak"):
                shutil.copy2(src_dir / fname, dst_dir / fname)
                session_count += 1
    if META_FILE.exists():
        shutil.copy2(META_FILE, target / "meta.json")
    if TRASH_DIR.exists():
        trash_target = target / "trash"
        if trash_target.exists():
            shutil.rmtree(trash_target)
        shutil.copytree(TRASH_DIR, trash_target)
    print(f"Backup: {session_count} files -> {target}")


def cmd_restore(source_path):
    source = Path(source_path)
    if not source.exists():
        print(f"Not found: {source}")
        return
    session_count = 0
    projects_src = source / "projects"
    if projects_src.exists():
        for project_dir in os.listdir(projects_src):
            src_dir = projects_src / project_dir
            if not src_dir.is_dir():
                continue
            dst_dir = PROJECTS_DIR / project_dir
            dst_dir.mkdir(parents=True, exist_ok=True)
            for fname in os.listdir(src_dir):
                if fname.endswith(".jsonl") or fname.endswith(".jsonl.bak"):
                    shutil.copy2(src_dir / fname, dst_dir / fname)
                    session_count += 1
    meta_src = source / "meta.json"
    if meta_src.exists():
        shutil.copy2(meta_src, META_FILE)
    trash_src = source / "trash"
    if trash_src.exists():
        if TRASH_DIR.exists():
            shutil.rmtree(TRASH_DIR)
        shutil.copytree(trash_src, TRASH_DIR)
    print(f"Restored: {session_count} files from {source}")


def cmd_tag(index, tags_str, project_filter=None):
    project_dir, uuid, fpath, entry = find_session(index, project_filter)
    if not fpath or not fpath.exists():
        print(f"Session #{index} not found.")
        return
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    meta = load_meta()
    meta.setdefault("sessions", {}).setdefault(uuid, {})
    existing = meta["sessions"][uuid].get("tags", [])
    meta["sessions"][uuid]["tags"] = existing + tags
    save_meta(meta)
    print(f"Tags {tags} added to #{index}")


def cmd_note(index, note_text, project_filter=None):
    project_dir, uuid, fpath, entry = find_session(index, project_filter)
    if not fpath or not fpath.exists():
        print(f"Session #{index} not found.")
        return
    meta = load_meta()
    meta.setdefault("sessions", {}).setdefault(uuid, {})
    meta["sessions"][uuid]["notes"] = note_text
    save_meta(meta)
    print(f"Note saved to #{index}")


# ─── Web Server ──────────────────────────────────────────────

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Session Manager</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; background: #1a1a2e; color: #e0e0e0; min-height: 100vh; }
.header { background: #16213e; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #0f3460; }
.header h1 { font-size: 20px; color: #e94560; }
.toolbar { display: flex; gap: 10px; align-items: center; }
.toolbar input, .toolbar select { background: #0f3460; border: 1px solid #1a1a4e; color: #e0e0e0; padding: 6px 12px; border-radius: 4px; font-size: 13px; }
.toolbar input:focus, .toolbar select:focus { border-color: #e94560; outline: none; }
.btn { padding: 6px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 500; transition: background .2s; }
.btn-primary { background: #e94560; color: white; }
.btn-primary:hover { background: #c73a52; }
.btn-sm { padding: 3px 10px; font-size: 11px; }
.btn-outline { background: transparent; border: 1px solid #e94560; color: #e94560; }
.btn-outline:hover { background: #e9456020; }
.btn-danger { background: #c0392b; color: white; }
.btn-danger:hover { background: #a93226; }
.btn-success { background: #27ae60; color: white; }
.btn-success:hover { background: #219a52; }
.tabs { display: flex; gap: 0; background: #16213e; padding: 0 24px; border-bottom: 1px solid #0f3460; }
.tab { padding: 10px 20px; cursor: pointer; border-bottom: 2px solid transparent; font-size: 14px; color: #999; transition: all .2s; }
.tab:hover { color: #e0e0e0; }
.tab.active { color: #e94560; border-bottom-color: #e94560; }
.stats { padding: 8px 24px; background: #16213e; font-size: 12px; color: #888; }
.content { padding: 16px 24px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
thead th { background: #16213e; padding: 8px 8px; text-align: left; font-weight: 600; color: #aaa; border-bottom: 2px solid #0f3460; position: sticky; top: 0; cursor: pointer; user-select: none; white-space: nowrap; }
thead th:hover { color: #e94560; }
tbody td { padding: 6px 8px; border-bottom: 1px solid #0f346030; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
tbody tr { cursor: pointer; transition: background .15s; }
tbody tr:hover { background: #0f346030; }
tbody tr.selected { background: #0f346060; }
.path-cell { font-size: 10px; color: #888; max-width: 350px; }
.uuid-cell { font-family: monospace; font-size: 11px; color: #aaa; }
.title-cell { max-width: 400px; }
.drawer-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 50; opacity: 0; pointer-events: none; transition: opacity 0.3s ease; }
.drawer-overlay.active { opacity: 1; pointer-events: auto; }
.drawer-panel { position: fixed; top: 0; right: 0; width: 480px; height: 100vh; background: #16213e; z-index: 51; transform: translateX(100%); transition: transform 0.3s ease; display: flex; flex-direction: column; box-shadow: -4px 0 20px rgba(0,0,0,0.5); }
.drawer-overlay.active .drawer-panel { transform: translateX(0); }
.drawer-header { padding: 16px 20px; border-bottom: 1px solid #0f3460; display: flex; justify-content: space-between; align-items: flex-start; flex-shrink: 0; }
.drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
.drawer-footer { padding: 12px 20px; border-top: 1px solid #0f3460; flex-shrink: 0; }
.drawer-title { font-size: 15px; color: #e94560; word-break: break-all; line-height: 1.4; }
.drawer-close { background: none; border: none; color: #888; font-size: 20px; cursor: pointer; padding: 0 4px; line-height: 1; }
.drawer-close:hover { color: #e94560; }
.preview-meta { display: grid; grid-template-columns: auto 1fr; gap: 4px 16px; font-size: 12px; margin-bottom: 16px; }
.preview-meta dt { color: #888; }
.preview-meta dd { color: #ccc; }
.drawer-msgs { margin-top: 12px; }
.drawer-msgs h4 { color: #888; margin-bottom: 8px; }
.msg-item { background: #1a1a2e; padding: 8px 12px; margin-bottom: 4px; border-radius: 4px; font-size: 12px; color: #bbb; border-left: 2px solid #e94560; }
.modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,.6); z-index: 100; align-items: center; justify-content: center; }
.modal-overlay.active { display: flex; }
.modal { background: #16213e; border-radius: 8px; padding: 24px; max-width: 500px; width: 90%; }
.modal h3 { color: #e94560; margin-bottom: 12px; }
.modal input { width: 100%; background: #0f3460; border: 1px solid #1a1a4e; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 14px; margin-bottom: 12px; }
.modal input:focus { border-color: #e94560; outline: none; }
.modal .modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; }
.badge-test { background: #e67e2220; color: #e67e22; }
.badge-active { background: #27ae6020; color: #27ae60; }
.empty { text-align: center; color: #666; padding: 40px; }
</style>
</head>
<body>
<div class="header">
  <h1>Session Manager</h1>
  <div class="toolbar">
    <input type="text" id="search" placeholder="Search..." oninput="renderTable()">
    <select id="projectFilter" onchange="renderTable()"><option value="">All Projects</option></select>
    <button class="btn btn-outline btn-sm" onclick="checkCleanTest()">Detect Test</button>
    <button class="btn btn-outline btn-sm" onclick="backupPrompt()">Backup</button>
    <button class="btn btn-primary btn-sm" onclick="refresh()">Refresh</button>
  </div>
</div>
<div class="tabs">
  <div class="tab active" data-tab="sessions" onclick="switchTab('sessions')">Sessions</div>
  <div class="tab" data-tab="trash" onclick="switchTab('trash')">Trash</div>
</div>
<div class="stats" id="stats">Loading...</div>
<div class="content">
  <table id="sessionTable">
    <thead>
      <tr>
        <th onclick="sortBy('id')" style="width:40px">#</th>
        <th onclick="sortBy('uuid')" style="width:90px">UUID</th>
        <th onclick="sortBy('project')" style="width:220px">Project</th>
        <th onclick="sortBy('date')" style="width:90px">Date</th>
        <th onclick="sortBy('size')" style="width:60px">Size</th>
        <th onclick="sortBy('msgs')" style="width:50px">Msgs</th>
        <th onclick="sortBy('title')">Title</th>
        <th style="width:130px">Actions</th>
      </tr>
    </thead>
    <tbody id="tableBody"></tbody>
  </table>
  <div class="empty" id="emptyMsg" style="display:none">No sessions found.</div>
</div>

<div class="drawer-overlay" id="drawerOverlay" onclick="closeDrawer()">
  <div class="drawer-panel" onclick="event.stopPropagation()">
    <div class="drawer-header">
      <div class="drawer-title" id="drawerTitle"></div>
      <button class="drawer-close" onclick="closeDrawer()">&times;</button>
    </div>
    <div class="drawer-body">
      <dl class="preview-meta" id="drawerMeta"></dl>
      <div class="drawer-msgs" id="drawerMsgs"></div>
    </div>
    <div class="drawer-footer" id="drawerActions"></div>
  </div>
</div>

<div class="modal-overlay" id="modalOverlay">
  <div class="modal" id="modalContent"></div>
</div>

<script>
let sessions = [];
let trashSessions = [];
let currentTab = 'sessions';
let selectedUuid = null;
let sortField = 'id';
let sortDir = 'asc';

async function api(path, options) {
  const r = await fetch(path, options);
  return r.json();
}

async function refresh() {
  const filter = document.getElementById('projectFilter').value;
  let url = '/api/sessions';
  if (currentTab === 'trash') url = '/api/trash';
  if (filter) url += '?project=' + encodeURIComponent(filter);
  const data = await api(url);
  if (currentTab === 'trash') {
    trashSessions = data.sessions || [];
  } else {
    sessions = data.sessions || [];
    // Update project filter
    const sel = document.getElementById('projectFilter');
    const currentVal = sel.value;
    sel.innerHTML = '<option value="">All Projects</option>';
    (data.projects || []).forEach(p => {
      sel.innerHTML += `<option value="${p}">${p}</option>`;
    });
    sel.value = currentVal;
  }
  renderTable();
  document.getElementById('stats').textContent = data.total
    ? `${data.total} sessions` + (data.projects ? ` across ${data.projects.length} projects` : '')
    : 'No sessions';
}

function renderTable() {
  const list = currentTab === 'trash' ? trashSessions : sessions;
  const search = document.getElementById('search').value.toLowerCase();
  let filtered = list;
  if (search) {
    filtered = list.filter(s =>
      (s.title||'').toLowerCase().includes(search) ||
      (s.uuid||'').toLowerCase().includes(search) ||
      (s.project||'').toLowerCase().includes(search) ||
      (s.path||'').toLowerCase().includes(search)
    );
  }

  // Sort
  filtered.sort((a, b) => {
    let va, vb;
    switch(sortField) {
      case 'id': va = a.index; vb = b.index; break;
      case 'uuid': va = a.uuid; vb = b.uuid; break;
      case 'project': va = a.project; vb = b.project; break;
      case 'date': va = a.mtime || 0; vb = b.mtime || 0; break;
      case 'size': va = a.size_kb || 0; vb = b.size_kb || 0; break;
      case 'msgs': va = a.msgs || 0; vb = b.msgs || 0; break;
      case 'title': va = a.title || ''; vb = b.title || ''; break;
      default: va = a.index; vb = b.index;
    }
    if (va < vb) return sortDir === 'asc' ? -1 : 1;
    if (va > vb) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  const tbody = document.getElementById('tableBody');
  const empty = document.getElementById('emptyMsg');
  if (filtered.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
  } else {
    empty.style.display = 'none';
    tbody.innerHTML = filtered.map((s, i) => `
      <tr class="${s.uuid === selectedUuid ? 'selected' : ''}" onclick="previewSession('${s.uuid}', ${i+1})">
        <td>${i+1}</td>
        <td class="uuid-cell" title="${s.uuid}">${s.uuid.substring(0,8)}...</td>
        <td title="${s.project}">${s.project.length > 35 ? s.project.substring(0,33)+'..' : s.project}</td>
        <td>${s.date || '-'}</td>
        <td>${s.size_kb||0}KB</td>
        <td>${s.msgs||0}</td>
        <td class="title-cell" title="${(s.title||'').replace(/"/g,'&quot;')}">${s.is_test ? '<span class="badge badge-test">TEST</span> ' : ''}${s.title||'(empty)'}</td>
        <td>
          <button class="btn btn-outline btn-sm" onclick="event.stopPropagation(); renamePrompt('${s.uuid}')" title="Rename">R</button>
          ${currentTab === 'trash'
            ? `<button class="btn btn-success btn-sm" onclick="event.stopPropagation(); doUndelete('${s.uuid}')" title="Restore">U</button>`
            : `<button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); doDelete('${s.uuid}')" title="Delete">D</button>`
          }
        </td>
      </tr>
    `).join('');
  }
}

function sortBy(field) {
  if (sortField === field) { sortDir = sortDir === 'asc' ? 'desc' : 'asc'; }
  else { sortField = field; sortDir = 'asc'; }
  renderTable();
}

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  selectedUuid = null;
  closeDrawer();
  refresh();
}

async function previewSession(uuid, idx) {
  selectedUuid = uuid;
  const data = await api('/api/sessions/' + uuid + '/preview');
  if (data.error) { alert(data.error); return; }

  document.getElementById('drawerTitle').textContent = `#${idx}  ${data.custom_title || data.first_msg || uuid}`;
  document.getElementById('drawerMeta').innerHTML = `
    <dt>UUID</dt><dd style="font-family:monospace">${uuid}</dd>
    <dt>Project</dt><dd>${data.project || '-'}</dd>
    <dt>Path</dt><dd style="font-size:10px;word-break:break-all">${data.path || '-'}</dd>
    <dt>Size</dt><dd>${data.size_kb || 0} KB / ${data.total_lines || 0} lines</dd>
    <dt>Messages</dt><dd>${data.user_msg_count || 0} user + ${data.assistant_count || 0} assistant</dd>
    <dt>Tools</dt><dd>${(data.tools_used||[]).join(', ') || '(none)'}</dd>
    <dt>First</dt><dd>${data.first_ts || '-'}</dd>
    <dt>Last</dt><dd>${data.last_ts || '-'}</dd>
    ${data.custom_title ? `<dt>Custom Title</dt><dd style="color:#e94560">${data.custom_title}</dd>` : ''}
    ${data.tags ? `<dt>Tags</dt><dd>${data.tags.join(', ')}</dd>` : ''}
    ${data.notes ? `<dt>Notes</dt><dd>${data.notes}</dd>` : ''}
  `;
  document.getElementById('drawerMsgs').innerHTML = `
    <h4>User Messages (${(data.user_msgs||[]).length} shown)</h4>
    ${(data.user_msgs||[]).map((m, j) => `<div class="msg-item">${j+1}. ${m}</div>`).join('')}
  `;
  document.getElementById('drawerActions').innerHTML = currentTab === 'trash'
    ? `<button class="btn btn-success btn-sm" onclick="doUndelete('${uuid}')">Restore</button>`
    : `<button class="btn btn-outline btn-sm" onclick="renamePrompt('${uuid}')">Rename</button>
       <button class="btn btn-danger btn-sm" onclick="doDelete('${uuid}')">Delete</button>`;
  document.getElementById('drawerOverlay').classList.add('active');
  renderTable();
}

function closeDrawer() { selectedUuid = null; document.getElementById('drawerOverlay').classList.remove('active'); renderTable(); }

function renamePrompt(uuid) {
  const modal = document.getElementById('modalContent');
  modal.innerHTML = `
    <h3>Rename Session</h3>
    <input type="text" id="renameInput" placeholder="New title...">
    <div class="modal-actions">
      <button class="btn btn-outline btn-sm" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="doRename('${uuid}')">Save</button>
    </div>
  `;
  document.getElementById('modalOverlay').classList.add('active');
  setTimeout(() => document.getElementById('renameInput').focus(), 100);
}

async function doRename(uuid) {
  const title = document.getElementById('renameInput').value.trim();
  if (!title) return;
  const data = await api('/api/sessions/' + uuid + '/rename', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title: title})
  });
  closeModal();
  if (data.ok) { refresh(); if (selectedUuid === uuid) previewSession(uuid, -1); }
}

async function doDelete(uuid) {
  if (!confirm('Delete this session? It will be moved to trash.')) return;
  const data = await api('/api/sessions/' + uuid + '/delete', {method: 'POST'});
  if (data.ok) { closeDrawer(); refresh(); }
}

async function doUndelete(uuid) {
  const data = await api('/api/trash/' + uuid + '/undelete', {method: 'POST'});
  if (data.ok) { closeDrawer(); refresh(); }
}

async function checkCleanTest() {
  const data = await api('/api/clean-test');
  if (!data.test_sessions || data.test_sessions.length === 0) {
    alert('No test sessions detected.');
    return;
  }
  const modal = document.getElementById('modalContent');
  modal.innerHTML = `
    <h3>${data.test_sessions.length} Test Sessions Detected</h3>
    <div style="max-height:300px;overflow-y:auto;margin-bottom:12px">
      ${data.test_sessions.map((s, i) => `<div style="font-size:12px;padding:4px 0;border-bottom:1px solid #0f346030">${i+1}. [${s.project}] ${s.title}</div>`).join('')}
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline btn-sm" onclick="closeModal()">Cancel</button>
      <button class="btn btn-danger btn-sm" onclick="doCleanTest()">Delete All ${data.test_sessions.length}</button>
    </div>
  `;
  document.getElementById('modalOverlay').classList.add('active');
}

async function doCleanTest() {
  const data = await api('/api/clean-test', {method: 'POST'});
  closeModal();
  if (data.ok) { refresh(); alert(`Deleted ${data.deleted} test sessions.`); }
}

function backupPrompt() {
  const modal = document.getElementById('modalContent');
  modal.innerHTML = `
    <h3>Backup Sessions</h3>
    <input type="text" id="backupPath" placeholder="Backup directory path...">
    <div class="modal-actions">
      <button class="btn btn-outline btn-sm" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="doBackup()">Backup</button>
    </div>
  `;
  document.getElementById('modalOverlay').classList.add('active');
}

async function doBackup() {
  const path = document.getElementById('backupPath').value.trim();
  if (!path) return;
  const data = await api('/api/backup', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: path})
  });
  closeModal();
  alert(data.ok ? `Backup complete: ${data.count} files` : 'Backup failed: ' + (data.error||''));
}

function closeModal() { document.getElementById('modalOverlay').classList.remove('active'); }
document.getElementById('modalOverlay').addEventListener('click', function(e) { if (e.target === this) closeModal(); });

refresh();
</script>
</body>
</html>'''


def cmd_web(port=8765):
    import http.server
    import urllib.parse
    import webbrowser
    from threading import Thread

    class SessionAPI(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Silent

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path == "/" or path == "":
                self._serve_html(HTML_TEMPLATE)

            elif path == "/api/sessions":
                qs = urllib.parse.parse_qs(parsed.query)
                proj = qs.get("project", [None])[0]
                sessions_data = all_sessions_flat(project_filter=proj)
                projects = sorted(set(
                    d for d in os.listdir(PROJECTS_DIR)
                    if (PROJECTS_DIR / d).is_dir()
                ))
                result = []
                for idx, (proj_dir, uuid, fpath, entry) in enumerate(sessions_data, 1):
                    mtime = os.path.getmtime(fpath)
                    stats = get_session_stats(fpath)
                    result.append({
                        "index": idx,
                        "uuid": uuid,
                        "project": proj_dir,
                        "path": str(fpath),
                        "date": datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M"),
                        "mtime": mtime,
                        "size_kb": os.path.getsize(fpath) // 1024,
                        "msgs": stats[0] + stats[1],
                        "title": entry.get("custom_title") or get_first_user_message(fpath),
                        "is_test": is_test_session(fpath),
                    })
                self._serve_json({"sessions": result, "projects": projects, "total": len(result)})

            elif path.startswith("/api/sessions/") and path.endswith("/preview"):
                uuid = path.split("/")[3]
                fpath = find_file_by_uuid(uuid)
                if not fpath:
                    self._serve_json({"error": "Session not found"}, 404)
                    return
                stats = get_session_stats(fpath)
                summary = get_session_summary(fpath, max_user_msgs=0)
                meta = load_meta()
                entry = meta.get("sessions", {}).get(uuid, {})
                proj_dir = _uuid_project_dir(uuid)
                self._serve_json({
                    "uuid": uuid,
                    "project": proj_dir,
                    "path": str(fpath),
                    "size_kb": os.path.getsize(fpath) // 1024,
                    "total_lines": summary["total_lines"],
                    "user_msg_count": summary["user_msg_count"],
                    "assistant_count": stats[1],
                    "tools_used": summary["tools_used"],
                    "first_ts": str(stats[3])[:19] if stats[3] else None,
                    "last_ts": str(stats[4])[:19] if stats[4] else None,
                    "first_msg": stats[5],
                    "user_msgs": summary["user_msgs"],
                    "custom_title": entry.get("custom_title"),
                    "tags": entry.get("tags"),
                    "notes": entry.get("notes"),
                })

            elif path == "/api/trash":
                meta = load_meta()
                result = []
                for idx, (uuid, entry) in enumerate(
                    sorted(
                        [(u, e) for u, e in meta.get("sessions", {}).items() if e.get("deleted_at")],
                        key=lambda x: x[1].get("deleted_at", ""), reverse=True
                    ), 1
                ):
                    result.append({
                        "index": idx,
                        "uuid": uuid,
                        "project": entry.get("original_project_dir", ""),
                        "path": str(TRASH_DIR / entry.get("original_project_dir", "") / f"{uuid}.jsonl"),
                        "date": entry.get("deleted_at", "")[:16],
                        "size_kb": 0,
                        "title": entry.get("custom_title", ""),
                        "msgs": 0,
                    })
                self._serve_json({"sessions": result, "total": len(result)})

            elif path == "/api/clean-test":
                test_list = []
                for proj_dir, uuid, fpath, entry in all_sessions_flat():
                    if is_test_session(fpath):
                        test_list.append({
                            "uuid": uuid, "project": proj_dir,
                            "title": get_first_user_message(fpath)[:80],
                            "size_kb": os.path.getsize(fpath) // 1024,
                        })
                self._serve_json({"test_sessions": test_list, "total": len(test_list)})

            else:
                self._serve_json({"error": "Not found"}, 404)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")

            content_len = int(self.headers.get("Content-Length", 0))
            body = {}
            if content_len > 0:
                body = json.loads(self.rfile.read(content_len))

            if path.startswith("/api/sessions/") and path.endswith("/rename"):
                uuid = path.split("/")[3]
                fpath = find_file_by_uuid(uuid)
                if not fpath:
                    self._serve_json({"error": "Not found"}, 404)
                    return
                new_title = body.get("title", "")
                if not new_title:
                    self._serve_json({"error": "Title required"}, 400)
                    return
                # Update meta
                meta = load_meta()
                meta.setdefault("sessions", {}).setdefault(uuid, {})
                meta["sessions"][uuid]["custom_title"] = new_title
                meta["sessions"][uuid]["renamed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_meta(meta)
                # Update JSONL
                _update_jsonl_title(fpath, new_title)
                self._serve_json({"ok": True, "title": new_title})

            elif path.startswith("/api/sessions/") and path.endswith("/delete"):
                uuid = path.split("/")[3]
                fpath = find_file_by_uuid(uuid)
                if not fpath:
                    self._serve_json({"error": "Not found"}, 404)
                    return
                proj_dir = _uuid_project_dir(uuid)
                trash_proj = TRASH_DIR / proj_dir
                trash_proj.mkdir(parents=True, exist_ok=True)
                shutil.move(str(fpath), str(trash_proj / f"{uuid}.jsonl"))
                bak = fpath.with_suffix(".jsonl.bak")
                if bak.exists():
                    shutil.move(str(bak), str(trash_proj / f"{uuid}.jsonl.bak"))
                meta = load_meta()
                meta.setdefault("sessions", {}).setdefault(uuid, {})
                meta["sessions"][uuid]["deleted_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                meta["sessions"][uuid]["original_project_dir"] = proj_dir
                save_meta(meta)
                self._serve_json({"ok": True})

            elif path.startswith("/api/trash/") and path.endswith("/undelete"):
                uuid = path.split("/")[3]
                meta = load_meta()
                entry = meta.get("sessions", {}).get(uuid, {})
                if not entry or not entry.get("deleted_at"):
                    self._serve_json({"error": "Not in trash"}, 404)
                    return
                proj_dir = entry.get("original_project_dir", "")
                trash_file = TRASH_DIR / proj_dir / f"{uuid}.jsonl"
                original_file = PROJECTS_DIR / proj_dir / f"{uuid}.jsonl"
                if trash_file.exists():
                    (PROJECTS_DIR / proj_dir).mkdir(parents=True, exist_ok=True)
                    shutil.move(str(trash_file), str(original_file))
                meta["sessions"][uuid]["deleted_at"] = None
                save_meta(meta)
                self._serve_json({"ok": True})

            elif path == "/api/clean-test":
                meta = load_meta()
                deleted = 0
                for proj_dir, uuid, fpath, entry in all_sessions_flat():
                    if is_test_session(fpath):
                        trash_proj = TRASH_DIR / proj_dir
                        trash_proj.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(fpath), str(trash_proj / f"{uuid}.jsonl"))
                        bak = fpath.with_suffix(".jsonl.bak")
                        if bak.exists():
                            shutil.move(str(bak), str(trash_proj / f"{uuid}.jsonl.bak"))
                        meta.setdefault("sessions", {}).setdefault(uuid, {})
                        meta["sessions"][uuid]["deleted_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        meta["sessions"][uuid]["original_project_dir"] = proj_dir
                        deleted += 1
                save_meta(meta)
                self._serve_json({"ok": True, "deleted": deleted})

            elif path == "/api/backup":
                target = body.get("path", "")
                if not target:
                    self._serve_json({"error": "Path required"}, 400)
                    return
                try:
                    target_path = Path(target)
                    target_path.mkdir(parents=True, exist_ok=True)
                    count = 0
                    for d in os.listdir(PROJECTS_DIR):
                        src = PROJECTS_DIR / d
                        if not src.is_dir():
                            continue
                        dst = target_path / "projects" / d
                        dst.mkdir(parents=True, exist_ok=True)
                        for fn in os.listdir(src):
                            if fn.endswith(".jsonl") or fn.endswith(".jsonl.bak"):
                                shutil.copy2(src / fn, dst / fn)
                                count += 1
                    if META_FILE.exists():
                        shutil.copy2(META_FILE, target_path / "meta.json")
                    self._serve_json({"ok": True, "count": count})
                except Exception as e:
                    self._serve_json({"error": str(e)}, 500)

            else:
                self._serve_json({"error": "Not found"}, 404)

        def _serve_html(self, content):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def _serve_json(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))


    def find_file_by_uuid(uuid):
        for d in os.listdir(PROJECTS_DIR):
            fpath = PROJECTS_DIR / d / f"{uuid}.jsonl"
            if fpath.exists():
                return fpath
        return None

    def _uuid_project_dir(uuid):
        for d in os.listdir(PROJECTS_DIR):
            if (PROJECTS_DIR / d / f"{uuid}.jsonl").exists():
                return d
        return ""

    def _update_jsonl_title(fpath, new_title):
        with open(fpath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        replaced = 0
        for line in lines:
            stripped = line.strip()
            if '"type":"last-prompt"' in stripped:
                new_line = re.sub(
                    r'(?<="lastPrompt":)".*?(?<!\\)"',
                    f'"{new_title}"',
                    stripped,
                    count=1
                )
                new_lines.append(new_line + "\n")
                replaced += 1
            else:
                new_lines.append(line)
        if replaced == 0:
            uuid = fpath.stem
            new_lines.append(
                '{"type":"last-prompt","lastPrompt":"%s","sessionId":"%s"}\n'
                % (new_title.replace('"', '\\"'), uuid)
            )
        shutil.copy2(fpath, fpath.with_suffix(".jsonl.bak"))
        with open(fpath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    server = http.server.HTTPServer(("127.0.0.1", port), SessionAPI)
    url = f"http://127.0.0.1:{port}"

    print(f"Session Manager Web UI → {url}")
    print("Press Ctrl+C to stop.")

    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(0.5)
        webbrowser.open(url)
    Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


# ─── CLI ──────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0].lower()
    rest = args[1:]

    project_filter = None
    remaining = []
    for a in rest:
        if a.startswith("--project="):
            project_filter = a.split("=", 1)[1]
        else:
            remaining.append(a)

    if cmd == "list":
        show_trash = "--trash" in remaining
        verbose = "--verbose" in remaining or "-v" in remaining
        cmd_list(project_filter=project_filter, show_trash=show_trash, verbose=verbose)

    elif cmd == "preview":
        if not remaining:
            print("Usage: preview <index> [--all] [--msgs N]")
            return
        max_msgs = 5
        args_filtered = []
        i = 0
        while i < len(remaining):
            a = remaining[i]
            if a == "--all":
                max_msgs = 0
            elif a == "--msgs":
                i += 1
                if i < len(remaining):
                    try:
                        max_msgs = int(remaining[i])
                    except ValueError:
                        print(f"Invalid --msgs value: {remaining[i]}")
                        return
                else:
                    print("Usage: preview <index> --msgs N")
                    return
            elif a.startswith("--msgs="):
                try:
                    max_msgs = int(a.split("=", 1)[1])
                except ValueError:
                    print(f"Invalid --msgs value: {a}")
                    return
            else:
                args_filtered.append(a)
            i += 1
        if not args_filtered:
            print("Usage: preview <index> [--all] [--msgs N]")
            return
        cmd_preview(args_filtered[0], project_filter=project_filter, max_msgs=max_msgs)

    elif cmd == "rename":
        if len(remaining) < 2:
            print("Usage: rename <index> <new-title>")
            return
        cmd_rename(remaining[0], " ".join(remaining[1:]), project_filter=project_filter)

    elif cmd == "delete":
        if not remaining:
            print("Usage: delete <index>")
            return
        cmd_delete(remaining[0], project_filter=project_filter)

    elif cmd == "undelete":
        idx = remaining[0] if remaining else None
        cmd_undelete(idx)

    elif cmd == "clean-test":
        force = "--force" in remaining
        cmd_clean_test(force=force, project_filter=project_filter)

    elif cmd == "backup":
        if not remaining:
            print("Usage: backup <target-path>")
            return
        cmd_backup(remaining[0])

    elif cmd == "restore":
        if not remaining:
            print("Usage: restore <source-path>")
            return
        cmd_restore(remaining[0])

    elif cmd == "tag":
        if len(remaining) < 2:
            print("Usage: tag <index> <tag1,tag2>")
            return
        cmd_tag(remaining[0], remaining[1], project_filter=project_filter)

    elif cmd == "note":
        if len(remaining) < 2:
            print("Usage: note <index> <text>")
            return
        cmd_note(remaining[0], " ".join(remaining[1:]), project_filter=project_filter)

    elif cmd == "web":
        port = int(remaining[0]) if remaining else 8765
        cmd_web(port)

    elif cmd in ("help", "--help", "-h"):
        print(__doc__)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()

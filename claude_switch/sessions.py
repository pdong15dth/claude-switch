from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import paths
from .util import (
    ToolError,
    atomic_write,
    exclusive_lock,
    prune_dirs,
    read_json_optional,
    secure_makedirs,
    ts_slug,
)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def sessions_root() -> Path:
    return paths.desktop_appdata() / "claude-code-sessions"


def account_org_dirs() -> List[Path]:
    root = sessions_root()
    if not root.is_dir():
        return []
    dirs: List[Path] = []
    for account in sorted(root.iterdir()):
        if not account.is_dir() or not UUID_RE.match(account.name):
            continue
        for org in sorted(account.iterdir()):
            if org.is_dir() and UUID_RE.match(org.name):
                dirs.append(org)
    return dirs


def _session_files(directory: Path) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    if not directory.is_dir():
        return files
    for entry in directory.iterdir():
        if entry.is_file() and entry.name.startswith("local_") and entry.name.endswith(".json"):
            files[entry.name] = entry
    return files


def _session_key(filename: str) -> str:
    return filename[len("local_") : -len(".json")]


def _tombstones(directory: Path) -> Set[str]:
    found: Set[str] = set()
    if not directory.is_dir():
        return found
    for entry in directory.iterdir():
        if entry.name.startswith("deleted_"):
            found.add(entry.name[len("deleted_") :])
    return found


def _version(path: Path) -> int:
    data = read_json_optional(path)
    last = 0
    if isinstance(data, dict):
        value = data.get("lastActivityAt") or data.get("lastFocusedAt") or 0
        try:
            last = int(value)
        except (TypeError, ValueError):
            last = 0
    try:
        mtime = int(path.stat().st_mtime * 1000)
    except OSError:
        mtime = 0
    # lastActivityAt is the canonical version. mtime changes when a file is
    # copied, so using it whenever metadata exists causes endless re-syncs.
    return last if last else mtime


def _directory_label(directory: Path) -> Tuple[str, str]:
    return directory.parent.name, directory.name


def status() -> Dict[str, Any]:
    accounts: List[Dict[str, Any]] = []
    for directory in account_org_dirs():
        account_uuid, org_uuid = _directory_label(directory)
        files = _session_files(directory)
        newest = max((_version(path) for path in files.values()), default=0)
        accounts.append(
            {
                "account_uuid": account_uuid,
                "org_uuid": org_uuid,
                "sessions": len(files),
                "deleted": len(_tombstones(directory)),
                "newest_activity_ms": newest or None,
            }
        )

    projects = paths.cc_home() / "projects"
    project_dirs = 0
    transcripts = 0
    if projects.is_dir():
        for project in projects.iterdir():
            if not project.is_dir():
                continue
            project_dirs += 1
            try:
                transcripts += sum(1 for entry in project.iterdir() if entry.suffix == ".jsonl")
            except OSError:
                pass

    return {
        "claude_desktop_code_sessions": accounts,
        "claude_code_cli": {
            "projects": project_dirs,
            "transcripts": transcripts,
            "shared": True,
        },
    }


def sync(dry_run: bool = False) -> Dict[str, Any]:
    dirs = account_org_dirs()
    if not dirs:
        raise ToolError("no Claude Desktop account session directories found")
    if len(dirs) < 2:
        raise ToolError("need at least two Claude Desktop account/org directories to sync")

    newest: Dict[str, Tuple[int, Path]] = {}
    for directory in dirs:
        for name, path in _session_files(directory).items():
            version = _version(path)
            current = newest.get(name)
            if current is None or version > current[0]:
                newest[name] = (version, path)

    planned: List[Dict[str, Any]] = []
    skipped_deleted = 0
    up_to_date = 0
    for directory in dirs:
        tombstones = _tombstones(directory)
        existing = _session_files(directory)
        account_uuid, org_uuid = _directory_label(directory)
        for name, (version, source) in sorted(newest.items()):
            key = _session_key(name)
            if key in tombstones:
                skipped_deleted += 1
                continue
            target = directory / name
            if source.parent == directory:
                up_to_date += 1
                continue
            if target.exists():
                if _version(target) >= version:
                    up_to_date += 1
                    continue
                action = "update"
            else:
                action = "copy"
            planned.append(
                {
                    "account_uuid": account_uuid,
                    "org_uuid": org_uuid,
                    "session": key,
                    "action": action,
                    "source": str(source),
                }
            )

    result: Dict[str, Any] = {
        "directories": len(dirs),
        "sessions": len(newest),
        "copies": len(planned),
        "up_to_date": up_to_date,
        "skipped_deleted": skipped_deleted,
        "dry_run": dry_run,
        "details": planned,
    }
    if dry_run:
        return result

    backups = paths.state_dir() / "sessions" / "backups"
    batch = backups / ts_slug()
    with exclusive_lock(paths.state_dir() / ".lock"):
        for item in planned:
            name = "local_%s.json" % item["session"]
            source = Path(item["source"])
            target = (
                sessions_root()
                / item["account_uuid"]
                / item["org_uuid"]
                / name
            )
            data = source.read_bytes()
            if target.exists():
                if target.read_bytes() == data:
                    continue
                backup_dir = batch / item["account_uuid"] / item["org_uuid"]
                secure_makedirs(backup_dir)
                shutil.copy2(str(target), str(backup_dir / name))
            atomic_write(target, data, mode=0o600)
            try:
                stat = source.stat()
                os.utime(target, (stat.st_atime, stat.st_mtime))
            except OSError:
                pass

    prune_dirs(backups, keep=3)
    result["backups"] = str(batch)
    return result

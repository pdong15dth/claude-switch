from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .util import (
    ToolError,
    atomic_write_json,
    exclusive_lock,
    file_mode,
    iso_now,
    prune_dirs,
    read_json,
    read_json_optional,
    run,
    secure_makedirs,
    ts_slug,
    validate_label,
)

CLAUDE_APP = Path("/Applications/Claude.app")
CLAUDE_EXECUTABLE = CLAUDE_APP / "Contents" / "MacOS" / "Claude"

AUTH_ENTRIES = [
    "Cookies",
    "Cookies-journal",
    "Cookies-wal",
    "Cookies-shm",
    "Local Storage",
    "Session Storage",
    "IndexedDB",
    "WebStorage",
    "SharedStorage",
    "Trust Tokens",
    "Trust Tokens-journal",
    "InterestGroups",
    "DIPS",
    "DIPS-wal",
    "Network Persistent State",
    "cowork-enabled-cli-ops.json",
]

PROFILE_VERSION = 1


def desktop_state_dir() -> Path:
    return paths.state_dir() / "desktop"


def profiles_dir() -> Path:
    return desktop_state_dir() / "profiles"


def backups_dir() -> Path:
    return desktop_state_dir() / "backups"


def state_path() -> Path:
    return desktop_state_dir() / "state.json"


def load_state() -> Dict[str, Any]:
    data = read_json_optional(state_path())
    if not isinstance(data, dict):
        return {"version": 1, "current": None}
    data.setdefault("version", 1)
    data.setdefault("current", None)
    return data


def save_state(state: Dict[str, Any]) -> None:
    atomic_write_json(state_path(), state, mode=0o600)


def _auth_rel_paths(root: Path) -> List[Path]:
    found: List[Path] = []
    for name in AUTH_ENTRIES:
        candidate = root / name
        if candidate.exists() or candidate.is_symlink():
            found.append(Path(name))
    return found


def _partition_rel_paths(root: Path) -> List[Path]:
    """Embedded-browser state lives in Partitions and is shared across accounts."""
    found: List[Path] = []
    partitions = root / "Partitions"
    if not partitions.is_dir():
        return found
    for part in sorted(partitions.iterdir()):
        if not part.is_dir() or part.name.startswith("."):
            continue
        for name in AUTH_ENTRIES:
            candidate = part / name
            if candidate.exists() or candidate.is_symlink():
                found.append(Path("Partitions") / part.name / name)
    return found


def _copy_rel(src_root: Path, dst_root: Path, rel: Path) -> None:
    src = src_root / rel
    dst = dst_root / rel
    secure_makedirs(dst.parent)
    if src.is_dir():
        shutil.copytree(str(src), str(dst), symlinks=True)
    else:
        shutil.copy2(str(src), str(dst))
    _tighten(dst)


def _move_rel(src_root: Path, dst_root: Path, rel: Path) -> None:
    src = src_root / rel
    dst = dst_root / rel
    secure_makedirs(dst.parent)
    os.replace(str(src), str(dst))


def _tighten(path: Path) -> None:
    if path.is_dir():
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        for child in path.rglob("*"):
            try:
                os.chmod(child, 0o700 if child.is_dir() else 0o600)
            except OSError:
                pass
    else:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def live_account_uuid() -> Optional[str]:
    cfg = read_json_optional(paths.desktop_appdata() / "config.json") or {}
    if isinstance(cfg, dict):
        value = cfg.get("lastKnownAccountUuid")
        if isinstance(value, str):
            return value
    return None


def is_running() -> bool:
    return bool(running_pids())


def running_pids() -> List[int]:
    cp = run(["ps", "-axo", "pid=,command="])
    pids: List[int] = []
    appdata = str(paths.desktop_appdata())
    for line in cp.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        command = parts[1]
        executable = command.split()[0]
        if executable.startswith(str(CLAUDE_APP) + os.sep):
            pids.append(pid)
        elif "Claude Helper" in command and ("--user-data-dir=%s" % appdata) in command:
            pids.append(pid)
    return pids


def main_pids() -> List[int]:
    cp = run(["ps", "-axo", "pid=,command="])
    pids: List[int] = []
    for line in cp.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        executable = parts[1].split()[0]
        if executable == str(CLAUDE_EXECUTABLE):
            pids.append(int(parts[0]))
    return pids


def quit_app(timeout: float = 20.0) -> None:
    if not is_running():
        return
    result = run(
        ['osascript', '-e', 'tell application "Claude" to quit'],
        timeout=10,
    )
    if result.returncode != 0:
        for pid in main_pids():
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running():
            return
        time.sleep(0.25)
    for pid in running_pids():
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    deadline = time.time() + 10
    while time.time() < deadline:
        if not is_running():
            return
        time.sleep(0.25)
    for pid in running_pids():
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
    if is_running():
        raise ToolError("could not stop Claude Desktop; quit it manually and retry")


def launch_app() -> None:
    if not CLAUDE_APP.exists():
        raise ToolError("Claude Desktop is not installed at %s" % CLAUDE_APP)
    run(["open", "-a", "Claude"])


def snapshot(label: str, force: bool = False) -> Dict[str, Any]:
    validate_label(label)
    appdata = paths.desktop_appdata()
    if not appdata.is_dir():
        raise ToolError("Claude Desktop data directory not found: %s" % appdata)

    with exclusive_lock(paths.state_dir() / ".lock"):
        if is_running():
            raise ToolError("Claude Desktop is running; quit it before snapshotting")
        return _snapshot_locked(label, force=force)


def _snapshot_locked(label: str, force: bool = False) -> Dict[str, Any]:
    appdata = paths.desktop_appdata()
    secure_makedirs(profiles_dir())
    dest = profiles_dir() / label
    if dest.exists() and not force:
        raise ToolError("profile %r already exists; pass --force to overwrite" % label)
    tmp = profiles_dir() / (".tmp-%s-%s" % (label, ts_slug()))
    if tmp.exists():
        shutil.rmtree(str(tmp), ignore_errors=True)
    secure_makedirs(tmp)

    entries: List[str] = []
    size = 0
    for rel in _auth_rel_paths(appdata):
        _copy_rel(appdata, tmp, rel)
        entries.append(str(rel))
        target = tmp / rel
        if target.is_dir():
            for child in target.rglob("*"):
                if child.is_file():
                    size += child.stat().st_size
        elif target.is_file():
            size += target.stat().st_size

    if not entries:
        shutil.rmtree(str(tmp), ignore_errors=True)
        raise ToolError(
            "no Claude Desktop login state found in %s (is an account signed in?)"
            % appdata
        )

    meta = {
        "version": PROFILE_VERSION,
        "label": label,
        "saved_at": iso_now(),
        "account_uuid": live_account_uuid(),
        "entries": entries,
        "size_bytes": size,
    }
    atomic_write_json(tmp / "meta.json", meta, mode=0o600)

    if dest.exists():
        old = profiles_dir() / (".old-%s-%s" % (label, ts_slug()))
        os.replace(str(dest), str(old))
    else:
        old = None
    try:
        os.replace(str(tmp), str(dest))
    except Exception:
        if old is not None:
            os.replace(str(old), str(dest))
        raise
    if old is not None:
        shutil.rmtree(str(old), ignore_errors=True)

    state = load_state()
    state["current"] = label
    save_state(state)
    return meta


def _checkpoint_outgoing_locked() -> Optional[str]:
    """Fold the live browser/session state back into its own profile.

    Claude rotates cookies and writes new webview storage while it runs, so a
    profile is only accurate on the machine at the moment of the last save.
    Checkpointing here is what keeps embedded-browser logins intact.
    """
    uuid = live_account_uuid()
    if not uuid:
        return None
    label = None
    profiles = list_profiles()
    for meta in profiles:
        if meta.get("account_uuid") == uuid:
            label = meta.get("label")
            break
    if label is None:
        base = "auto-" + uuid[:8]
        label = base
        taken = {meta.get("label"): meta.get("account_uuid") for meta in profiles}
        suffix = 2
        while label in taken and taken[label] != uuid:
            label = "%s-%d" % (base, suffix)
            suffix += 1
    _snapshot_locked(label, force=True)
    return label


def restore(label: str) -> Dict[str, Any]:
    validate_label(label)
    profile = profiles_dir() / label
    meta_path = profile / "meta.json"
    if not meta_path.exists():
        raise ToolError("unknown Claude Desktop profile %r" % label)
    meta = read_json(meta_path)
    if not isinstance(meta, dict) or meta.get("version") != PROFILE_VERSION:
        raise ToolError("profile %r has an unsupported format" % label)
    appdata = paths.desktop_appdata()
    if not appdata.is_dir():
        raise ToolError("Claude Desktop data directory not found: %s" % appdata)

    with exclusive_lock(paths.state_dir() / ".lock"):
        if is_running():
            raise ToolError("Claude Desktop is running; quit it before switching")

        checkpointed = _checkpoint_outgoing_locked()

        rollback = backups_dir() / ("%s-use-%s" % (ts_slug(), label))
        secure_makedirs(rollback)
        moved: List[Path] = []
        copied: List[Path] = []
        try:
            for rel in _auth_rel_paths(appdata):
                _move_rel(appdata, rollback, rel)
                moved.append(rel)
            for rel_name in meta.get("entries", []):
                rel = Path(rel_name)
                if rel.parts and rel.parts[0] == "Partitions":
                    continue
                if (profile / rel).exists() or (profile / rel).is_symlink():
                    _copy_rel(profile, appdata, rel)
                    copied.append(rel)
            _patch_config(meta.get("account_uuid"))
        except Exception:
            for rel in reversed(copied):
                dst = appdata / rel
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(str(dst), ignore_errors=True)
                elif dst.exists() or dst.is_symlink():
                    dst.unlink()
            for rel in reversed(moved):
                src = rollback / rel
                dst = appdata / rel
                if not src.exists() and not src.is_symlink():
                    continue
                if dst.exists() or dst.is_symlink():
                    if dst.is_dir() and not dst.is_symlink():
                        shutil.rmtree(str(dst), ignore_errors=True)
                    else:
                        dst.unlink()
                _move_rel(rollback, appdata, rel)
            raise

        state = load_state()
        state["current"] = label
        save_state(state)
        prune_dirs(backups_dir(), keep=5)
        return {"meta": meta, "checkpointed": checkpointed}


def import_browser(label: str) -> Dict[str, Any]:
    """Copy embedded-browser data from a profile into the live app once.

    Older profiles created before partitions were shared contain browser
    cookies/storage. This brings them back into the live app so the browser is
    logged in again; afterwards partitions stay shared across Claude accounts.
    """
    validate_label(label)
    profile = profiles_dir() / label
    if not (profile / "meta.json").exists():
        raise ToolError("unknown Claude Desktop profile %r" % label)
    appdata = paths.desktop_appdata()
    if not appdata.is_dir():
        raise ToolError("Claude Desktop data directory not found: %s" % appdata)

    with exclusive_lock(paths.state_dir() / ".lock"):
        if is_running():
            raise ToolError("Claude Desktop is running; quit it before importing")

        backup = backups_dir() / ("%s-browser-%s" % (ts_slug(), label))
        secure_makedirs(backup)
        moved: List[Path] = []
        copied: List[Path] = []
        try:
            for rel in _partition_rel_paths(appdata):
                _move_rel(appdata, backup, rel)
                moved.append(rel)
            for rel in _partition_rel_paths(profile):
                _copy_rel(profile, appdata, rel)
                copied.append(rel)
        except Exception:
            for rel in reversed(copied):
                dst = appdata / rel
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(str(dst), ignore_errors=True)
                elif dst.exists() or dst.is_symlink():
                    dst.unlink()
            for rel in reversed(moved):
                src = backup / rel
                dst = appdata / rel
                if not src.exists() and not src.is_symlink():
                    continue
                if dst.exists() or dst.is_symlink():
                    if dst.is_dir() and not dst.is_symlink():
                        shutil.rmtree(str(dst), ignore_errors=True)
                    else:
                        dst.unlink()
                _move_rel(backup, appdata, rel)
            raise

        prune_dirs(backups_dir(), keep=5)
        return {"backup": str(backup), "entries": len(copied)}


def clear_live() -> Path:
    appdata = paths.desktop_appdata()
    if not appdata.is_dir():
        raise ToolError("Claude Desktop data directory not found: %s" % appdata)
    with exclusive_lock(paths.state_dir() / ".lock"):
        if is_running():
            raise ToolError("Claude Desktop is running; quit it before clearing")
        backup = backups_dir() / ("%s-clear" % ts_slug())
        secure_makedirs(backup)
        for rel in _auth_rel_paths(appdata):
            _move_rel(appdata, backup, rel)
        _clear_last_account()
        state = load_state()
        state["current"] = None
        save_state(state)
        prune_dirs(backups_dir(), keep=5)
        return backup


def _clear_last_account() -> None:
    path = paths.desktop_appdata() / "config.json"
    cfg = read_json_optional(path)
    if not isinstance(cfg, dict):
        return
    cfg["lastKnownAccountUuid"] = None
    atomic_write_json(path, cfg, mode=file_mode(path))


def _patch_config(account_uuid: Optional[str]) -> None:
    path = paths.desktop_appdata() / "config.json"
    cfg = read_json_optional(path)
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        return
    if account_uuid:
        cfg["lastKnownAccountUuid"] = account_uuid
    atomic_write_json(path, cfg, mode=file_mode(path))


def current_label() -> Optional[str]:
    live_uuid = live_account_uuid()
    if not live_uuid:
        return None
    matches = []
    for meta in list_profiles():
        if meta.get("account_uuid") == live_uuid:
            matches.append(meta["label"])
    if len(matches) == 1:
        return matches[0]
    if matches:
        state = load_state()
        if state.get("current") in matches:
            return state["current"]
        return matches[0]
    return None


def list_profiles() -> List[Dict[str, Any]]:
    base = profiles_dir()
    if not base.is_dir():
        return []
    rows = []
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = read_json(meta_path)
        except Exception:
            continue
        if isinstance(meta, dict):
            meta.setdefault("label", entry.name)
            rows.append(meta)
    return rows


def remove(label: str) -> None:
    validate_label(label)
    profile = profiles_dir() / label
    if not profile.is_dir():
        raise ToolError("unknown Claude Desktop profile %r" % label)
    with exclusive_lock(paths.state_dir() / ".lock"):
        shutil.rmtree(str(profile))
        state = load_state()
        if state.get("current") == label:
            state["current"] = None
            save_state(state)



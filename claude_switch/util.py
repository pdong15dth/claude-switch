from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class ToolError(Exception):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(cmd, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolError("command not found: %s" % cmd[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError("command timed out: %s" % " ".join(cmd)) from exc
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise ToolError("%s failed: %s" % (" ".join(cmd), detail))
    return cp


def secure_makedirs(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def file_mode(path: Path) -> int:
    try:
        return Path(path).stat().st_mode & 0o777
    except OSError:
        return 0o600


def atomic_write(path: Path, data: bytes, mode: Optional[int] = None) -> None:
    path = Path(path)
    secure_makedirs(path.parent)
    if mode is None:
        mode = file_mode(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".claude-switch-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(path: Path, obj: Any, mode: Optional[int] = None) -> None:
    body = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write(path, body, mode=mode)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_json_optional(path: Path) -> Optional[Any]:
    try:
        return read_json(path)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        raise ToolError("cannot read %s: %s" % (path, exc)) from exc


def read_text_optional(path: Path) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def backup_file(path: Path, backup_dir: Path, tag: str, keep: int = 5) -> Optional[Path]:
    path = Path(path)
    if not path.exists():
        return None
    secure_makedirs(backup_dir)
    dest = backup_dir / ("%s-%s-%s" % (tag, ts_slug(), path.name))
    shutil.copy2(str(path), str(dest))
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    prune_dir(backup_dir, keep=keep)
    return dest


def prune_dir(directory: Path, keep: int = 5) -> None:
    directory = Path(directory)
    if not directory.is_dir():
        return
    items = sorted(
        (p for p in directory.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in items[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def prune_dirs(directory: Path, keep: int = 5) -> None:
    directory = Path(directory)
    if not directory.is_dir():
        return
    items = sorted(
        (p for p in directory.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in items[keep:]:
        shutil.rmtree(str(stale), ignore_errors=True)


@contextlib.contextmanager
def exclusive_lock(path: Path):
    path = Path(path)
    secure_makedirs(path.parent)
    handle = open(path, "a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ToolError("another claude-switch operation is running") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def human_ms(epoch_ms: Optional[int]) -> str:
    if not epoch_ms:
        return "unknown"
    dt = datetime.fromtimestamp(epoch_ms / 1000.0)
    return dt.strftime("%Y-%m-%d %H:%M")


def short_uuid(value: Optional[str]) -> str:
    if not value:
        return "-"
    return value[:8]


def confirm(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    import sys

    if not sys.stdin.isatty():
        raise ToolError("confirmation required; pass --yes in non-interactive mode")
    answer = input("%s [y/N] " % prompt).strip().lower()
    if answer not in ("y", "yes"):
        raise ToolError("aborted")


def validate_label(label: str) -> None:
    """Labels become directory names and keychain accounts.

    Unicode and spaces are allowed so Vietnamese names work. Only characters
    that are unsafe in a path or impossible to type are rejected.
    """
    if not label or len(label) > 64:
        raise ToolError("label must be 1-64 characters")
    if label != label.strip():
        raise ToolError("label must not start or end with whitespace")
    if label.startswith("."):
        raise ToolError("label must not start with a dot")
    if "/" in label or "\\" in label or "\x00" in label:
        raise ToolError("label must not contain / or \\")
    if any(ord(char) < 32 for char in label):
        raise ToolError("label must not contain control characters")

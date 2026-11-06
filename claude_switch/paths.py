from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("HOME") or str(Path.home()))


def state_dir() -> Path:
    return Path(os.environ.get("CLAUDE_SWITCH_HOME", str(home() / ".claude-switch")))


def cc_home() -> Path:
    return Path(os.environ.get("CLAUDE_SWITCH_CLAUDE_HOME", str(home() / ".claude")))


def cc_json() -> Path:
    return Path(os.environ.get("CLAUDE_SWITCH_CLAUDE_JSON", str(home() / ".claude.json")))


def cc_credentials_file() -> Path:
    return cc_home() / ".credentials.json"


def desktop_appdata() -> Path:
    return Path(
        os.environ.get(
            "CLAUDE_SWITCH_CLAUDE_APPDATA",
            str(home() / "Library" / "Application Support" / "Claude"),
        )
    )


def keychain_backend() -> str:
    return os.environ.get("CLAUDE_SWITCH_KEYCHAIN", "security")

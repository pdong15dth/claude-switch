from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional

from . import paths
from .util import ToolError, atomic_write_json, read_json_optional


class Keychain:
    """Thin wrapper over the macOS `security` CLI, with a file backend for tests."""

    def __init__(self, backend: Optional[str] = None) -> None:
        self.backend = backend or paths.keychain_backend()
        self._file = paths.state_dir() / "keychain.json"

    def _load_file(self) -> Dict[str, Dict[str, str]]:
        data = read_json_optional(self._file)
        if not isinstance(data, dict):
            return {}
        return data

    def get(self, service: str, account: str) -> Optional[str]:
        if self.backend == "file":
            return self._load_file().get(service, {}).get(account)
        cp = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if cp.returncode != 0:
            cp = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if cp.returncode != 0:
                return None
        value = cp.stdout
        if value.endswith("\n"):
            value = value[:-1]
        return value

    def set(self, service: str, account: str, secret: str) -> None:
        if self.backend == "file":
            data = self._load_file()
            data.setdefault(service, {})[account] = secret
            atomic_write_json(self._file, data, mode=0o600)
            return
        cp = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                secret,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise ToolError("cannot write keychain item %s: %s" % (service, detail))

    def delete(self, service: str, account: str) -> bool:
        if self.backend == "file":
            data = self._load_file()
            bucket = data.get(service)
            if not bucket or account not in bucket:
                return False
            del bucket[account]
            if not bucket:
                data.pop(service, None)
            atomic_write_json(self._file, data, mode=0o600)
            return True
        cp = subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", account],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return cp.returncode == 0

    def has(self, service: str, account: str) -> bool:
        return self.get(service, account) is not None


def parse_json_object(raw: Optional[str], where: str) -> Optional[dict]:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ToolError("%s is not valid JSON: %s" % (where, exc)) from exc
    if not isinstance(data, dict):
        raise ToolError("%s is not a JSON object" % where)
    return data

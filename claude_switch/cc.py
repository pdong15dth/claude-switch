from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from . import paths
from .keychain import Keychain, parse_json_object
from .util import (
    ToolError,
    atomic_write,
    atomic_write_json,
    backup_file,
    exclusive_lock,
    file_mode,
    iso_now,
    read_json_optional,
    run,
    validate_label,
)

LIVE_SERVICE = "Claude Code-credentials"
STORE_SERVICE = "claude-switch-cc"
META_VERSION = 1


def meta_path():
    return paths.state_dir() / "cc.json"


def load_meta() -> Dict[str, Any]:
    data = read_json_optional(meta_path())
    if not isinstance(data, dict):
        return {"version": META_VERSION, "current": None, "accounts": {}}
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        data["accounts"] = {}
    data.setdefault("version", META_VERSION)
    data.setdefault("current", None)
    return data


def save_meta(meta: Dict[str, Any]) -> None:
    atomic_write_json(meta_path(), meta, mode=0o600)


def live_credentials_raw(keychain: Keychain) -> Optional[str]:
    raw = keychain.get(LIVE_SERVICE, getpass.getuser())
    if raw is not None:
        return raw
    file_raw = None
    cred_file = paths.cc_credentials_file()
    if cred_file.exists():
        file_raw = cred_file.read_text(encoding="utf-8")
    return file_raw


def _oauth_block(credentials: Dict[str, Any]) -> Dict[str, Any]:
    oauth = credentials.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise ToolError(
            "credentials do not contain claudeAiOauth (is this a subscription login?)"
        )
    return oauth


def _account_label_for(meta: Dict[str, Any], account_uuid: Optional[str]) -> Optional[str]:
    if not account_uuid:
        return None
    matches = [
        label
        for label, info in meta.get("accounts", {}).items()
        if info.get("account_uuid") == account_uuid
    ]
    if len(matches) == 1:
        return matches[0]
    if meta.get("current") in matches:
        return meta["current"]
    return matches[0] if matches else None


def live_summary(keychain: Keychain) -> Dict[str, Any]:
    cfg = read_json_optional(paths.cc_json()) or {}
    account = cfg.get("oauthAccount") if isinstance(cfg, dict) else {}
    if not isinstance(account, dict):
        account = {}
    summary: Dict[str, Any] = {
        "email": account.get("emailAddress"),
        "account_uuid": account.get("accountUuid"),
        "organization_uuid": account.get("organizationUuid"),
        "billing_type": account.get("billingType"),
    }
    raw = live_credentials_raw(keychain)
    if raw:
        try:
            credentials = json.loads(raw)
            oauth = credentials.get("claudeAiOauth") or {}
            summary["expires_at"] = oauth.get("expiresAt")
            summary["refresh_expires_at"] = oauth.get("refreshTokenExpiresAt")
            summary["subscription_type"] = oauth.get("subscriptionType")
            summary["rate_limit_tier"] = oauth.get("rateLimitTier")
        except (json.JSONDecodeError, AttributeError):
            summary["credentials_error"] = "unreadable credentials"
    meta = load_meta()
    summary["label"] = _account_label_for(meta, summary.get("account_uuid"))
    return summary


def _store_blob(keychain: Keychain, label: str, blob: Dict[str, Any]) -> None:
    keychain.set(STORE_SERVICE, label, json.dumps(blob, separators=(",", ":")))


def _load_blob(keychain: Keychain, label: str) -> Dict[str, Any]:
    raw = keychain.get(STORE_SERVICE, label)
    if raw is None:
        raise ToolError("no saved Claude Code login named %r" % label)
    blob = parse_json_object(raw, "saved login %r" % label)
    if not isinstance(blob.get("credentials"), dict):
        raise ToolError("saved login %r is corrupted" % label)
    return blob


def _write_live_credentials(keychain: Keychain, credentials: Dict[str, Any]) -> None:
    raw = json.dumps(credentials, separators=(",", ":"))
    keychain.set(LIVE_SERVICE, getpass.getuser(), raw)
    atomic_write(paths.cc_credentials_file(), raw.encode("utf-8"), mode=0o600)


def _patch_claude_json(account: Dict[str, Any]) -> None:
    path = paths.cc_json()
    cfg = read_json_optional(path)
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ToolError("%s is not a JSON object" % path)
    backup_file(path, paths.state_dir() / "backups", "claude-json")
    if account:
        cfg["oauthAccount"] = account
    atomic_write_json(path, cfg, mode=file_mode(path))


def add(label: str, keychain: Optional[Keychain] = None, force: bool = False) -> Dict[str, Any]:
    keychain = keychain or Keychain()
    validate_label(label)
    with exclusive_lock(paths.state_dir() / ".lock"):
        raw = live_credentials_raw(keychain)
        if raw is None:
            raise ToolError(
                "no Claude Code credentials found in Keychain or %s"
                % paths.cc_credentials_file()
            )
        credentials = parse_json_object(raw, "live Claude Code credentials")
        assert credentials is not None
        oauth = _oauth_block(credentials)
        cfg = read_json_optional(paths.cc_json()) or {}
        account = cfg.get("oauthAccount") if isinstance(cfg, dict) else {}
        if not isinstance(account, dict):
            account = {}

        meta = load_meta()
        if label in meta["accounts"] and not force:
            raise ToolError("login %r already exists; pass --force to overwrite" % label)

        blob = {
            "version": 1,
            "label": label,
            "saved_at": iso_now(),
            "credentials": credentials,
            "oauthAccount": account,
        }
        _store_blob(keychain, label, blob)
        meta["accounts"][label] = {
            "email": account.get("emailAddress"),
            "account_uuid": account.get("accountUuid"),
            "organization_uuid": account.get("organizationUuid"),
            "subscription_type": oauth.get("subscriptionType"),
            "rate_limit_tier": oauth.get("rateLimitTier"),
            "saved_at": blob["saved_at"],
            "expires_at": oauth.get("expiresAt"),
            "refresh_expires_at": oauth.get("refreshTokenExpiresAt"),
        }
        meta["current"] = label
        save_meta(meta)
        return meta["accounts"][label]


def use(
    label: str, keychain: Optional[Keychain] = None, force: bool = False
) -> Dict[str, Any]:
    keychain = keychain or Keychain()
    with exclusive_lock(paths.state_dir() / ".lock"):
        meta = load_meta()
        if label not in meta["accounts"]:
            raise ToolError("unknown Claude Code login %r" % label)
        running = running_claude_cli()
        if running and not force:
            raise ToolError(
                "Claude Code is running (pid %s). Close those sessions or pass --force."
                % ", ".join(str(pid) for pid in running)
            )
        blob = _load_blob(keychain, label)
        credentials = blob["credentials"]
        _oauth_block(credentials)

        _checkpoint_outgoing(keychain, meta)

        _write_live_credentials(keychain, credentials)
        account = blob.get("oauthAccount") or {}
        if account:
            _patch_claude_json(account)
        meta = load_meta()
        meta["current"] = label
        save_meta(meta)
        return meta["accounts"][label]


def login(
    label: str,
    keychain: Optional[Keychain] = None,
    force: bool = False,
    timeout: int = 600,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Sign in with another subscription, then save it under `label`.

    The login that is active before signing in is preserved as a profile so the
    flow never loses the current account.
    """
    keychain = keychain or Keychain()
    validate_label(label)
    meta = load_meta()
    if label in meta["accounts"] and not force:
        raise ToolError("login %r already exists; pass --force to overwrite" % label)
    running = running_claude_cli()
    if running:
        raise ToolError(
            "Claude Code is running (pid %s). Close those sessions before adding an account."
            % ", ".join(str(pid) for pid in running)
        )

    live = live_summary(keychain)
    before_uuid = live.get("account_uuid")
    preserved = None
    if live.get("label") is None and before_uuid:
        preserved = _auto_label(meta, live)
        add(preserved, keychain=keychain, force=True)

    command = ["claude", "auth", "login"]
    if email:
        command.extend(["--email", email])
    try:
        completed = subprocess.run(command, timeout=timeout)
    except FileNotFoundError as exc:
        raise ToolError("claude CLI not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError("login timed out after %s seconds" % timeout) from exc
    if completed.returncode != 0:
        raise ToolError(
            "claude auth login failed with exit code %d" % completed.returncode
        )

    after = live_summary(keychain)
    after_uuid = after.get("account_uuid")
    info = add(label, keychain=keychain, force=force)
    return {
        "info": info,
        "preserved_label": preserved,
        "before_uuid": before_uuid,
        "after_uuid": after_uuid,
        "same_account": bool(before_uuid and before_uuid == after_uuid),
    }


def _auto_label(meta: Dict[str, Any], live: Dict[str, Any]) -> str:
    email = live.get("email") or ""
    base = email.split("@")[0] if email else "account"
    base = re.sub(r"[^A-Za-z0-9._@+-]", "-", base) or "account"
    uuid = live.get("account_uuid") or ""
    candidate = "auto-" + base
    accounts = meta.get("accounts", {})
    if candidate in accounts and accounts[candidate].get("account_uuid") != uuid:
        candidate = "auto-%s-%s" % (base, uuid[:8])
    suffix = 2
    while candidate in accounts and accounts[candidate].get("account_uuid") != uuid:
        candidate = "auto-%s-%s-%d" % (base, uuid[:8], suffix)
        suffix += 1
    return candidate


def _checkpoint_outgoing(keychain: Keychain, meta: Dict[str, Any]) -> None:
    """Re-save the live login before switching so refreshed tokens are not lost."""
    cfg = read_json_optional(paths.cc_json()) or {}
    account = cfg.get("oauthAccount") if isinstance(cfg, dict) else {}
    if not isinstance(account, dict):
        return
    label = _account_label_for(meta, account.get("accountUuid"))
    if not label:
        return
    raw = live_credentials_raw(keychain)
    if raw is None:
        return
    try:
        credentials = json.loads(raw)
    except json.JSONDecodeError:
        return
    blob = {
        "version": 1,
        "label": label,
        "saved_at": iso_now(),
        "credentials": credentials,
        "oauthAccount": account,
    }
    _store_blob(keychain, label, blob)
    meta["accounts"][label]["saved_at"] = blob["saved_at"]
    meta["accounts"][label]["expires_at"] = credentials["claudeAiOauth"].get(
        "expiresAt", meta["accounts"][label].get("expires_at")
    )
    save_meta(meta)


def remove(label: str, keychain: Optional[Keychain] = None) -> None:
    keychain = keychain or Keychain()
    with exclusive_lock(paths.state_dir() / ".lock"):
        meta = load_meta()
        if label not in meta["accounts"]:
            raise ToolError("unknown Claude Code login %r" % label)
        keychain.delete(STORE_SERVICE, label)
        del meta["accounts"][label]
        if meta.get("current") == label:
            meta["current"] = None
        save_meta(meta)


def list_accounts(keychain: Optional[Keychain] = None) -> List[Dict[str, Any]]:
    keychain = keychain or Keychain()
    meta = load_meta()
    live = live_summary(keychain)
    rows = []
    for label in sorted(meta["accounts"]):
        info = dict(meta["accounts"][label])
        info["label"] = label
        info["active"] = (
            live.get("label") == label
            or (
                info.get("account_uuid") is not None
                and info.get("account_uuid") == live.get("account_uuid")
            )
        )
        rows.append(info)
    return rows


def running_claude_cli() -> List[int]:
    cp = run(["ps", "-axo", "pid=,command="])
    pids: List[int] = []
    for line in cp.stdout.splitlines():
        match = re.match(r"\s*(\d+)\s+(.*)", line)
        if not match:
            continue
        pid = int(match.group(1))
        command = match.group(2)
        if ".app/" in command or "claude-switch" in command:
            continue
        first = command.split()[0]
        base = os.path.basename(first)
        if base == "claude" or "claude-code/cli.js" in command:
            pids.append(pid)
    return pids



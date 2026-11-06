from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import __version__, cc
from .keychain import Keychain

API_URL = "https://api.anthropic.com/api/oauth/usage"
TIMEOUT = 6

WINDOWS = (
    ("five_hour", "5-hour"),
    ("seven_day", "Weekly"),
    ("seven_day_opus", "Opus weekly"),
    ("seven_day_sonnet", "Sonnet weekly"),
    ("seven_day_oauth_apps", "OAuth apps weekly"),
)


def _percent(utilization: Any) -> Optional[float]:
    try:
        value = float(utilization)
    except (TypeError, ValueError):
        return None
    return round(value * 1000) / 10


def parse_usage(payload: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
    now = time.time() if now is None else now
    windows = []
    for key, label in WINDOWS:
        raw = payload.get(key)
        if not isinstance(raw, dict):
            continue
        percent = _percent(raw.get("utilization"))
        if percent is None:
            continue
        resets_at = raw.get("resets_at")
        if isinstance(resets_at, (int, float)) and resets_at <= now:
            continue
        windows.append(
            {
                "key": key,
                "label": label,
                "used_percent": percent,
                "resets_at": int(resets_at) if isinstance(resets_at, (int, float)) else None,
            }
        )
    return windows


def _base(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": False,
        "label": summary.get("label"),
        "email": summary.get("email"),
        "subscription_type": summary.get("subscription_type"),
    }


def _error(base: Dict[str, Any], code: str, message: str) -> Dict[str, Any]:
    return {**base, "error": code, "message": message}


def build_usage(keychain: Optional[Keychain] = None) -> Dict[str, Any]:
    keychain = keychain or Keychain()
    summary = cc.live_summary(keychain)
    base = _base(summary)

    raw = cc.live_credentials_raw(keychain)
    if not raw:
        return _error(
            base,
            "no_credentials",
            "No Claude Code login found. Run `claude /login` or add an account.",
        )
    try:
        credentials = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _error(base, "invalid_credentials", "Claude Code credentials are not readable.")
    oauth = credentials.get("claudeAiOauth") if isinstance(credentials, dict) else None
    if not isinstance(oauth, dict):
        return _error(base, "not_subscription", "The live login is not a subscription login.")
    token = oauth.get("accessToken")
    if not token:
        return _error(base, "no_token", "Claude Code credentials have no access token.")

    expires_at = oauth.get("expiresAt")
    if isinstance(expires_at, (int, float)) and expires_at <= time.time() * 1000:
        return _error(
            base,
            "token_expired",
            "OAuth token expired. Open Claude Code once to refresh it, then retry.",
        )

    request = urllib.request.Request(
        API_URL,
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
            "User-Agent": "claude-switch/%s" % __version__,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return _error(
                base,
                "token_expired",
                "OAuth token expired. Open Claude Code once to refresh it, then retry.",
            )
        return _error(base, "http_error", "Usage endpoint returned HTTP %s." % exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _error(base, "network_error", "Cannot reach the usage endpoint: %s" % exc)

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return _error(base, "invalid_response", "Usage endpoint returned invalid JSON.")
    if not isinstance(payload, dict):
        return _error(base, "invalid_response", "Usage endpoint returned an unexpected payload.")

    windows = parse_usage(payload)
    if not windows:
        return _error(base, "no_limits", "No active plan limits reported for this account.")
    return {
        **base,
        "ok": True,
        "fetched_at": int(time.time()),
        "windows": windows,
    }


def format_usage(data: Dict[str, Any]) -> str:
    if not data.get("ok"):
        return "usage unavailable: %s" % (data.get("message") or data.get("error"))
    who = data.get("label") or data.get("email") or "current account"
    plan = data.get("subscription_type")
    lines = ["Usage — %s%s" % (who, " (%s)" % plan if plan else "")]
    for window in data.get("windows") or []:
        lines.append(
            "  %-14s %5.1f%%  %s"
            % (window["label"], window["used_percent"], _reset_text(window.get("resets_at")))
        )
    return "\n".join(lines)


def _reset_text(resets_at: Optional[int]) -> str:
    if not resets_at:
        return ""
    remaining = int(resets_at - time.time())
    if remaining <= 0:
        return "resetting"
    hours, minutes = divmod(remaining // 60, 60)
    if hours >= 48:
        return "resets %s" % time.strftime("%a %H:%M", time.localtime(resets_at))
    if hours:
        return "resets in %dh %dm" % (hours, minutes)
    return "resets in %dm" % minutes

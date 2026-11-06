from __future__ import annotations

from typing import Any, Dict

from . import cc, desktop, paths
from .keychain import Keychain


def build_status() -> Dict[str, Any]:
    keychain = Keychain()
    cc_meta = cc.load_meta()
    cc_live = cc.live_summary(keychain)
    cc_accounts = []
    for row in cc.list_accounts(keychain):
        cc_accounts.append(
            {
                "label": row["label"],
                "email": row.get("email"),
                "subscription_type": row.get("subscription_type"),
                "account_uuid": row.get("account_uuid"),
                "saved_at": row.get("saved_at"),
                "expires_at": row.get("expires_at"),
                "active": row.get("active", False),
            }
        )

    desktop_profiles = []
    live_uuid = desktop.live_account_uuid()
    current_desktop = desktop.current_label()
    for meta in desktop.list_profiles():
        desktop_profiles.append(
            {
                "label": meta.get("label"),
                "account_uuid": meta.get("account_uuid"),
                "saved_at": meta.get("saved_at"),
                "size_bytes": meta.get("size_bytes"),
                "active": meta.get("label") == current_desktop,
            }
        )

    return {
        "claude_code": {
            "current_label": cc_live.get("label"),
            "accounts": cc_accounts,
            "live": {
                "email": cc_live.get("email"),
                "account_uuid": cc_live.get("account_uuid"),
                "organization_uuid": cc_live.get("organization_uuid"),
                "expires_at": cc_live.get("expires_at"),
                "refresh_expires_at": cc_live.get("refresh_expires_at"),
                "subscription_type": cc_live.get("subscription_type"),
                "source": "keychain",
            },
            "state_dir": str(paths.state_dir()),
        },
        "desktop": {
            "current_label": current_desktop,
            "accounts": desktop_profiles,
            "running": desktop.is_running(),
            "live_account_uuid": live_uuid,
            "appdata": str(paths.desktop_appdata()),
        },
    }

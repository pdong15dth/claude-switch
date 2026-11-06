from __future__ import annotations

import getpass
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_switch import cc, desktop, status
from claude_switch.keychain import Keychain


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.appdata = self.root / "Claude"
        self.cc_home = self.root / ".claude"
        self.cc_json = self.root / ".claude.json"
        self.state = self.root / ".claude-switch"

        os.environ["CLAUDE_SWITCH_HOME"] = str(self.state)
        os.environ["CLAUDE_SWITCH_CLAUDE_HOME"] = str(self.cc_home)
        os.environ["CLAUDE_SWITCH_CLAUDE_JSON"] = str(self.cc_json)
        os.environ["CLAUDE_SWITCH_CLAUDE_APPDATA"] = str(self.appdata)
        os.environ["CLAUDE_SWITCH_KEYCHAIN"] = "file"

        self.appdata.mkdir(parents=True)
        self.cc_home.mkdir(parents=True)

        self.kc = Keychain()

    def tearDown(self) -> None:
        for key in (
            "CLAUDE_SWITCH_HOME",
            "CLAUDE_SWITCH_CLAUDE_HOME",
            "CLAUDE_SWITCH_CLAUDE_JSON",
            "CLAUDE_SWITCH_CLAUDE_APPDATA",
            "CLAUDE_SWITCH_KEYCHAIN",
        ):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def seed_cc(self, email: str, account_uuid: str, token: str) -> None:
        credentials = {
            "claudeAiOauth": {
                "accessToken": token,
                "refreshToken": "refresh-" + token,
                "expiresAt": 1792485997221,
                "refreshTokenExpiresAt": 1794866475221,
                "subscriptionType": "team",
                "rateLimitTier": "default_claude_max_5x",
            }
        }
        self.kc.set(cc.LIVE_SERVICE, getpass.getuser(), json.dumps(credentials))
        cfg = {
            "oauthAccount": {
                "emailAddress": email,
                "accountUuid": account_uuid,
                "organizationUuid": "org-" + account_uuid,
            },
            "theme": "dark",
            "projects": {"/tmp/demo": {"allowedTools": []}},
        }
        self.write_json(self.cc_json, cfg)


class ClaudeCodeTests(BaseCase):
    def test_add_and_switch_keeps_settings(self) -> None:
        self.seed_cc("work@example.com", "uuid-work", "token-work")
        with mock.patch.object(cc, "running_claude_cli", return_value=[]):
            info = cc.add("work")
            self.assertEqual(info["email"], "work@example.com")

            self.seed_cc("personal@example.com", "uuid-personal", "token-personal")
            cc.add("personal")

            labels = [row["label"] for row in cc.list_accounts(self.kc)]
            self.assertEqual(labels, ["personal", "work"])

            cc.use("work")

        live = json.loads(self.kc.get(cc.LIVE_SERVICE, getpass.getuser()))
        self.assertEqual(live["claudeAiOauth"]["accessToken"], "token-work")
        file_creds = json.loads((self.cc_home / ".credentials.json").read_text())
        self.assertEqual(file_creds["claudeAiOauth"]["accessToken"], "token-work")

        cfg = json.loads(self.cc_json.read_text())
        self.assertEqual(cfg["oauthAccount"]["emailAddress"], "work@example.com")
        self.assertEqual(cfg["theme"], "dark")
        self.assertIn("/tmp/demo", cfg["projects"])

    def test_use_refuses_while_claude_running(self) -> None:
        self.seed_cc("work@example.com", "uuid-work", "token-work")
        cc.add("work")
        with mock.patch.object(cc, "running_claude_cli", return_value=[4242]):
            with self.assertRaises(Exception):
                cc.use("work")

    def test_current_matches_account_uuid(self) -> None:
        self.seed_cc("work@example.com", "uuid-work", "token-work")
        cc.add("work")
        live = cc.live_summary(self.kc)
        self.assertEqual(live["label"], "work")

    def test_remove(self) -> None:
        self.seed_cc("work@example.com", "uuid-work", "token-work")
        cc.add("work")
        cc.remove("work")
        self.assertEqual(cc.list_accounts(self.kc), [])
        self.assertIsNone(self.kc.get(cc.STORE_SERVICE, "work"))


class DesktopTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        (self.appdata / "Cookies").write_text("cookies-A")
        (self.appdata / "Cookies-journal").write_text("")
        (self.appdata / "Local Storage").mkdir()
        (self.appdata / "Local Storage" / "leveldb").write_text("storage-A")
        (self.appdata / "Partitions" / "p1").mkdir(parents=True)
        (self.appdata / "Partitions" / "p1" / "Cookies").write_text("p1-cookies-A")
        (self.appdata / "Cache").mkdir()
        (self.appdata / "Cache" / "cache.bin").write_text("cache")
        self.write_json(
            self.appdata / "config.json",
            {"lastKnownAccountUuid": "uuid-a", "userThemeMode": "dark"},
        )
        self.write_json(
            self.appdata / "claude_desktop_config.json",
            {"mcpServers": {"demo": {"command": "echo"}}},
        )
        self.write_json(self.appdata / "Preferences", {"spellcheck": True})

        self.is_running = mock.patch.object(desktop, "is_running", return_value=False)
        self.is_running.start()

    def tearDown(self) -> None:
        self.is_running.stop()
        super().tearDown()

    def switch_to_b(self) -> None:
        (self.appdata / "Cookies").write_text("cookies-B")
        (self.appdata / "Local Storage" / "leveldb").write_text("storage-B")
        (self.appdata / "Partitions" / "p1" / "Cookies").write_text("p1-cookies-B")
        self.write_json(
            self.appdata / "config.json",
            {"lastKnownAccountUuid": "uuid-b", "userThemeMode": "dark"},
        )

    def test_save_and_restore_auth_only(self) -> None:
        desktop.snapshot("a")
        self.switch_to_b()
        desktop.snapshot("b")

        desktop.restore("a")

        self.assertEqual((self.appdata / "Cookies").read_text(), "cookies-A")
        self.assertEqual(
            (self.appdata / "Local Storage" / "leveldb").read_text(), "storage-A"
        )
        self.assertEqual(
            (self.appdata / "Partitions" / "p1" / "Cookies").read_text(),
            "p1-cookies-B",
        )
        meta = json.loads(
            (desktop.profiles_dir() / "a" / "meta.json").read_text()
        )
        self.assertFalse(
            any(entry.startswith("Partitions/") for entry in meta["entries"])
        )
        cfg = json.loads((self.appdata / "config.json").read_text())
        self.assertEqual(cfg["lastKnownAccountUuid"], "uuid-a")
        self.assertEqual(cfg["userThemeMode"], "dark")
        self.assertTrue((self.appdata / "claude_desktop_config.json").exists())
        self.assertTrue((self.appdata / "Preferences").exists())
        self.assertTrue((self.appdata / "Cache" / "cache.bin").exists())
        self.assertEqual(desktop.current_label(), "a")

    def test_switch_removes_stale_auth_entries(self) -> None:
        desktop.snapshot("a")
        self.switch_to_b()
        desktop.snapshot("b")
        (self.appdata / "Cookies-wal").write_text("stale")
        desktop.restore("a")
        self.assertFalse((self.appdata / "Cookies-wal").exists())

    def test_clear_moves_auth_and_keeps_settings(self) -> None:
        backup = desktop.clear_live()
        self.assertFalse((self.appdata / "Cookies").exists())
        self.assertTrue((backup / "Cookies").exists())
        self.assertTrue((self.appdata / "claude_desktop_config.json").exists())
        self.assertTrue((self.appdata / "Preferences").exists())
        self.assertEqual(
            (self.appdata / "Partitions" / "p1" / "Cookies").read_text(),
            "p1-cookies-A",
        )

    def test_import_browser_restores_legacy_partition_data(self) -> None:
        desktop.snapshot("a")
        profile = desktop.profiles_dir() / "a" / "Partitions" / "p1"
        profile.mkdir(parents=True)
        (profile / "Cookies").write_text("legacy-browser-login")
        (self.appdata / "Partitions" / "p1" / "Cookies").write_text("live-cookies")

        result = desktop.import_browser("a")

        self.assertEqual(result["entries"], 1)
        self.assertEqual(
            (self.appdata / "Partitions" / "p1" / "Cookies").read_text(),
            "legacy-browser-login",
        )
        self.assertTrue((Path(result["backup"]) / "Partitions" / "p1" / "Cookies").exists())

    def test_duplicate_profile_requires_force(self) -> None:
        desktop.snapshot("a")
        with self.assertRaises(Exception):
            desktop.snapshot("a")
        desktop.snapshot("a", force=True)
        self.assertEqual(len(desktop.list_profiles()), 1)

    def test_switch_checkpoints_outgoing_browser_state(self) -> None:
        desktop.snapshot("a")
        self.switch_to_b()
        desktop.snapshot("b")

        (self.appdata / "Cookies").write_text("cookies-A-refreshed")
        (self.appdata / "IndexedDB").mkdir(exist_ok=True)
        (self.appdata / "IndexedDB" / "token").write_text("embedded-browser-login-A2")
        self.write_json(
            self.appdata / "config.json",
            {"lastKnownAccountUuid": "uuid-a", "userThemeMode": "dark"},
        )

        result = desktop.restore("b")
        self.assertEqual(result["checkpointed"], "a")

        desktop.restore("a")
        self.assertEqual((self.appdata / "Cookies").read_text(), "cookies-A-refreshed")
        self.assertEqual(
            (self.appdata / "IndexedDB" / "token").read_text(),
            "embedded-browser-login-A2",
        )

    def test_switch_auto_labels_unsaved_outgoing_state(self) -> None:
        desktop.snapshot("a")
        self.switch_to_b()
        desktop.snapshot("b")
        (self.appdata / "Cookies").write_text("cookies-C")
        self.write_json(self.appdata / "config.json", {"lastKnownAccountUuid": "uuid-c"})
        result = desktop.restore("b")
        self.assertEqual(result["checkpointed"], "auto-uuid-c")


class LabelTests(unittest.TestCase):
    def test_unicode_and_spaces_are_allowed(self) -> None:
        from claude_switch.util import validate_label

        for label in ("work", "HCM 2", "Công ty HCM", "team@example.com", "a_b+c-d"):
            validate_label(label)

    def test_unsafe_labels_are_rejected(self) -> None:
        from claude_switch.util import ToolError, validate_label

        for label in ("", ".", ".hidden", "a/b", "a\\b", " padded", "x\x00y"):
            with self.assertRaises(ToolError):
                validate_label(label)


class StatusTests(BaseCase):
    def test_status_shape(self) -> None:
        self.seed_cc("work@example.com", "uuid-work", "token-work")
        cc.add("work")
        (self.appdata / "Cookies").write_text("x")
        self.write_json(
            self.appdata / "config.json", {"lastKnownAccountUuid": "uuid-work"}
        )
        with mock.patch.object(desktop, "is_running", return_value=False):
            desktop.snapshot("work")
            data = status.build_status()
        self.assertEqual(data["claude_code"]["current_label"], "work")
        self.assertEqual(data["desktop"]["current_label"], "work")
        self.assertFalse(data["desktop"]["running"])
        self.assertEqual(len(data["claude_code"]["accounts"]), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_switch import desktop, sessions

A = "aaaaaaaa-1111-4111-8111-111111111111"
B = "bbbbbbbb-2222-4222-8222-222222222222"
ORG = "cccccccc-3333-4333-8333-333333333333"


class SessionSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.appdata = self.root / "Claude"
        self.state = self.root / ".claude-switch"
        self.cc_home = self.root / ".claude"
        os.environ["CLAUDE_SWITCH_HOME"] = str(self.state)
        os.environ["CLAUDE_SWITCH_CLAUDE_HOME"] = str(self.cc_home)
        os.environ["CLAUDE_SWITCH_CLAUDE_JSON"] = str(self.root / ".claude.json")
        os.environ["CLAUDE_SWITCH_CLAUDE_APPDATA"] = str(self.appdata)
        os.environ["CLAUDE_SWITCH_KEYCHAIN"] = "file"
        self.base = self.appdata / "claude-code-sessions"
        (self.base / A / ORG).mkdir(parents=True)
        (self.base / B / ORG).mkdir(parents=True)
        self.patch = mock.patch.object(desktop, "is_running", return_value=False)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        for key in (
            "CLAUDE_SWITCH_HOME",
            "CLAUDE_SWITCH_CLAUDE_HOME",
            "CLAUDE_SWITCH_CLAUDE_JSON",
            "CLAUDE_SWITCH_CLAUDE_APPDATA",
            "CLAUDE_SWITCH_KEYCHAIN",
        ):
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def write_session(self, account: str, sid: str, last: int, title: str) -> Path:
        path = self.base / account / ORG / ("local_%s.json" % sid)
        path.write_text(
            json.dumps(
                {
                    "sessionId": "local_%s" % sid,
                    "cliSessionId": "cli-%s" % sid,
                    "lastActivityAt": last,
                    "title": title,
                }
            )
        )
        os.utime(path, (last / 1000.0, last / 1000.0))
        return path

    def test_sync_copies_newest_and_respects_tombstones(self) -> None:
        old = 1700000000000
        new = 1700000100000
        self.write_session(A, "s1", old, "old title")
        self.write_session(B, "s1", new, "new title")
        self.write_session(B, "s2", 1700000050000, "only in b")
        self.write_session(B, "s3", 1700000060000, "deleted in a")
        (self.base / A / ORG / "deleted_s3").write_text("")

        result = sessions.sync()

        self.assertEqual(result["copies"], 2)
        a_s1 = json.loads((self.base / A / ORG / "local_s1.json").read_text())
        self.assertEqual(a_s1["title"], "new title")
        self.assertTrue((self.base / A / ORG / "local_s2.json").exists())
        self.assertFalse((self.base / A / ORG / "local_s3.json").exists())
        b_s1 = json.loads((self.base / B / ORG / "local_s1.json").read_text())
        self.assertEqual(b_s1["title"], "new title")

    def test_dry_run_writes_nothing(self) -> None:
        self.write_session(B, "s1", 1700000000000, "b")
        result = sessions.sync(dry_run=True)
        self.assertEqual(result["copies"], 1)
        self.assertFalse((self.base / A / ORG / "local_s1.json").exists())

    def test_sync_is_idempotent(self) -> None:
        self.write_session(B, "s1", 1700000000000, "b")
        first = sessions.sync()
        self.assertGreater(first["copies"], 0)
        second = sessions.sync()
        self.assertEqual(second["copies"], 0)

    def test_status_counts(self) -> None:
        self.write_session(A, "s1", 1700000000000, "a")
        self.write_session(B, "s1", 1700000000000, "b")
        self.write_session(B, "s2", 1700000000001, "b2")
        (self.base / B / ORG / "deleted_s9").write_text("")
        data = sessions.status()
        by_account = {
            row["account_uuid"]: row for row in data["claude_desktop_code_sessions"]
        }
        self.assertEqual(by_account[A]["sessions"], 1)
        self.assertEqual(by_account[B]["sessions"], 2)
        self.assertEqual(by_account[B]["deleted"], 1)


if __name__ == "__main__":
    unittest.main()

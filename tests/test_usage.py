from __future__ import annotations

import getpass
import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from claude_switch import cc, usage
from claude_switch.keychain import Keychain


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ["CLAUDE_SWITCH_HOME"] = str(self.root / ".claude-switch")
        os.environ["CLAUDE_SWITCH_CLAUDE_HOME"] = str(self.root / ".claude")
        os.environ["CLAUDE_SWITCH_CLAUDE_JSON"] = str(self.root / ".claude.json")
        os.environ["CLAUDE_SWITCH_CLAUDE_APPDATA"] = str(self.root / "Claude")
        os.environ["CLAUDE_SWITCH_KEYCHAIN"] = "file"

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

    def seed_credentials(self, expires_at: int) -> None:
        credentials = {
            "claudeAiOauth": {
                "accessToken": "token-test",
                "refreshToken": "refresh-test",
                "expiresAt": expires_at,
                "subscriptionType": "team",
            }
        }
        Keychain().set(cc.LIVE_SERVICE, getpass.getuser(), json.dumps(credentials))

    def test_parse_usage_converts_and_filters_expired(self) -> None:
        payload = {
            "five_hour": {"utilization": 0.234, "resets_at": 2000},
            "seven_day": {"utilization": 0.5, "resets_at": 500},
            "seven_day_opus": {"utilization": 1.25, "resets_at": 3000},
            "unknown": {"utilization": 0.9, "resets_at": 4000},
        }
        windows = usage.parse_usage(payload, now=1000)
        self.assertEqual([w["key"] for w in windows], ["five_hour", "seven_day_opus"])
        self.assertAlmostEqual(windows[0]["used_percent"], 23.4)
        self.assertAlmostEqual(windows[1]["used_percent"], 125.0)
        self.assertEqual(windows[0]["resets_at"], 2000)

    def test_no_credentials(self) -> None:
        data = usage.build_usage()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "no_credentials")

    def test_expired_token_skips_network(self) -> None:
        self.seed_credentials(expires_at=1000)
        with mock.patch.object(usage.urllib.request, "urlopen") as fetch:
            data = usage.build_usage()
        fetch.assert_not_called()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "token_expired")

    def test_successful_fetch(self) -> None:
        self.seed_credentials(expires_at=int(time.time() * 1000) + 600000)
        payload = {
            "five_hour": {"utilization": 0.42, "resets_at": int(time.time()) + 3600},
            "seven_day": {"utilization": 0.1, "resets_at": int(time.time()) + 86400},
        }
        with mock.patch.object(
            usage.urllib.request, "urlopen", return_value=FakeResponse(payload)
        ) as fetch:
            data = usage.build_usage()

        request = fetch.call_args[0][0]
        self.assertTrue(request.headers["Authorization"].startswith("Bearer "))
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["windows"]), 2)
        self.assertAlmostEqual(data["windows"][0]["used_percent"], 42.0)
        self.assertIn("5-hour", usage.format_usage(data))

    def test_unauthorized(self) -> None:
        self.seed_credentials(expires_at=int(time.time() * 1000) + 600000)
        error = urllib.error.HTTPError(usage.API_URL, 401, "Unauthorized", {}, None)
        with mock.patch.object(usage.urllib.request, "urlopen", side_effect=error):
            data = usage.build_usage()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "token_expired")


if __name__ == "__main__":
    unittest.main()

"""Offline NH quote contract: no credentials or live API calls are needed."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "nh_bridge", Path(__file__).resolve().parents[1] / "tools/nhplug_quote_bridge.py"
)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class NhQuoteBridgeTest(unittest.TestCase):
    def test_receipt_clock_runs_after_provider_response(self):
        events = []
        received = datetime(2026, 9, 30, 12, 1, tzinfo=UTC)

        def caller(*_):
            events.append("response")
            return {"Output_0": {"stck_prpr": "231000"}}

        def clock():
            events.append("received")
            return received

        result = bridge.collect("005930", caller, clock=clock)
        self.assertEqual(events, ["response", "received"])
        self.assertEqual(result["fetched_at"], int(received.timestamp()))

    def test_only_public_allowlisted_price_crosses_boundary(self):
        calls = []

        def caller(path, parameters):
            calls.append((path, parameters))
            return {
                "rsp_msg": "정상",
                "Output_0": {"stck_prpr": "231000", "account": "do-not-copy"},
                "access_token": "do-not-copy",
            }

        now = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
        result = bridge.collect("005930", caller, now)
        self.assertEqual(
            calls,
            [
                (
                    "/krstock/quote/v1/currentPrice",
                    {"iem_cd": "005930", "market_cd": "KRX"},
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "provider": "NHPLUG",
                "code": "005930",
                "market": "KRX",
                "currency": "KRW",
                "price": 231000,
                "fetched_at": int(now.timestamp()),
            },
        )

    def test_reject_invalid_code_before_call(self):
        for code in ("../key", "00593", "ABC123", "１２３４５６", "005930;rm", None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                bridge.collect(code, lambda *_: self.fail("provider called"))

    def test_invalid_or_missing_price_fails_closed(self):
        for value in (None, "", "0", "12.5", "1,000", -1, True, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.collect(
                    "005930", lambda *_: {"Output_0": {"stck_prpr": value}}
                )

    def test_naive_clock_is_rejected_before_call(self):
        with self.assertRaises(ValueError):
            bridge.collect(
                "005930", lambda *_: self.fail("provider called"), datetime(2026, 9, 30)
            )

    def test_process_file_contains_only_public_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nh.json"
            provider = SimpleNamespace(
                call=lambda *_: {
                    "Output_0": {"stck_prpr": "231000"},
                    "access_token": "do-not-copy",
                }
            )
            with patch.object(sys, "argv", ["bridge", "005930", str(output), "123-456-7"]):
                with patch.dict(sys.modules, {"nhplug": provider}):
                    with patch.dict(os.environ, {"PHALANX_NH_OFFLINE": "0"}):
                        self.assertEqual(bridge.main(), 0)
            raw = output.read_text(encoding="utf-8")
            envelope = json.loads(raw)
            self.assertTrue(envelope["ok"])
            self.assertEqual(envelope["payload"]["price"], 231000)
            self.assertNotIn("do-not-copy", raw)

    def test_auth_error_is_bounded_and_omits_provider_message(self):
        class AuthError(Exception):
            category = "auth"

        def fail(*_):
            raise AuthError("sensitive-provider-body")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nh.json"
            with patch.object(sys, "argv", ["bridge", "005930", str(output), "123-456-7"]):
                with patch.dict(sys.modules, {"nhplug": SimpleNamespace(call=fail)}):
                    with patch.dict(os.environ, {"PHALANX_NH_OFFLINE": "0"}):
                        self.assertEqual(bridge.main(), 1)
            raw = output.read_text(encoding="utf-8")
            self.assertEqual(json.loads(raw)["error"], "NH_CONFIG_MISSING")
            self.assertNotIn("sensitive-provider-body", raw)

    def test_offline_mode_never_calls_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nh.json"
            provider = SimpleNamespace(call=lambda *_: self.fail("provider called"))
            with patch.object(sys, "argv", ["bridge", "005930", str(output), "123-456-7"]):
                with patch.dict(sys.modules, {"nhplug": provider}):
                    with patch.dict(os.environ, {"PHALANX_NH_OFFLINE": "1"}):
                        self.assertEqual(bridge.main(), 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["error"], "NH_OFFLINE")


if __name__ == "__main__":
    unittest.main()

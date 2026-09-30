"""Offline contract tests for the WSL discovery catalog export."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


spec = importlib.util.spec_from_file_location(
    "market_catalog_bridge", Path(__file__).resolve().parents[1] / "tools/market_catalog_bridge.py"
)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

COLLECTED = datetime(2026, 9, 12, 14, 29, 5, tzinfo=timezone.utc)


def candidate(code, name, market="KOSPI", group="ST", preferred="0", etp=None,
              standard=None, reasons=(), status="excluded"):
    return NS(
        record=NS(short_code=code, standard_code=standard, name=name, market=market,
                  security_group=group, preferred_class=preferred, etp_class=etp),
        decision=NS(status=status, reasons=tuple(NS(code=value) for value in reasons)),
    )


def view(status="success", snapshot=True, snapshot_status="success"):
    markets = [NS(market=market, provider="kis-public-master", collection_completed_at=COLLECTED)
               for market in ("KOSPI", "KOSDAQ")]
    return NS(latest_attempt=NS(status=status), snapshot=(
        NS(markets=markets, status=snapshot_status, collection_completed_at=COLLECTED)
        if snapshot else None
    ))


class Service:
    def __init__(self, current, rows, refreshed=None):
        self.current = current
        self.rows = tuple(rows)
        self.refreshed = refreshed
        self.refresh_calls = 0
        self.status_filter = "unset"

    def view(self):
        return self.current

    def list_candidates(self, current, status=None):
        assert current is self.current
        self.status_filter = status
        return self.rows

    def refresh(self):
        self.refresh_calls += 1
        if isinstance(self.refreshed, Exception):
            raise self.refreshed
        return NS(status=self.refreshed or "success")


class BridgeTest(unittest.TestCase):
    def test_load_is_offline_and_includes_excluded_etf_and_preferred(self):
        service = Service(view(), [
            candidate("005930", "삼성전자", status="eligible"),
            candidate("069500", "KODEX 200", group="EF", etp="2"),
            candidate("005935", "삼성전자우", preferred="1"),
        ])
        result = bridge.execute("load", service)
        self.assertTrue(result["ok"])
        self.assertEqual(service.refresh_calls, 0)
        self.assertIsNone(service.status_filter)
        payload = result["payload"]
        self.assertEqual([item["kind"] for item in payload["items"]],
                         ["보통주", "ETF", "우선주"])
        self.assertTrue(all(item["registration_supported"] for item in payload["items"]))
        self.assertEqual(payload["collected_at"], COLLECTED.isoformat())
        self.assertTrue(all(item["source"] == "한국투자증권 공개 종목 마스터" for item in payload["items"]))

    def test_identifier_collisions_remain_visible_but_block_registration(self):
        rows = [
            candidate("111111", "동일 코드 A", standard="KR1111111111"),
            candidate("111111", "동일 코드 B", standard="KR2222222222"),
            candidate("222222", "표준 코드 A", standard="KR3333333333"),
            candidate("333333", "표준 코드 B", market="KOSDAQ", standard="KR3333333333"),
            candidate("444444", "원천 충돌", reasons=("RECORD_CONFLICT",)),
            candidate("555555", "정상", standard="KR5555555555"),
        ]
        items = bridge.export_catalog(view(), tuple(rows))["items"]
        self.assertEqual([item["collision"] for item in items],
                         [True, True, True, True, True, False])
        self.assertEqual([item["registration_supported"] for item in items],
                         [False, False, False, False, False, True])
        self.assertEqual([item["name"] for item in items[:2]], ["동일 코드 A", "동일 코드 B"])

    def test_unsupported_length_is_searchable_with_safe_reason(self):
        item = bridge.export_catalog(view(), (candidate("F70100030", "펀드", group="BC"),))["items"][0]
        self.assertEqual(item["code"], "F70100030")
        self.assertEqual(item["kind"], "기타 (BC)")
        self.assertFalse(item["registration_supported"])
        self.assertIn("6자리", item["reason"])

    def test_unconfirmed_security_kind_and_name_limit_are_not_misrepresented(self):
        rows = (
            candidate("03473K", "SK우", preferred="9", status="unknown"),
            candidate("123456", "분류 충돌", group="ST", etp="2",
                      reasons=("CLASSIFICATION_CONFLICT",), status="unknown"),
            candidate("654321", "긴" * 81),
        )
        items = bridge.export_catalog(view(), rows)["items"]
        self.assertEqual(items[0]["kind"], "주식 (우선주 분류 9 미확인)")
        self.assertEqual(items[1]["kind"], "종류 분류 충돌")
        self.assertFalse(items[2]["registration_supported"])
        self.assertIn("저장 한도", items[2]["reason"])

    def test_empty_and_failed_refresh_are_distinct(self):
        empty = bridge.execute("load", Service(view(snapshot=False), []))
        self.assertTrue(empty["ok"])
        self.assertEqual(empty["payload"]["state"], "empty")
        service = Service(view(status="failed"), [candidate("005930", "삼성전자")],
                          refreshed=RuntimeError("do not expose provider details"))
        failed = bridge.execute("refresh", service)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"], "REFRESH_FAILED")
        self.assertEqual(failed["payload"]["items"][0]["name"], "삼성전자")
        self.assertEqual(failed["payload"]["collected_at"], COLLECTED.isoformat())
        self.assertEqual(service.refresh_calls, 1)
        first_failure = bridge.execute("load", Service(view(status="failed", snapshot=False), []))
        self.assertFalse(first_failure["ok"])
        self.assertEqual(first_failure["payload"]["state"], "empty")
        partial = bridge.execute("load", Service(view(status="partial", snapshot_status="partial"),
                                                 [candidate("005930", "부분 목록")]))
        self.assertFalse(partial["ok"])
        self.assertEqual(partial["payload"]["state"], "empty")
        self.assertEqual(partial["payload"]["snapshot_status"], "partial")
        old = Service(view(status="partial"), [candidate("005930", "이전 정상 목록")],
                      refreshed="partial")
        partial_after_success = bridge.execute("refresh", old)
        self.assertFalse(partial_after_success["ok"])
        self.assertEqual(partial_after_success["payload"]["state"], "ready")
        self.assertEqual(partial_after_success["payload"]["items"][0]["name"],
                         "이전 정상 목록")


if __name__ == "__main__":
    unittest.main()

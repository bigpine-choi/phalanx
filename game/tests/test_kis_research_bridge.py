"""Offline tests: import no credentials, exercise the bridge's public boundary."""
import importlib.util
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import unittest

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).resolve().parents[1]/'tools/kis_research_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Reader:
    def fetch_daily_bars(self, code, start, end):
        self.request = (code, start, end)
        return tuple(SimpleNamespace(stock_code=code, trade_date=date(2026, 9, day),
                     open_price=Decimal('100'), high_price=Decimal('110'), low_price=Decimal('90'),
                     close_price=Decimal('105'), volume=1000000) for day in [24,25])


class BridgeTest(unittest.TestCase):
    def test_basis_dates_and_serialization(self):
        reader = Reader()
        data = bridge.collect('005930', reader, datetime(2026,9,29,1,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(reader.request, ('005930', date(2025,9,28), date(2026,9,28)))
        self.assertEqual((data['provider'], data['market'], data['adjusted']), ('KIS','KRX',True))
        self.assertEqual(data['candles'][0]['volume'], 1000000)
        self.assertEqual(data['candles'][0]['close'], 105)
        self.assertEqual(set(data), {'provider','market','adjusted','code','currency','fetched_at','requested_start','requested_end','candles'})

    def test_dynamic_security_and_fixed_clock(self):
        now = datetime(2026,9,29,1,tzinfo=ZoneInfo('Asia/Seoul'))
        data = bridge.collect('123459', Reader(), now)
        self.assertEqual(data['code'], '123459')
        self.assertEqual(data['fetched_at'], int(now.timestamp()))
        for code in ['../keys', '12345', '１２３４５６', '005930;echo', '', None]:
            with self.subTest(code=code), self.assertRaises(ValueError):
                bridge.collect(code, object(), now)

    def test_allowlist_precedes_provider(self):
        with self.assertRaises(ValueError):
            bridge.collect('../credentials', object())

    def test_empty_is_not_synthesized(self):
        with self.assertRaises(ValueError):
            bridge.collect('005930', SimpleNamespace(fetch_daily_bars=lambda *args: ()))

    def test_wrong_stock_rejected(self):
        reader = Reader()
        rows = list(reader.fetch_daily_bars('000660',None,None))
        with self.assertRaises(ValueError):
            bridge.collect('005930', SimpleNamespace(fetch_daily_bars=lambda *args: rows))


if __name__ == '__main__':
    unittest.main()

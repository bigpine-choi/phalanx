"""Offline contract tests. Temporary encrypted dummy key only; never calls OpenAI."""
import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import httpx
from advisor_engine import build_report, CODES
import advisor_openai as api

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
KEY = "sk-test-never-a-real-key-1234567890"


def context(count=61):
    bars = []
    for i in range(count):
        price = 100 + i
        bars.append(dict(date=(NOW.date()-timedelta(days=count-i)).isoformat(), open=price, high=price+2, low=price-2, close=price, volume=1000))
    return dict(code="005930", mode="brief", note="검증할 투자 가설", draft={},
                quote=dict(code="005930", currency="KRW", candles=bars, fetched_at=NOW.timestamp(), as_of=bars[-1]["date"]),
                financials=dict(code="005930",currency="KRW",source="unit test",rows=[
                    dict(year=2024,revenue=100,operating_profit=10),dict(year=2025,revenue=120,operating_profit=18)]))


def answer(refs=None):
    item = dict(title="해석",text="연간 실적을 분기 자료와 함께 확인하세요.",source_ids=refs or ["F2025"])
    return dict(status="completed",output=[dict(type="message",content=[dict(type="output_text",text=json.dumps(dict(items=[item])) )])])


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phalanx-advisor-test-")
        self.path = Path(self.temp.name)/"config.json"
        self.env = patch.dict(os.environ, {"PHALANX_ADVISOR_CONFIG":str(self.path),"OPENAI_API_KEY":"","PHALANX_ADVISOR_OFFLINE":""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_existing_calculator_exact_return(self):
        report = build_report(context(), NOW)
        metrics = report["price_features"]["symbols"][0]["metrics"]
        value = next(x["value"] for x in metrics if x["name"]=="price_return" and x["intervals"]==60)
        self.assertEqual(Decimal(value), Decimal("0.6"))
        dd = next(x["value"] for x in metrics if x["name"]=="maximum_drawdown" and x["intervals"]==60)
        self.assertEqual(Decimal(dd),0)
        self.assertEqual(report["analysis"], [])
        self.assertTrue(any(x["text"].startswith("15.00%") for x in report["facts"]))
        self.assertEqual(report["price_features"]["discovery_run_id"],"godot_snapshot_no_discovery")

    def test_missing_is_not_zero(self):
        report = build_report(context(2), NOW)
        self.assertTrue(any("60관측" in x for x in report["missing"]))
        self.assertFalse(any("60관측" in x["title"] for x in report["facts"]))

    def test_reject_invalid_market_data(self):
        cases = []
        c=context();c["quote"]["code"]="000660";cases.append(c)
        c=context();c["quote"]["candles"][-1]["volume"]=0.5;cases.append(c)
        c=context();c["quote"]["candles"][-1]["close"]=float("nan");cases.append(c)
        c=context();c["quote"]["candles"][-1]["date"]="2026-10-01";c["quote"]["as_of"]="2026-10-01";cases.append(c)
        c=context();c["quote"]["candles"][-1]["date"]=c["quote"]["candles"][-2]["date"];cases.append(c)
        c=context();c["financials"]["code"]="000660";cases.append(c)
        for bad in cases:
            with self.subTest(bad=cases.index(bad)), self.assertRaises(ValueError):
                build_report(bad,NOW)

    def test_review_keeps_synthetic_provenance(self):
        c=context();c["mode"]="review";c["plan"]={"source":"가상 계좌 · 샘플 시세", "rows":[dict(code=k,target=10) for k in CODES]}
        report=build_report(c,NOW)
        self.assertTrue(any("실계좌 아님" in s["detail"] for s in report["sources"]))
        self.assertTrue(any("20.0%" in f["text"] for f in report["facts"] if "반도체" in f["title"]))

    def test_key_dpapi_and_preserve_on_blank(self):
        self.assertFalse(api.status()["configured"])
        api.configure(dict(key=KEY,model=api.DEFAULT_MODEL))
        self.assertNotIn(KEY,self.path.read_text())
        self.assertEqual(api.credentials()[1],KEY)
        api.configure(dict(key="",model="gpt-5.4-mini"))
        self.assertEqual(api.credentials()[1],KEY)
        self.assertNotIn("key",api.status())

    def test_no_key_is_explicit(self):
        with self.assertRaisesRegex(api.AdvisorError,"KEY_MISSING"):
            api.request_analysis(build_report(context(),NOW),"brief")

    def test_request_and_response_contract(self):
        api.configure(dict(key=KEY))
        report=build_report(context(),NOW)
        def handler(request):
            self.assertEqual(str(request.url),api.ENDPOINT)
            body=json.loads(request.content)
            self.assertIs(body["store"],False)
            self.assertIs(body["text"]["format"]["strict"],True)
            self.assertNotIn(KEY,request.content.decode())
            data=json.loads(body["input"])
            self.assertNotIn("quote",data)
            self.assertIn("sources",data)
            return httpx.Response(200,json=answer())
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result=api.request_analysis(report,"brief",client=client)
        self.assertEqual(result["items"][0]["source_ids"],["F2025"])

    def test_provider_errors_and_citations(self):
        api.configure(dict(key=KEY))
        report=build_report(context(),NOW)
        for status,payload,error in [(401,{},"AUTH_FAILED"),(429,{},"LIMIT_REACHED"),(500,{},"API_FAILED"),
                                     (200,answer(["FAKE"]),"CITATION_INVALID"),(200,{"status":"incomplete"},"RESPONSE_INCOMPLETE"),
                                     (200,{"status":"completed","output":[{"type":"message","content":[{"type":"refusal"}]}]},"REFUSED")]:
            with self.subTest(error=error),httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=payload))) as client:
                with self.assertRaisesRegex(api.AdvisorError,error):
                    api.request_analysis(report,"brief",client=client)

    def test_timeout_and_offline(self):
        api.configure(dict(key=KEY))
        def timeout(request):
            raise httpx.ReadTimeout("sensitive exception must not escape")
        with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
            with self.assertRaisesRegex(api.AdvisorError,"^TIMEOUT$"):
                api.request_analysis(build_report(context(),NOW),"brief",client=client)
        with patch.dict(os.environ,{"PHALANX_ADVISOR_OFFLINE":"1"}):
            with self.assertRaisesRegex(api.AdvisorError,"OFFLINE"):
                api.request_analysis(build_report(context(),NOW),"brief")

    def test_bridge_no_key_keeps_facts_and_no_logging(self):
        request=Path(self.temp.name)/"request.json";output=Path(self.temp.name)/"out.json"
        c=context();c["quote"]["fetched_at"]=datetime.now(UTC).timestamp()
        # Use no quote so this subprocess test remains stable on any run date.
        c["quote"]={}
        request.write_text(json.dumps(c),encoding="utf-8")
        bridge=Path(api.__file__).with_name("advisor_bridge.py")
        p=subprocess.run([sys.executable,str(bridge),"analyze",str(request),str(output),"test-1"],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0)
        self.assertEqual(p.stdout+p.stderr,b"")
        result=json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["payload"]["ai_state"],"KEY_MISSING")
        self.assertTrue(result["payload"]["facts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

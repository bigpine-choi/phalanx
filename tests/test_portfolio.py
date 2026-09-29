import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from portfolio_engine import PlanError, simulate, review_report


def fixture():
    return {"account":{"source":"kis_account","currency":"KRW","snapshot_id":"a"*64,
        "observed_at":"2026-09-29T12:00:00+00:00","account_masked":"0000****-**",
        "summary":{"deposit_total":"99999999"},
        "rows":[{"code":"005930","name":"삼성전자","quantity":"10","sellable":"10","price":"100","value":"1000"},
                {"code":"000660","name":"SK하이닉스","quantity":"5","sellable":"5","price":"200","value":"1000"}]},
        "cash_assumption":"1000","targets":{"005930":50,"000660":25}}


class PortfolioTests(unittest.TestCase):
    def test_existing_engine_and_rounding(self):
        c=fixture()
        r=simulate(c)
        self.assertIn("apply_fractional_self_financing_transition",r["engine"])
        self.assertEqual([x["result_quantity"] for x in r["plan"]["rows"]],[15,3])
        self.assertEqual(r["buy_total"],500)
        self.assertEqual(r["sell_total"],400)
        self.assertEqual(r["plan"]["planned_cash"],900)
        self.assertEqual(r["plan"]["base_assets"],3000)
        self.assertEqual(c,fixture())

    def test_deposit_is_not_orderable_cash(self):
        c=fixture(); c["cash_assumption"]="0"
        r=simulate(c)
        self.assertEqual(r["plan"]["base_assets"],2000)
        self.assertEqual(r["plan"]["base_cash"],0)

    def test_overallocation_and_sellable(self):
        c=fixture(); c["targets"]["005930"]=80
        with self.assertRaisesRegex(PlanError,"OVER_ALLOCATED"): simulate(c)
        c=fixture(); c["account"]["rows"][1]["sellable"]="1"
        with self.assertRaisesRegex(PlanError,"SELLABLE_EXCEEDED"): simulate(c)

    def test_invalid_and_mismatched_inputs(self):
        for value in ["NaN","Infinity",-1,True]:
            c=fixture(); c["cash_assumption"]=value
            with self.assertRaises(PlanError): simulate(c)
        c=fixture(); c["targets"]["unknown"]=0
        with self.assertRaises(PlanError): simulate(c)
        c=fixture(); c["account"]["rows"][0]["quantity"]="1.5"
        with self.assertRaisesRegex(PlanError,"QUANTITY_INVALID"): simulate(c)

    def test_zero_and_full_equity_reconcile(self):
        for targets in [{"005930":0,"000660":0},{"005930":33.33,"000660":66.67},{"005930":100,"000660":0}]:
            c=fixture(); c["targets"]=targets
            plan=simulate(c)["plan"]
            self.assertGreaterEqual(plan["planned_cash"],0)
            self.assertEqual(plan["base_assets"],sum(x["result_quantity"]*x["price"] for x in plan["rows"])+plan["planned_cash"])

    def test_current_weights_do_not_trade_due_to_display_rounding(self):
        c=fixture(); c["targets"]={"005930":33.33,"000660":33.33}; c["keep_holdings"]=True
        r=simulate(c)
        self.assertEqual([x["delta"] for x in r["plan"]["rows"]],[0,0])
        self.assertEqual(r["plan"]["planned_cash"],1000)
        c["targets"]["005930"]=40
        with self.assertRaises(PlanError): simulate(c)

    def test_review_minimizes_private_data(self):
        r=review_report(simulate(fixture()))
        text=json.dumps(r,ensure_ascii=False)
        for forbidden in ["account_masked","quantity","price","base_assets","99999999","0000****","snapshot_id"]:
            self.assertNotIn(forbidden,text)
        self.assertIn("005930",text)
        self.assertIn("%",text)

    def test_recurring_current_weights_with_many_holdings(self):
        from decimal import Decimal, ROUND_FLOOR
        for count in (3, 11, 100):
            for cash in (0, 123456):
                rows=[dict(code=str(i),name="fixture",price=str(100+i*37),quantity=str(i+1),sellable=str(i+1)) for i in range(count)]
                nav=sum(Decimal(r["price"])*Decimal(r["quantity"]) for r in rows)+cash
                targets={r["code"]:str((Decimal(r["price"])*Decimal(r["quantity"])/nav*100).quantize(Decimal("0.01"),rounding=ROUND_FLOOR)) for r in rows}
                r=simulate(dict(account=dict(source="demo",currency="KRW",rows=rows),cash_assumption=str(cash),keep_holdings=True,targets=targets))
                self.assertTrue(all(x["delta"]==0 for x in r["plan"]["rows"]))
                self.assertEqual(r["plan"]["planned_cash"],cash)

    def test_fingerprint_tracks_scenario_and_snapshot(self):
        a=fixture(); b=copy.deepcopy(a); b["cash_assumption"]="2000"
        self.assertNotEqual(simulate(a)["input_hash"],simulate(b)["input_hash"])
        self.assertEqual(simulate(a),simulate(a))

    def test_empty_account(self):
        c=fixture(); c["account"]["rows"]=[]; c["targets"]={}
        with self.assertRaisesRegex(PlanError,"NO_HOLDINGS"): simulate(c)

    def test_native_bridge_no_api_and_no_stdout(self):
        import os, subprocess, tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory); (path/"in.json").write_text(json.dumps(fixture()),encoding="utf-8")
            r=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"tools/portfolio_bridge.py"),"simulate",str(path/"in.json"),str(path/"out.json"),"probe"],capture_output=True,text=True)
            self.assertEqual(r.returncode,0); self.assertEqual(r.stdout,""); self.assertEqual(r.stderr,"")
            data=json.loads((path/"out.json").read_text(encoding="utf-8"))
            self.assertTrue(data["ok"]); self.assertEqual(data["request_id"],"probe")

    def test_account_bridge_cancelled_request_does_not_leave_balance(self):
        import types, tempfile
        import account_bridge
        service=types.ModuleType("phalanx.account_overview_application")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); output=root/"result.json"; marker=root/"request.input.json"
            marker.write_text("probe")
            def query():
                marker.unlink()
                return types.SimpleNamespace(overview=object())
            service.run_production_account_overview=query
            with patch.dict(sys.modules,{"phalanx.account_overview_application":service}), patch.object(sys,"argv",["account_bridge",str(output),"probe",str(marker)]), patch.object(account_bridge,"present",return_value={"private_balance":"fixture"}), patch.dict("os.environ",{"PHALANX_ACCOUNT_OFFLINE":"0"}):
                self.assertEqual(account_bridge.main(),0)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".pending").exists())


if __name__=="__main__": unittest.main()

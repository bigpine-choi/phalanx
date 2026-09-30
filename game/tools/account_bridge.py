"""Read-only KIS overview adapter. Run in the existing WSL environment."""
import hashlib
import json
import os
from pathlib import Path
import sys


def present(overview):
    snapshot = overview.snapshot
    holdings = {p.stock_code: p for p in snapshot.positions}
    def amount(value):
        return format(value, "f")
    return {
        "version": 1, "source": "kis_account", "currency": "KRW",
        "snapshot_id": hashlib.sha256(overview.model_dump_json().encode()).hexdigest(),
        "account_masked": snapshot.account_number_masked,
        "observed_at": overview.observation_completed_at.isoformat(),
        "observed_start": overview.observation_started_at.isoformat(),
        "summary": {key: amount(getattr(snapshot.summary, key)) for key in (
            "net_assets", "deposit_total", "securities_evaluation_amount", "profit_loss_total")},
        "orderable_cash": None,
        "positions_value": amount(overview.totals.observed_positions_evaluation_amount),
        "valuation_difference": amount(overview.totals.observed_minus_broker_positions),
        "rows": [{"code": p.stock_code, "name": p.product_name,
                  "quantity": amount(p.holding_quantity), "sellable": amount(p.sellable_quantity),
                  "price": amount(p.observed_price), "value": amount(p.observed_evaluation_amount),
                  "broker_value": amount(p.broker_evaluation_amount),
                  "profit_loss": amount(holdings[p.stock_code].profit_loss),
                  "stock_weight": amount(p.observed_stock_weight * 100),
                  "price_observed_at": p.price_received_at.isoformat()} for p in overview.positions],
        "warnings": list(snapshot.evidence.summary_consistency_warnings),
    }


def main():
    if len(sys.argv) != 4:
        return 2
    output, request_id, marker = sys.argv[1:]
    result = {"request_id": request_id, "ok": False}
    try:
        from phalanx.account_overview_application import run_production_account_overview
        if os.environ.get("PHALANX_ACCOUNT_OFFLINE") == "1":
            result["error"] = "OFFLINE"
        else:
            result.update(ok=True, payload=present(run_production_account_overview().overview))
    except Exception as error:
        # Class names only; never serialize provider bodies or credentials.
        category = type(error).__name__
        result["error"] = "ACCOUNT_CONFIG" if category == "ConfigError" else (
            "ACCOUNT_AUTH" if "Auth" in category else "ACCOUNT_QUERY_FAILED")
    path = Path(output)
    pending = path.with_suffix(".pending")
    try:
        if not Path(marker).exists():
            return 0
        pending.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(pending, path)
        if not Path(marker).exists():
            path.unlink(missing_ok=True)
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

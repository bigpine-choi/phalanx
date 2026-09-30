"""Native Python simulation and optional OpenAI review; no broker API."""
import json
import os
from pathlib import Path
import sys
from portfolio_engine import PlanError, simulate, review_report
from advisor_openai import AdvisorError, request_analysis


def main():
    if len(sys.argv) != 5:
        return 2
    action, input_path, output_path, request_id = sys.argv[1:]
    result = {"request_id":request_id,"ok":False}
    try:
        path = Path(input_path)
        if action not in {"simulate","portfolio_review"} or path.stat().st_size > 512*1024:
            raise PlanError("INPUT_INVALID")
        payload = simulate(json.loads(path.read_text(encoding="utf-8")))
        if action == "portfolio_review":
            try:
                ai = request_analysis(review_report(payload),"review")
                payload.update(analysis=ai["items"], model=ai["model"], ai_state="ready")
            except AdvisorError as error:
                payload["ai_state"] = str(error)
        result.update(ok=True,payload=payload)
    except PlanError as error:
        result["error"] = str(error)
    except Exception:
        result["error"] = "SIMULATION_FAILED"
    try:
        path = Path(output_path)
        pending = path.with_suffix(".pending")
        pending.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding="utf-8")
        os.replace(pending,path)
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

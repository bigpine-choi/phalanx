"""Bounded one-shot JSON bridge, no shell, server or account access."""
import json
import os
from pathlib import Path
import sys

from advisor_openai import AdvisorError, configure, request_analysis, status


def main():
    if len(sys.argv) != 5:
        return 2
    action, input_path, output_path, request_id = sys.argv[1:]
    result = {"request_id": request_id, "ok": False}
    try:
        if action == "configure":
            raw = sys.stdin.buffer.readline(4097)
            if len(raw) > 4096:
                raise AdvisorError("CONFIG_INVALID")
            result.update(ok=True, payload=configure(json.loads(raw.decode("utf-8"))))
        elif action == "status":
            result.update(ok=True, payload=status())
        elif action in {"analyze", "facts"}:
            from advisor_engine import build_report
            path = Path(input_path)
            if path.stat().st_size > 512 * 1024:
                raise AdvisorError("INPUT_INVALID")
            context = json.loads(path.read_text(encoding="utf-8"))
            report = build_report(context)
            if action == "analyze":
                try:
                    ai = request_analysis(report, context["mode"])
                    report.update(analysis=ai["items"], model=ai["model"], ai_state="ready")
                except AdvisorError as exc:
                    report.update(ai_state=str(exc), analysis=[])
            result.update(ok=True, payload=report)
        else:
            raise AdvisorError("ACTION_INVALID")
    except AdvisorError as exc:
        result["error"] = str(exc)
    except Exception:
        result["error"] = "REQUEST_FAILED"
    # No request body, key, raw provider response, or exception details are logged.
    try:
        path = Path(output_path)
        temporary = path.with_suffix(".pending")
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

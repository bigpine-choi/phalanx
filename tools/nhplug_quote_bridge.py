"""Read-only NHPLUG quote boundary for the Godot research screen.

The official SDK reads credentials from ~/.nhplug/.env (or NHPLUG_ENV_FILE).
Only an allowlisted public price leaves this WSL process; no key, token,
account response, or provider exception is serialized.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


def valid_code(code: object) -> bool:
    return isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code) is not None


def _positive_price(value: object) -> int:
    if type(value) is int:
        price = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
        price = int(value)
    else:
        raise ValueError("missing or invalid NH price")
    if not 0 < price <= 1_000_000_000_000:
        raise ValueError("NH price out of range")
    return price


def collect(
    code: str,
    caller: Callable[[str, dict[str, str]], object],
    now: datetime | None = None,
) -> dict[str, object]:
    if not valid_code(code):
        raise ValueError("unsupported security")
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("timezone-aware observation required")
    response = caller(
        "/krstock/quote/v1/currentPrice", {"iem_cd": code, "market_cd": "KRX"}
    )
    if not isinstance(response, dict):
        raise ValueError("invalid NH response")
    output = response.get("Output_0")
    if not isinstance(output, dict):
        raise ValueError("NH quote missing")
    return {
        "provider": "NHPLUG",
        "code": code,
        "market": "KRX",
        "currency": "KRW",
        "price": _positive_price(output.get("stck_prpr")),
        "fetched_at": int(observed.timestamp()),
    }


def main() -> int:
    if len(sys.argv) != 4 or not valid_code(sys.argv[1]):
        return 2
    code, output, request_id = sys.argv[1:]
    if re.fullmatch(r"[0-9-]{3,64}", request_id) is None:
        return 2
    try:
        from nhplug import call

        result: dict[str, object] = {"ok": True, "payload": collect(code, call)}
    except ImportError:
        result = {"ok": False, "error": "NH_SDK_MISSING"}
    except Exception as error:
        category = getattr(error, "category", "")
        result = {
            "ok": False,
            "error": "NH_CONFIG_MISSING"
            if category in ("auth", "config")
            else "NH_READ_FAILED",
        }
    result.update({"request_id": request_id, "code": code})
    destination = Path(output)
    temporary = destination.with_suffix(destination.suffix + ".pending")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        os.replace(temporary, destination)
    except OSError:
        return 3
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

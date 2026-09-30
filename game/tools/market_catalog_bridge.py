"""Export the persisted Linux discovery master for the Godot market search.

`load` never downloads. `refresh` is the sole network-capable action. This
script is launched with the existing WSL Python environment, because the
discovery repository enforces POSIX ownership and file permissions.
"""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys


_SIX_CHARACTER_CODE = re.compile(r"[0-9A-Z]{6}\Z")
_IDENTIFIER_CONFLICTS = frozenset({"DUPLICATE_RECORD", "RECORD_CONFLICT"})


def _value(value: object) -> str:
    """Convert StrEnum fields without relying on their presentation string."""
    return str(getattr(value, "value", value) or "")


def _source_name(provider: object) -> str:
    name = _value(provider)
    return "한국투자증권 공개 종목 마스터" if name == "kis-public-master" else name


def _kind(record: object, decision: object) -> str:
    group = _value(record.security_group)
    etp = _value(record.etp_class)
    if any(_value(reason.code) == "CLASSIFICATION_CONFLICT" for reason in decision.reasons):
        return "종류 분류 충돌"
    if group == "EF" or etp == "2":
        return "ETF"
    if group == "EN" or etp == "3":
        return "ETN"
    if _value(record.preferred_class) in {"1", "2"}:
        return "우선주"
    if group == "ST":
        preferred = _value(record.preferred_class)
        return "보통주" if preferred == "0" else f"주식 (우선주 분류 {preferred or '누락'} 미확인)"
    return "기타 (" + group + ")" if group else "기타"


def _empty_payload(attempt_status: str = "") -> dict:
    return {
        "state": "empty",
        "source": "",
        "collected_at": "",
        "snapshot_status": "",
        "latest_attempt_status": attempt_status,
        "items": [],
        "collisions": [],
    }


def export_catalog(view: object, candidates: tuple) -> dict:
    """Search exposure is independent from candidate investment eligibility.

    Keep collision rows visible for investigation, but make every row whose
    short or standard identifier collides impossible to register. Never merge
    records just because their display names or identifiers look alike.
    """
    attempt = getattr(view, "latest_attempt", None)
    attempt_status = _value(attempt.status) if attempt is not None else ""
    snapshot = getattr(view, "snapshot", None)
    if snapshot is None:
        return _empty_payload(attempt_status)
    if _value(snapshot.status) != "success":
        # The repository exposes a partial run when no successful run exists.
        # It is not a normal catalog and must not become the game's good cache.
        payload = _empty_payload(attempt_status)
        payload["snapshot_status"] = _value(snapshot.status)
        return payload

    by_market = {_value(market.market): market for market in snapshot.markets}
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        record = candidate.record
        for field in ("short_code", "standard_code"):
            identifier = _value(getattr(record, field))
            if identifier:
                groups[(field, identifier)].append(index)
    collisions = {index for indices in groups.values() if len(indices) > 1 for index in indices}
    for index, candidate in enumerate(candidates):
        if any(_value(reason.code) in _IDENTIFIER_CONFLICTS for reason in candidate.decision.reasons):
            collisions.add(index)

    items = []
    for index, candidate in enumerate(candidates):
        record = candidate.record
        code = _value(record.short_code)
        name = _value(record.name)
        market = _value(record.market)
        market_snapshot = by_market[market]
        collision = index in collisions
        valid_code = _SIX_CHARACTER_CODE.fullmatch(code) is not None
        if collision:
            reason = "식별자 중복 또는 충돌로 관심종목에 추가할 수 없습니다."
        elif not valid_code:
            reason = "현재 게임은 6자리 종목코드만 관심종목에 등록할 수 있습니다."
        elif not name:
            reason = "종목명이 없어 관심종목에 추가할 수 없습니다."
        elif len(name) > 80:
            reason = "종목명이 기존 저장 한도를 넘어서 관심종목에 추가할 수 없습니다."
        else:
            reason = ""
        items.append(
            {
                "code": code,
                "name": name,
                "market": market,
                "kind": _kind(record, candidate.decision),
                "source": _source_name(market_snapshot.provider),
                "collected_at": market_snapshot.collection_completed_at.isoformat(),
                "collision": collision,
                "registration_supported": not reason,
                "reason": reason,
                "eligibility": _value(candidate.decision.status),
            }
        )

    return {
        "state": "ready",
        "source": ", ".join(sorted({_source_name(m.provider) for m in snapshot.markets})),
        "collected_at": snapshot.collection_completed_at.isoformat(),
        "snapshot_status": _value(snapshot.status),
        "latest_attempt_status": attempt_status,
        "items": items,
        "collisions": [
            {"code": code, "reason": "식별자 중복 또는 충돌"}
            for code in sorted({items[index]["code"] for index in collisions})
        ],
    }


def execute(action: str, service: object) -> dict:
    """Return an envelope while preserving the repository's last good view."""
    if action not in {"load", "refresh"}:
        return {"ok": False, "error": "ACTION_INVALID", "payload": _empty_payload()}

    refresh_failed = False
    if action == "refresh":
        try:
            refresh_failed = _value(service.refresh().status) != "success"
        except Exception:
            refresh_failed = True
    try:
        view = service.view()
        payload = export_catalog(view, service.list_candidates(view, status=None))
    except Exception:
        return {"ok": False, "error": "STORE_READ_FAILED", "payload": _empty_payload()}

    attempt = getattr(view, "latest_attempt", None)
    degraded = attempt is not None and _value(attempt.status) != "success"
    if refresh_failed or degraded:
        return {"ok": False, "error": "REFRESH_FAILED", "payload": payload}
    return {"ok": True, "payload": payload}


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    action, output_path, request_id = sys.argv[1:]
    if action not in {"load", "refresh"} or not request_id or len(request_id) > 128:
        return 2
    try:
        from phalanx.discovery.application import build_service

        result = execute(action, build_service())
    except Exception:
        result = {"ok": False, "error": "BRIDGE_FAILED", "payload": _empty_payload()}
    result["request_id"] = request_id
    destination = Path(output_path)
    temporary = destination.with_suffix(".pending")
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temporary, destination)
    except Exception:
        return 3
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

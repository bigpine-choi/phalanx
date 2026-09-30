"""Validate the displayed projection of a saved v1 result, without model execution.

This checks representation and relationships consumed by the view. It does not
recompute hashes, covariances, PSD/KKT evidence, or authenticate the source file.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction
from itertools import pairwise
from typing import cast

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.allocation_targets import ALLOCATION_TARGETS_SCHEMA, ALLOCATION_TARGETS_VERSION
from phalanx.domain.risk_model import SCENARIO_KIND_ORDER
from phalanx.portfolio.formation_room.errors import FormationRoomInputError
from phalanx.portfolio.formation_room.model import FormationRoomModel, FormationRoomPresentation
from phalanx.portfolio.formation_room.selection import linked_names

MAX_TARGETS_BYTES = 32 * 1024 * 1024
_SCOPE = "selected_universe_single_date_risky_asset_allocation"
_LABELS = ("장기 균형", "빠른 적응", "느린 적응", "하방 스트레스")
_STATUS_LABELS = {
    "input_unavailable": "입력 준비 불가",
    "common_failure": "공통 계산 실패",
    "succeeded": "네 시나리오 산출 완료",
    "partial": "일부 시나리오 산출",
    "failed": "모든 시나리오 계산 실패",
}
_BOUND_LABELS = {"free": "범위 내", "upper": "상한 적용", "lower": "하한 적용"}
_LIMITATIONS = [
    "위험자산 내부 연구용 배분입니다. 실제 계좌 실행 목표나 검증된 추천 포트폴리오가 아닙니다.",
    "저장된 결과를 조회하는 오프라인 화면 시제품입니다. 실시간 분석이나 재계산을 하지 않습니다.",
    "네 시나리오는 독립 결과이며 평균·혼합·자동 추천을 하지 않습니다.",
    "기존 위험모형은 숫자 6자리 종목코드만 지원합니다.",
    "공식 거래일 무누락은 미검증이며 point-in-time 백테스트를 보장하지 않습니다.",
    "배당을 제외한 수정종가 가격수익률입니다.",
    "features 소비 입력 해시는 재검증하지 않았습니다.",
    "입력 SHA-256은 파일 식별용입니다. 진위 인증이나 전체 모형 재검증을 뜻하지 않습니다.",
]


def _require(condition: bool) -> None:
    if not condition:
        raise FormationRoomInputError()


def _object(value: object) -> dict[str, object]:
    _require(type(value) is dict)
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    _require(type(value) is list)
    return cast(list[object], value)


def _text(value: object) -> str:
    _require(type(value) is str and bool(value))
    return cast(str, value)


def _bool(value: object) -> bool:
    _require(type(value) is bool)
    return cast(bool, value)


def _count(value: object) -> int:
    _require(type(value) is int and value >= 0)
    return cast(int, value)


def _date(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    text = _text(value)
    _require(date.fromisoformat(text).isoformat() == text)
    return text


def _instant(value: object) -> datetime:
    result = datetime.fromisoformat(_text(value))
    _require(result.tzinfo is not None and result.utcoffset() is not None)
    return result


def _dates(value: object) -> list[str]:
    values = [_text(_date(item)) for item in _list(value)]
    _require(all(left < right for left, right in pairwise(values)))
    return values


def _codes(value: object, *, numeric: bool = False) -> list[str]:
    values = [_text(item) for item in _list(value)]
    pattern = r"[0-9]{6}" if numeric else r"[A-Za-z0-9]{6}"
    _require(len(values) == len(set(values)))
    _require(all(re.fullmatch(pattern, item) is not None for item in values))
    return values


def _hash(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    value = _text(value)
    _require(re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def _decimal(value: object) -> Decimal:
    text = _text(value)
    _require(len(text) <= 256)
    _require(
        re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text) is not None
    )
    result = Decimal(text)
    _require(result.is_finite() and abs(int(result.as_tuple().exponent)) <= 1000)
    return result


def _number(value: object) -> float:
    _require(type(value) in (int, float))
    result = float(cast(float, value))
    _require(math.isfinite(result))
    return result


def _percent(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise FormationRoomInputError()


def _finite_json(value: object) -> None:
    """Also catch JSON exponents overflowing float and invalid Unicode scalars."""
    if isinstance(value, float):
        _require(math.isfinite(value))
    elif isinstance(value, str):
        _require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value))
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _finite_json(key)
            _finite_json(item)


def _failure(
    value: object, *, day: str | None, kind: str | None, common: bool = False
) -> dict[str, object]:
    failure = _object(value)
    stage = _text(failure["stage"])
    _require(stage in ("input_contract", "risk_snapshot") if common else stage == "scenario")
    _require(failure["category"] in ("calculation", "contract", "unexpected"))
    _require(_date(failure["as_of_date"], nullable=True) == day)
    _require(failure["scenario_kind"] == kind)
    return {"code": _text(failure["code"]), "message": _text(failure["message"])}


def _source_provenance(
    prepared: dict[str, object], codes: list[str], selected_at: str
) -> dict[str, object] | None:
    """Check the display relationship of either saved selection or replay evidence.

    The file and its reported hashes are not authenticated or recomputed here.
    """
    evidence = prepared.get("replay_provenance")
    selection_sha = prepared["selection_file_sha256"]
    if evidence is None:
        _hash(selection_sha)
        return None
    _require(selection_sha is None)
    replay = _object(evidence)
    _require(
        set(replay)
        == {
            "evidence_kind",
            "replay_file_sha256",
            "selection_content_sha256",
            "read_receipt_file_sha256",
            "read_receipt_content_sha256",
            "row_evidence_sha256",
            "features_sha256",
            "history_job_id",
            "as_of",
            "selected_codes",
            "decision_at",
            "replayed_at",
            "read_completed_at",
            "local_snapshot_read_before_decision_confirmed",
            "vendor_release_time_verified",
            "point_in_time_backtest_guaranteed",
        }
    )
    _require(replay["evidence_kind"] == "recomputed_history_replay_with_local_read_receipt_v1")
    for name in (
        "replay_file_sha256",
        "selection_content_sha256",
        "read_receipt_file_sha256",
        "read_receipt_content_sha256",
        "row_evidence_sha256",
        "features_sha256",
    ):
        _hash(replay[name])
    job = _text(replay["history_job_id"])
    _require(re.fullmatch(r"[0-9a-f]{32}", job) is not None)
    _require(job == prepared["history_job_id"])
    _require(_date(replay["as_of"]) == selected_at)
    _require(_codes(replay["selected_codes"]) == codes)
    read_at = _instant(replay["read_completed_at"])
    decided_at = _instant(replay["decision_at"])
    replayed_at = _instant(replay["replayed_at"])
    _require(read_at <= decided_at <= replayed_at)
    _require(replay["local_snapshot_read_before_decision_confirmed"] is True)
    _require(replay["vendor_release_time_verified"] is False)
    _require(replay["point_in_time_backtest_guaranteed"] is False)
    return replay


def _prepared(
    raw: dict[str, object], codes: list[str], selected_at: str, reference: str | None
) -> tuple[
    dict[str, object], list[dict[str, object]], list[dict[str, object]], dict[str, object] | None
]:
    prepared = _object(raw["prepared"])
    _require(prepared["schema_version"] == "1")
    _require(prepared["readiness_scope"] == "risk_model_return_matrix_only")
    ready = _bool(prepared["input_ready"])
    _require(_codes(prepared["selected_codes"], numeric=ready) == codes)
    _require(_date(prepared["selection_as_of"]) == selected_at)
    _require(_date(prepared["reference_price_date"], nullable=True) == reference)
    _require(reference is None or reference <= selected_at)
    _require(prepared["features_consumed_input_hashes_verified"] is False)
    _require(prepared["trading_day_completeness"] == "unverified")
    _require(prepared["point_in_time_backtest_guaranteed"] is False)
    _require(prepared["price_basis"] == "adjusted_close_price_return_excluding_dividends")
    _require(prepared["date_policy"] == "strict_observed_window_v1")
    replay = _source_provenance(prepared, codes, selected_at)
    completion = _object(prepared["selection_completion"])
    _require(_count(completion["selected_count"]) == len(codes))
    requested = _count(completion["requested_top"])
    _require(requested >= len(codes))
    _require(_count(completion["shortfall"]) == requested - len(codes))
    _require(_bool(completion["selection_filled"]) == (len(codes) == requested))
    _require(
        _bool(completion["complete"])
        == (_bool(completion["evaluation_complete"]) and completion["selection_filled"])
    )
    source = _object(prepared["selection_source"])
    _require(_date(source["as_of"]) == selected_at)
    _require(source["history_job_id"] == prepared["history_job_id"])
    reasons: list[dict[str, object]] = [
        {"code": _text(item["code"]), "message": _text(item["description"])}
        for entry in _list(prepared["reasons"])
        for item in [_object(entry)]
    ]
    _require(bool(reasons))
    symbols = []
    ordinals = []
    for entry in _list(prepared["symbols"]):
        symbol = _object(entry)
        code = _text(symbol["code"])
        ordinals.append(_count(symbol["ordinal"]))
        eligible = _count(symbol["eligible_price_count"])
        stored = _count(symbol["stored_price_count"])
        window = _count(symbol["window_price_count"])
        last = _date(symbol["last_eligible_date"], nullable=True)
        first = _date(symbol["first_eligible_date"], nullable=True)
        _require(window <= eligible <= stored)
        _require((eligible == 0) == (first is None and last is None))
        if eligible:
            _require(first is not None and last is not None)
            assert first is not None and last is not None
            _require(first <= last <= selected_at)
        _hash(symbol["verified_source_price_sha256"])
        _hash(symbol["selection_consumed_input_sha256"])
        symbols.append(
            {
                "code": code,
                "price_observations": eligible,
                "last_eligible_date": last,
                "name": None,
                "name_status": "unconfirmed",
            }
        )
    _require([symbol["code"] for symbol in symbols] == codes)
    _require(len(set(ordinals)) == len(ordinals))
    return prepared, symbols, reasons, replay


def _matrix_dates(
    prepared: dict[str, object], codes: list[str], start: str | None, end: str | None, count: int
) -> list[str]:
    matrix = _object(prepared["matrix"])
    _require(_codes(matrix["stock_codes"], numeric=True) == codes)
    dates = _dates(matrix["dates"])
    _require(bool(codes) and bool(dates) and len(dates) == count)
    _require(start is not None and end is not None)
    assert start is not None
    _require(start < dates[0] and dates[-1] == end)
    minimum, maximum = (
        _count(prepared["minimum_observations"]),
        _count(prepared["maximum_observations"]),
    )
    _require(minimum <= count <= maximum and minimum == 504)
    rows = _list(matrix["values"])
    _require(len(rows) == count)
    for row in rows:
        values = _list(row)
        _require(len(values) == len(codes))
        for value in values:
            _decimal(value)
    _require(_dates(prepared["return_start_dates"]) == [start, *dates[:-1]])
    _require(_dates(prepared["inspected_price_dates"]) == [start, *dates])
    return dates


def _snapshot(
    value: object, *, codes: list[str], day: str, dates: list[str], input_hash: str | None
) -> None:
    snapshot = _object(value)
    _require(_date(snapshot["as_of_date"]) == day)
    _require(_codes(snapshot["stock_codes"], numeric=True) == codes)
    _require(_dates(snapshot["consumed_dates"]) == dates)
    _require(_hash(snapshot["consumed_input_fingerprint"]) == input_hash)
    period = _object(snapshot["consumed_period"])
    _require(_date(period["start"]) == dates[0])
    _require(_date(period["end"]) == day and _count(period["observation_count"]) == len(dates))
    scenarios = _list(snapshot["scenarios"])
    _require(len(scenarios) == 4)
    for entry, kind in zip(scenarios, SCENARIO_KIND_ORDER, strict=True):
        scenario = _object(entry)
        _require(scenario["kind"] == kind.value)
        _require(_codes(scenario["stock_codes"], numeric=True) == codes)
        _require(_dates(scenario["observation_dates"]) == dates)


def _holdings(target: dict[str, object], codes: list[str]) -> tuple[list[dict[str, object]], str]:
    size = len(codes)
    raw_weights = _list(target["reconciled_decimal_weights"])
    weights = [_decimal(value) for value in raw_weights]
    lower = [_decimal(value) for value in _list(target["lower_bounds"])]
    upper = [_decimal(value) for value in _list(target["upper_bounds"])]
    _require(len(weights) == len(lower) == len(upper) == size and size >= 5)
    _require(sum(weights, Decimal(0)) == Decimal(1))
    # A 50-digit Decimal addition can conceal a smaller residual. Rational
    # equality verifies the serialized strings exactly without changing them.
    _require(sum((Fraction(value) for value in weights), Fraction(0)) == 1)
    for weight, low, high in zip(weights, lower, upper, strict=True):
        _require(low == 0 and high == Decimal("0.20") and low < weight <= high)
    diagnostics = _object(target["diagnostics_after_reconciliation"])
    post_weights = [_number(item) for item in _list(diagnostics["weights"])]
    _require(post_weights == [float(value) for value in weights])
    contributions = [_number(item) for item in _list(diagnostics["relative_risk_contributions"])]
    flags = [_text(item) for item in _list(diagnostics["bound_flags"])]
    _require(len(contributions) == len(flags) == size)
    _require(all(flag in _BOUND_LABELS for flag in flags))
    for field in ("marginal_risks", "absolute_risk_contributions"):
        values = [_number(item) for item in _list(diagnostics[field])]
        _require(len(values) == size)
    for field in (
        "primal_residual",
        "euler_residual",
        "normalized_max_kkt_residual",
        "complementarity_residual",
    ):
        _require(_number(diagnostics[field]) >= 0)
    dispersion = diagnostics["free_asset_rc_dispersion"]
    _require(("free" in flags) == (dispersion is not None))
    if dispersion is not None:
        _require(_number(dispersion) >= 0)
    volatility = _number(diagnostics["portfolio_volatility"])
    _require(volatility > 0)
    holdings = [
        {
            "code": code,
            "weight": raw_weights[index],
            "weight_display": _percent(weights[index]),
            "bar_percent": format(weights[index] * 100, "f"),
            "relative_risk_display": _percent(Decimal(str(contributions[index]))),
            "upper_display": _percent(upper[index]),
            "lower_display": _percent(lower[index]),
            "bound_flag": flags[index],
            "bound_label": _BOUND_LABELS[flags[index]],
        }
        for index, code in enumerate(codes)
    ]
    return holdings, _percent(Decimal(str(volatility)))


def _project(raw: dict[str, object], source_name: str, sha256: str) -> FormationRoomModel:
    _require(raw["schema"] == ALLOCATION_TARGETS_SCHEMA)
    _require(
        raw["schema_version"] == "1" and raw["code_model_version"] == ALLOCATION_TARGETS_VERSION
    )
    _require(raw["research_scope"] == _SCOPE)
    _require(raw["account_execution_target"] is False and raw["recommended_scenario"] is None)
    status = _text(raw["status"])
    _require(status in _STATUS_LABELS)
    complete, succeeded = _bool(raw["complete"]), _count(raw["succeeded_count"])
    codes = _codes(raw["selected_codes"])
    selected_at = _text(_date(raw["selection_as_of"]))
    reference = _date(raw["reference_price_date"], nullable=True)
    day = _date(raw["calculation_date"], nullable=True)
    prepared, symbols, reasons, replay = _prepared(raw, codes, selected_at, reference)
    ready = _bool(prepared["input_ready"])
    start, end = (_date(prepared[field], nullable=True) for field in ("used_start", "used_end"))
    count = _count(prepared["return_observation_count"])
    _require((start is None) == (end is None))
    if start is not None and end is not None:
        _require(start <= end <= selected_at)
    fingerprints: list[dict[str, object]] = []
    for label, value, nullable in (
        ("선정 파일", prepared["selection_file_sha256"], replay is not None),
        ("가격 창", prepared["price_window_sha256"], True),
        ("입력 준비", prepared["calculation_fingerprint"], True),
        ("위험 입력", raw["risk_input_fingerprint"], True),
        ("위험모형 설정", raw["risk_config_fingerprint"], False),
        ("solver 설정", raw["solver_config_fingerprint"], False),
    ):
        checked_hash = _hash(value, nullable=nullable)
        if checked_hash is not None:
            fingerprints.append({"label": label, "value": checked_hash})
    for field in ("risk_config", "solver_config", "solver_psd_config", "library_provenance"):
        _object(raw[field])
    input_hash = _hash(raw["risk_input_fingerprint"], nullable=True)
    solver_hash = _hash(raw["solver_config_fingerprint"])
    if ready:
        _require(day is not None and day == end == reference)
        dates = _matrix_dates(prepared, codes, start, end, count)
        for entry in _list(prepared["symbols"]):
            symbol = _object(entry)
            _require(_count(symbol["window_price_count"]) == count + 1)
            _require(_date(symbol["last_eligible_date"]) == end)
            _require(_dates(symbol["missing_dates"]) == [])
    else:
        dates = []
        _require(status == "input_unavailable" and day is None and prepared["matrix"] is None)
        _require(
            input_hash is None and raw["risk_snapshot"] is None and raw["common_failure"] is None
        )
    if status == "common_failure":
        _require(ready and raw["risk_snapshot"] is None)
        reasons.append(_failure(raw["common_failure"], day=day, kind=None, common=True))
    elif ready:
        _require(status in ("succeeded", "partial", "failed") and raw["common_failure"] is None)
        assert day is not None
        _snapshot(raw["risk_snapshot"], codes=codes, day=day, dates=dates, input_hash=input_hash)
    scenarios: list[dict[str, object]] = []
    entries = _list(raw["scenarios"])
    _require(len(entries) == 4)
    for entry, kind, label in zip(entries, SCENARIO_KIND_ORDER, _LABELS, strict=True):
        scenario = _object(entry)
        _require(scenario["scenario_kind"] == kind.value)
        state = _text(scenario["status"])
        covariance = _hash(scenario["covariance_fingerprint"], nullable=True)
        failure = None
        holdings: list[dict[str, object]] = []
        volatility = None
        if state == "succeeded":
            _require(status in ("succeeded", "partial") and scenario["failure"] is None)
            target = _object(scenario["target"])
            _require(target["scenario_kind"] == kind.value)
            _require(target["policy_id"] == f"constrained_erc_{kind.value}")
            _require(_date(target["as_of_date"]) == day)
            _require(_codes(target["stock_codes"], numeric=True) == codes)
            _require(_hash(target["covariance_fingerprint"]) == covariance)
            _require(_hash(target["solver_config_fingerprint"]) == solver_hash)
            holdings, volatility = _holdings(target, codes)
        elif state == "failed":
            _require(status in ("partial", "failed") and scenario["target"] is None)
            failure = _failure(scenario["failure"], day=day, kind=kind.value)
        else:
            _require(state == "not_run" and status in ("input_unavailable", "common_failure"))
            _require(
                scenario["target"] is None and scenario["failure"] is None and covariance is None
            )
        scenarios.append(
            {
                "kind": kind.value,
                "label": label,
                "status": state,
                "volatility_display": volatility,
                "failure": failure,
                "holdings": holdings,
                "covariance_fingerprint": covariance,
            }
        )
    actual = sum(scenario["status"] == "succeeded" for scenario in scenarios)
    _require(actual == succeeded and complete == (actual == 4))
    if ready and status != "common_failure":
        _require(status == ("succeeded" if actual == 4 else "partial" if actual else "failed"))
    return FormationRoomModel(
        source_name=source_name,
        source_sha256=sha256,
        status=status,
        status_label=_STATUS_LABELS[status],
        selected_codes=codes,
        selection_as_of=selected_at,
        calculation_date=day,
        reference_price_date=reference,
        selected_count=len(codes),
        return_observation_count=count,
        succeeded_count=succeeded,
        used_start=start,
        used_end=end,
        symbols=symbols,
        scenarios=scenarios,
        reasons=reasons,
        fingerprints=fingerprints,
        limitations=list(_LIMITATIONS),
        replay_provenance=replay,
    )


def parse_targets(
    payload: bytes,
    *,
    source_name: str,
    selection_payload: bytes | None = None,
    presentation: FormationRoomPresentation | None = None,
) -> FormationRoomModel:
    """Read UTF-8 JSON bytes once into a bounded, deterministic display projection."""
    try:
        _require(type(payload) is bytes and 0 < len(payload) <= MAX_TARGETS_BYTES)
        _text(source_name)
        _finite_json(source_name)
        parsed: object = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_constant
        )
        _finite_json(parsed)
        with localcontext(financial_decimal_context()):
            raw = _object(parsed)
            model = _project(raw, source_name, hashlib.sha256(payload).hexdigest())
            if selection_payload is not None:
                names = linked_names(selection_payload, _object(raw["prepared"]))
                model = replace(
                    model,
                    selection_linked=True,
                    symbols=[
                        {
                            **symbol,
                            "name": names[_text(symbol["code"])],
                            "name_status": "verified_selection"
                            if names[_text(symbol["code"])] is not None
                            else "unconfirmed",
                        }
                        for symbol in model.symbols
                    ],
                )
            if presentation is not None:
                _require(isinstance(presentation, FormationRoomPresentation))
                model = replace(model, presentation=presentation)
            return model
    except FormationRoomInputError:
        raise
    except (
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        DecimalException,
        OverflowError,
        RecursionError,
    ):
        raise FormationRoomInputError() from None

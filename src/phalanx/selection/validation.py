"""Strict feature-file boundary: reject contradictions without repairing evidence."""

from __future__ import annotations

import json
import re
from datetime import date
from itertools import pairwise
from typing import cast

from pydantic import ValidationError

from phalanx.domain.candidate_selection import METRIC_RULES, valid_candidate_code
from phalanx.domain.discovery import SourceFile
from phalanx.domain.price_features import (
    CandidatePriceFeatures,
    PriceFeatureMetric,
    PriceFeaturePolicy,
    SymbolPriceFeatures,
)
from phalanx.domain.price_history import HistoryTarget, SymbolStatus
from phalanx.selection.errors import SelectionInputError

_COMBINATIONS = frozenset((rule.name, rule.intervals) for rule in METRIC_RULES.values())


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("inconsistent feature input")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def _validate_utf8_strings(value: object) -> None:
    """Reject unpaired surrogates in decoded JSON keys and nested string values."""
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_utf8_strings(key)
            _validate_utf8_strings(child)
    elif isinstance(value, list):
        for child in value:
            _validate_utf8_strings(child)


def _object(value: object, fields: set[str]) -> dict[str, object]:
    _require(isinstance(value, dict))
    result = cast(dict[str, object], value)
    _require(set(result) == fields)
    return result


def _integers(value: dict[str, object], *names: str) -> None:
    for name in names:
        _require(type(value[name]) is int)


def _date(value: object) -> None:
    _require(isinstance(value, str))
    text = cast(str, value)
    _require(date.fromisoformat(text).isoformat() == text)


def _raw_shape(payload: object) -> None:
    root = _object(payload, set(CandidatePriceFeatures.model_fields))
    _require(type(root["complete"]) is bool)
    _require(root["point_in_time_backtest_guaranteed"] is False)
    _require(isinstance(root["calculated_at"], str))
    for name in ("as_of", "history_requested_start", "history_requested_end"):
        _date(root[name])
    policy = _object(root["policy"], set(PriceFeaturePolicy.model_fields))
    _integers(policy, "annualization_periods", "variance_ddof", "decimal_precision")
    for name in ("return_intervals", "volatility_intervals", "drawdown_intervals"):
        values = policy[name]
        _require(isinstance(values, list))
        _require(all(type(v) is int for v in cast(list[object], values)))
    _require(isinstance(root["symbols"], list))
    for item in cast(list[object], root["symbols"]):
        symbol = _object(item, set(SymbolPriceFeatures.model_fields))
        _integers(symbol, "ordinal", "eligible_observation_count", "used_observation_count")
        if symbol["calendar_days_since_last_observation"] is not None:
            _integers(symbol, "calendar_days_since_last_observation")
        for name in ("used_start", "used_end"):
            if symbol[name] is not None:
                _date(symbol[name])
        target = _object(symbol["target"], set(HistoryTarget.model_fields))
        _require(isinstance(target["source_files"], list))
        for source in cast(list[object], target["source_files"]):
            _integers(_object(source, set(SourceFile.model_fields)), "size_bytes")
        _require(isinstance(symbol["metrics"], list))
        for metric in cast(list[object], symbol["metrics"]):
            fields = _object(metric, set(PriceFeatureMetric.model_fields))
            _integers(fields, "intervals", "required_observations", "available_observations")
            _require(type(fields["available"]) is bool)
            for name in ("window_start", "window_end"):
                if fields[name] is not None:
                    _date(fields[name])


def parse_features(payload: bytes) -> CandidatePriceFeatures:
    """Parse one already-read byte string; duplicate keys and defaults are not accepted."""
    try:
        raw = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _validate_utf8_strings(raw)
        _raw_shape(raw)
        features = CandidatePriceFeatures.model_validate(raw)
        validate_features(features)
        return features
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise SelectionInputError() from None


def validate_features(features: CandidatePriceFeatures) -> None:
    """Check the fixed feature contract without reopening files or verifying source prices."""
    try:
        _require(features.schema_version == "1" and features.policy == PriceFeaturePolicy())
        _require(re.fullmatch(r"[0-9a-f]{32}", features.history_job_id) is not None)
        _require(bool(features.discovery_run_id.strip()))
        _require(
            features.history_requested_start <= features.as_of <= features.history_requested_end
        )
        _require(bool(features.symbols))
        _require(len({s.ordinal for s in features.symbols}) == len(features.symbols))
        codes = [
            s.target.short_code
            for s in features.symbols
            if valid_candidate_code(s.target.short_code)
        ]
        _require(len(set(codes)) == len(codes))
        for symbol in features.symbols:
            _validate_symbol(features, symbol)
        _require(features.complete == all(s.complete for s in features.symbols))
    except ValueError:
        raise SelectionInputError() from None


def _validate_symbol(features: CandidatePriceFeatures, symbol: SymbolPriceFeatures) -> None:
    combinations = [(m.name, m.intervals) for m in symbol.metrics]
    _require(len(combinations) == 8 and set(combinations) == _COMBINATIONS)
    count = symbol.eligible_observation_count
    used = symbol.used_observation_count
    _require(used == min(count, 253))
    has_result = symbol.source_status in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY)
    _require(has_result == (symbol.source_price_sha256 is not None))
    _require(has_result == (symbol.consumed_input_sha256 is not None))
    if symbol.source_status != SymbolStatus.COMPLETED:
        _require(count == 0)
    if used == 0:
        _require(
            symbol.used_start is None
            and symbol.used_end is None
            and symbol.last_close is None
            and symbol.calendar_days_since_last_observation is None
        )
        if symbol.source_status == SymbolStatus.COMPLETED:
            _require(features.as_of < features.history_requested_end)
    else:
        start, end = symbol.used_start, symbol.used_end
        _require(start is not None and end is not None and symbol.last_close is not None)
        assert start is not None and end is not None and symbol.last_close is not None
        _require(features.history_requested_start <= start <= end <= features.as_of)
        _require(symbol.last_close > 0)
        _require(symbol.calendar_days_since_last_observation == (features.as_of - end).days)
        _require(used <= (end - start).days + 1)
        _require((used == 1) == (start == end))
        _require(count - used <= (start - features.history_requested_start).days)
    for metric in symbol.metrics:
        _validate_metric(symbol, metric)
    available = sorted((m for m in symbol.metrics if m.available), key=lambda m: m.intervals)
    for shorter, longer in pairwise(available):
        assert shorter.window_start is not None and longer.window_start is not None
        if shorter.intervals == longer.intervals:
            _require(shorter.window_start == longer.window_start)
        else:
            _require(
                (shorter.window_start - longer.window_start).days
                >= longer.intervals - shorter.intervals
            )


def _validate_metric(symbol: SymbolPriceFeatures, metric: PriceFeatureMetric) -> None:
    count = symbol.eligible_observation_count
    required = metric.intervals + 1
    expected_available = symbol.source_status == SymbolStatus.COMPLETED and count >= required
    _require(
        metric.available == expected_available and metric.available == (metric.value is not None)
    )
    _require(metric.required_observations == required and metric.available_observations == count)
    if metric.available:
        _require(metric.reason is None and metric.reason_code is None)
        _require(metric.window_end == symbol.used_end)
        start, end = metric.window_start, metric.window_end
        _require(start is not None and end is not None and symbol.used_start is not None)
        assert start is not None and end is not None and symbol.used_start is not None
        _require(symbol.used_start <= start <= end)
        _require((end - start).days >= metric.intervals)
        _require((start - symbol.used_start).days >= symbol.used_observation_count - required)
        if symbol.used_observation_count == required:
            _require(start == symbol.used_start)
        assert metric.value is not None
        if metric.name == "annualized_volatility":
            _require(metric.value >= 0)
        elif metric.name == "maximum_drawdown":
            _require(-1 <= metric.value <= 0)
        else:
            _require(metric.value >= -1)
    else:
        _require(metric.window_start is None and metric.window_end is None)
        if symbol.source_status != SymbolStatus.COMPLETED:
            expected_reason = f"SOURCE_{symbol.source_status.value.upper()}"
        elif count == 0:
            expected_reason = "NO_OBSERVATIONS_AS_OF"
        else:
            expected_reason = "INSUFFICIENT_OBSERVATIONS"
        _require(
            metric.reason_code == expected_reason and bool(metric.reason and metric.reason.strip())
        )

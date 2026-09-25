"""Strict selection JSON boundary using the existing selection validation idioms."""

from __future__ import annotations

import json
import re
from typing import cast

from phalanx.domain.candidate_selection import (
    CandidateEvaluation,
    CandidateSelection,
    SelectionPolicy,
    SelectionReason,
    SelectionSource,
)
from phalanx.domain.discovery import SourceFile
from phalanx.domain.price_features import (
    PriceFeatureMetric,
    PriceFeaturePolicy,
    SymbolPriceFeatures,
)
from phalanx.domain.price_history import HistoryTarget, SymbolStatus
from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.selection.engine import _unavailable_reasons
from phalanx.selection.validation import (
    _date,
    _integers,
    _object,
    _reject_constant,
    _require,
    _unique_object,
    _validate_metric,
    _validate_utf8_strings,
)


def _raw_shape(payload: object) -> None:
    root = _object(payload, set(CandidateSelection.model_fields))
    for name in ("evaluation_complete", "selection_filled", "complete"):
        _require(type(root[name]) is bool)
    _require(root["point_in_time_backtest_guaranteed"] is False)
    _require(isinstance(root["evaluated_at"], str))
    if root["reference_price_date"] is not None:
        _date(root["reference_price_date"])
    source = _object(root["source"], set(SelectionSource.model_fields))
    _date(source["as_of"])
    _require(isinstance(source["calculated_at"], str))
    _require(type(source["features_complete"]) is bool)
    _require(source["source_price_hashes_verified"] is False)
    policy = _object(source["feature_policy"], set(PriceFeaturePolicy.model_fields))
    _integers(policy, "annualization_periods", "variance_ddof", "decimal_precision")
    for name in ("return_intervals", "volatility_intervals", "drawdown_intervals"):
        _require(isinstance(policy[name], list))
        _require(all(type(v) is int for v in cast(list[object], policy[name])))
    _object(root["policy"], set(SelectionPolicy.model_fields))
    _require(isinstance(root["candidates"], list))
    for item in cast(list[object], root["candidates"]):
        candidate = _object(item, set(CandidateEvaluation.model_fields))
        for name in ("used_start", "used_end"):
            if candidate[name] is not None:
                _date(candidate[name])
        target = _object(candidate["target"], set(HistoryTarget.model_fields))
        _require(isinstance(target["source_files"], list))
        for file in cast(list[object], target["source_files"]):
            _integers(_object(file, set(SourceFile.model_fields)), "size_bytes")
        metric = _object(candidate["selected_feature"], set(PriceFeatureMetric.model_fields))
        _integers(metric, "intervals", "required_observations", "available_observations")
        _require(type(metric["available"]) is bool)
        for name in ("window_start", "window_end"):
            if metric[name] is not None:
                _date(metric[name])
        _require(isinstance(candidate["reasons"], list))
        for reason in cast(list[object], candidate["reasons"]):
            _object(reason, set(SelectionReason.model_fields))


def _validate_evidence(selection: CandidateSelection) -> None:
    _require(re.fullmatch(r"[0-9a-f]{32}", selection.source.history_job_id) is not None)
    _require(bool(selection.source.discovery_run_id.strip()))
    _require(selection.source.feature_policy == PriceFeaturePolicy())
    _require(
        selection.source.features_complete
        == all(
            candidate.source_status == SymbolStatus.COMPLETED
            and candidate.eligible_observation_count >= 253
            for candidate in selection.candidates
        )
    )
    for candidate in selection.candidates:
        count = candidate.eligible_observation_count
        used = candidate.used_observation_count
        _require(used == min(count, 253))
        has_result = candidate.source_status in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY)
        _require(has_result == (candidate.source_price_sha256 is not None))
        _require(has_result == (candidate.consumed_input_sha256 is not None))
        if candidate.source_status != SymbolStatus.COMPLETED:
            _require(count == 0)
        if used:
            start, end, close = candidate.used_start, candidate.used_end, candidate.last_close
            _require(start is not None and end is not None and close is not None)
            assert start is not None and end is not None and close is not None
            _require(start <= end <= selection.source.as_of and close > 0)
            _require(used <= (end - start).days + 1)
            _require((used == 1) == (start == end))
            _require(
                candidate.calendar_days_since_last_observation
                == (selection.source.as_of - end).days
            )
        else:
            _require(
                candidate.used_start is None
                and candidate.used_end is None
                and candidate.last_close is None
                and candidate.calendar_days_since_last_observation is None
            )
        # Reuse the producer's metric and eligibility rules, without pretending
        # to have the other seven features or recomputing selection scores.
        symbol = SymbolPriceFeatures(
            **{
                name: getattr(candidate, name)
                for name in SymbolPriceFeatures.model_fields
                if name != "metrics"
            },
            metrics=(candidate.selected_feature,),
        )
        _validate_metric(symbol, candidate.selected_feature)
        reasons = _unavailable_reasons(
            symbol, candidate.selected_feature, selection.reference_price_date, selection.policy
        )
        _require((candidate.status == "unavailable") == bool(reasons))
        if reasons:
            _require([r.code for r in candidate.reasons] == [r.code for r in reasons])
        _require(all(bool(r.description.strip()) for r in candidate.reasons))


def parse_selection(payload: bytes) -> CandidateSelection:
    """Parse and validate exactly these bytes; all serialized fields are mandatory."""
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _validate_utf8_strings(raw)
        _raw_shape(raw)
        selection = CandidateSelection.model_validate(raw)
        _validate_evidence(selection)
        return selection
    except (ValueError, UnicodeError, RecursionError):
        raise AllocationInputError() from None

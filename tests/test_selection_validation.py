from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from selection_helpers import AS_OF, features

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import SymbolStatus
from phalanx.selection.errors import SelectionInputError
from phalanx.selection.validation import parse_features


def raw():
    return json.loads(features().to_json_bytes())


def replace(payload, path, value):
    current = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), "2"),
        (("policy", "version"), "future_policy"),
        (("policy", "return_intervals"), [20, 60, 120]),
        (("policy", "volatility_intervals"), [60, 20]),
        (("policy", "drawdown_intervals"), [60, 251]),
        (("policy", "annualization_periods"), 365),
        (("policy", "variance_ddof"), True),
        (("policy", "decimal_precision"), 49),
        (("policy", "decimal_rounding"), "ROUND_UP"),
        (("policy", "consumed_input_contract"), "unknown"),
        (("complete",), False),
        (("complete",), "true"),
        (("point_in_time_backtest_guaranteed",), 0),
        (("trading_day_completeness",), "verified"),
        (("price_basis",), "total_return"),
        (("history_job_id",), "not-a-job-id"),
        (("discovery_run_id",), ""),
        (("as_of",), "2024-12-31"),
        (("as_of",), "2026-09-01"),
        (("as_of",), "20260820"),
        (("history_requested_start",), "2026-08-31"),
        (("calculated_at",), "2026-09-13T00:00:00"),
        (("symbols", 1, "ordinal"), 0),
        (("symbols", 0, "ordinal"), True),
        (("symbols", 0, "ordinal"), "0"),
        (("symbols", 1, "target", "short_code"), "0001A0"),
        (("symbols", 0, "source_status"), "failed"),
        (("symbols", 0, "source_price_sha256"), None),
        (("symbols", 0, "consumed_input_sha256"), None),
        (("symbols", 0, "source_price_sha256"), "not-a-hash"),
        (("symbols", 0, "eligible_observation_count"), 252),
        (("symbols", 0, "eligible_observation_count"), 999999),
        (("symbols", 0, "used_observation_count"), 252),
        (("symbols", 0, "used_observation_count"), True),
        (("symbols", 0, "used_start"), None),
        (("symbols", 0, "used_start"), "2026-08-19"),
        (("symbols", 0, "used_end"), "2026-08-21"),
        (("symbols", 0, "calendar_days_since_last_observation"), 1),
        (("symbols", 0, "calendar_days_since_last_observation"), False),
        (("symbols", 0, "last_close"), None),
        (("symbols", 0, "last_close"), "0"),
        (("symbols", 0, "last_close"), "-1"),
        (("symbols", 0, "last_close"), 100.0),
        (("symbols", 0, "last_close"), True),
        (("symbols", 0, "last_close"), "NaN"),
        (("symbols", 0, "metrics", 0, "name"), "composite_score"),
        (("symbols", 0, "metrics", 0, "available"), False),
        (("symbols", 0, "metrics", 0, "available"), 1),
        (("symbols", 0, "metrics", 0, "value"), None),
        (("symbols", 0, "metrics", 0, "value"), 0.1),
        (("symbols", 0, "metrics", 0, "value"), False),
        (("symbols", 0, "metrics", 0, "value"), "Infinity"),
        (("symbols", 0, "metrics", 0, "value"), "-1.01"),
        (("symbols", 0, "metrics", 4, "value"), "-0.1"),
        (("symbols", 0, "metrics", 6, "value"), "0.1"),
        (("symbols", 0, "metrics", 6, "value"), "-1.1"),
        (("symbols", 0, "metrics", 0, "intervals"), 21),
        (("symbols", 0, "metrics", 0, "required_observations"), 20),
        (("symbols", 0, "metrics", 0, "available_observations"), 252),
        (("symbols", 0, "metrics", 0, "window_start"), "2026-08-20"),
        (("symbols", 0, "metrics", 0, "window_end"), "2026-08-19"),
        (("symbols", 0, "metrics", 0, "reason_code"), "unexpected"),
    ],
)
def test_contradictory_or_malformed_feature_fields_are_input_errors(path, value) -> None:
    payload = raw()
    replace(payload, path, value)
    with pytest.raises(SelectionInputError) as error:
        parse_features(json.dumps(payload).encode())
    assert error.value.code == "INVALID_FEATURES"
    assert "0001A0" not in str(error.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_metric",
        "duplicate_metric",
        "same_interval_window",
        "nested_window",
        "defaulted_policy",
        "defaulted_schema",
        "missing_reason",
    ],
)
def test_structure_and_cross_metric_contradictions_are_rejected(mutation: str) -> None:
    payload = raw()
    metrics = payload["symbols"][0]["metrics"]
    if mutation == "missing_metric":
        metrics.pop()
    elif mutation == "duplicate_metric":
        metrics[-1] = metrics[0]
    elif mutation == "same_interval_window":
        # Both 20-interval metrics must refer to the same observation window.
        metrics[4]["window_start"] = "2026-07-30"
    elif mutation == "nested_window":
        metrics[1]["window_start"] = "2026-06-20"
    elif mutation == "defaulted_policy":
        del payload["policy"]["version"]
    elif mutation == "defaulted_schema":
        del payload["schema_version"]
    else:
        del metrics[0]["reason"]
    with pytest.raises(SelectionInputError):
        parse_features(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "mutation",
    [
        "available_despite_shortage",
        "false_complete",
        "wrong_reason",
        "missing_reason",
        "fake_window",
        "fake_hash",
        "fake_observations",
    ],
)
def test_normal_partial_results_are_accepted_but_contradictions_are_not(mutation) -> None:
    source = features(counts=(61, 21, 1))
    assert parse_features(source.to_json_bytes()) == source
    payload = json.loads(source.to_json_bytes())
    metric = payload["symbols"][0]["metrics"][3]
    if mutation == "available_despite_shortage":
        metric.update(
            available=True,
            value="0",
            reason=None,
            reason_code=None,
            window_start="2026-06-21",
            window_end=AS_OF.isoformat(),
        )
    elif mutation == "false_complete":
        payload["complete"] = True
    elif mutation == "wrong_reason":
        metric["reason_code"] = "SOURCE_FAILED"
    elif mutation == "missing_reason":
        metric["reason"] = None
    elif mutation == "fake_window":
        metric["window_end"] = AS_OF.isoformat()
    else:
        payload = json.loads(features(statuses=(SymbolStatus.PENDING,) * 3).to_json_bytes())
        if mutation == "fake_hash":
            payload["symbols"][0]["source_price_sha256"] = "a" * 64
        else:
            payload["symbols"][0]["eligible_observation_count"] = 1
    with pytest.raises(SelectionInputError):
        parse_features(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "payload",
    [
        b'{"complete":true,"complete":true}',
        b'{"x":{"x":1,"x":2}}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b"\xff",
        b"null",
        b"[]",
        b"{",
        b"{}",
    ],
)
def test_invalid_json_duplicate_keys_and_nonfinite_numbers_are_rejected(payload: bytes) -> None:
    with pytest.raises(SelectionInputError):
        parse_features(payload)


def test_duplicate_key_in_otherwise_valid_document_is_not_last_wins() -> None:
    payload = features().to_json_bytes()
    payload = payload.replace(b'"complete": true', b'"complete": false, "complete": true', 1)
    with pytest.raises(SelectionInputError):
        parse_features(payload)


def raw_with_source_files():
    payload = json.loads(features(statuses=(SymbolStatus.FAILED,) * 3).to_json_bytes())
    payload["symbols"][0]["target"]["source_files"] = [
        {"filename": "synthetic-source.mst", "sha256": "a" * 64, "size_bytes": 1}
    ]
    return payload


_TEXT_PATHS = [
    ("discovery_run_id",),
    ("symbols", 0, "target", "name"),
    ("symbols", 0, "target", "source_files", 0, "filename"),
    ("symbols", 0, "source_error_message"),
    ("symbols", 0, "metrics", 0, "reason"),
]


@pytest.mark.parametrize("path", _TEXT_PATHS)
@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"], ids=["high", "low"])
def test_unpaired_surrogates_are_input_errors_at_every_text_depth(path, surrogate) -> None:
    payload = raw_with_source_files()
    # The document is otherwise valid, including nested source/error evidence.
    assert parse_features(json.dumps(payload).encode()).symbols[0].source_status == "failed"
    replace(payload, path, "synthetic-" + surrogate)
    with pytest.raises(SelectionInputError) as error:
        parse_features(json.dumps(payload).encode())
    assert error.value.code == "INVALID_FEATURES"


@pytest.mark.parametrize("path", _TEXT_PATHS)
@pytest.mark.parametrize("escaped", [True, False], ids=["surrogate-pair", "utf8"])
def test_korean_and_emoji_survive_parsing_and_serialization(path, escaped: bool) -> None:
    payload = raw_with_source_files()
    replace(payload, path, "한글 이름·출처·설명 😀")
    encoded = json.dumps(payload, ensure_ascii=escaped).encode("utf-8")
    if escaped:
        assert rb"\ud83d\ude00" in encoded
    parsed = parse_features(encoded)
    assert json.loads(parsed.to_json_bytes()) == payload


@pytest.mark.parametrize(
    "top,age", [(0, 7), (-1, 7), (True, 7), (1.0, 7), (1, -1), (1, False), (1, 7.0)]
)
def test_policy_parameters_are_explicit_strict_integers(top, age) -> None:
    with pytest.raises(ValidationError):
        SelectionPolicy(metric=SelectionMetric.RETURN_60, top=top, max_age_days=age)

from __future__ import annotations

import json

import pytest
from allocation_input_helpers import create_inputs

from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.portfolio.allocation_input.validation import parse_selection


@pytest.fixture(scope="module")
def valid_bytes(tmp_path_factory):
    _, path, _, _ = create_inputs(tmp_path_factory.mktemp("selection-boundary"))
    return path.read_bytes()


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), "2"),
        (("complete",), "true"),
        (("complete",), False),
        (("evaluation_complete",), 1),
        (("selection_filled",), False),
        (("point_in_time_backtest_guaranteed",), 0),
        (("selected_count",), True),
        (("selected_count",), "2"),
        (("requested_top",), 2.0),
        (("shortfall",), 1),
        (("selected_codes",), ["000001", "005930"]),
        (("selected_codes",), [5930, "000001"]),
        (("reference_price_date",), "2026-08-19"),
        (("evaluated_at",), 1700000000),
        (("source", "as_of"), "20260820"),
        (("source", "as_of"), "2026-08-19"),
        (("source", "calculated_at"), "2026-08-20T00:00:00"),
        (("source", "history_job_id"), "latest"),
        (("source", "discovery_run_id"), " "),
        (("source", "features_complete"), "true"),
        (("source", "features_complete"), False),
        (("source", "source_price_hashes_verified"), 0),
        (("source", "feature_policy", "decimal_precision"), 50.0),
        (("source", "feature_policy", "variance_ddof"), True),
        (("source", "feature_policy", "return_intervals"), [20.0, 60, 120, 252]),
        (("policy", "top"), True),
        (("policy", "max_age_days"), "7"),
        (("candidates", 0, "ordinal"), 1),
        (("candidates", 0, "ordinal"), "0"),
        (("candidates", 0, "selection_order"), 2),
        (("candidates", 0, "source_price_sha256"), None),
        (("candidates", 0, "source_status"), "failed"),
        (("candidates", 0, "status"), "not_selected"),
        (("candidates", 0, "eligible_observation_count"), True),
        (("candidates", 0, "used_observation_count"), 252),
        (("candidates", 0, "used_start"), "2026-08-19"),
        (("candidates", 0, "last_close"), 11008.0),
        (("candidates", 0, "last_close"), True),
        (("candidates", 0, "last_close"), "0"),
        (("candidates", 0, "last_close"), "NaN"),
        (("candidates", 0, "score"), 0.2),
        (("candidates", 0, "score"), False),
        (("candidates", 0, "score"), "Infinity"),
        (("candidates", 0, "calendar_days_since_last_observation"), False),
        (("candidates", 0, "selected_feature", "available"), 1),
        (("candidates", 0, "selected_feature", "intervals"), 60.0),
        (("candidates", 0, "selected_feature", "value"), 0.1),
        (("candidates", 0, "selected_feature", "window_start"), "2026-08-20"),
        (("candidates", 0, "reasons", 0, "code"), "OUTSIDE_TOP_N"),
        (("candidates", 0, "reasons", 0, "description"), ""),
        (("candidates", 0, "target", "name"), "bad\ud800"),
        (("source", "discovery_run_id"), "bad\udfff"),
    ],
)
def test_malformed_or_contradictory_selection_is_rejected(valid_bytes, path, value):
    raw = json.loads(valid_bytes)
    current = raw
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(AllocationInputError) as error:
        parse_selection(json.dumps(raw).encode())
    assert error.value.code == "INVALID_SELECTION"


@pytest.mark.parametrize(
    "path",
    [
        ("schema_version",),
        ("complete",),
        ("source", "feature_schema_version"),
        ("source", "source_price_hashes_verified"),
        ("source", "feature_policy", "version"),
        ("policy", "policy_id"),
        ("candidates", 0, "selected_feature", "reason"),
    ],
)
def test_missing_serialized_fields_cannot_be_hidden_by_defaults(valid_bytes, path):
    raw = json.loads(valid_bytes)
    current = raw
    for key in path[:-1]:
        current = current[key]
    del current[path[-1]]
    with pytest.raises(AllocationInputError):
        parse_selection(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "payload",
    [
        b"null",
        b"[]",
        b"{}",
        b"{",
        b"\xff",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":{"y":1,"y":2}}',
    ],
)
def test_invalid_json_is_safe_input_error(payload):
    with pytest.raises(AllocationInputError):
        parse_selection(payload)


def test_duplicate_keys_in_valid_selection_are_not_last_wins(valid_bytes):
    changed = valid_bytes.replace(b'"complete": true', b'"complete": false,"complete": true', 1)
    with pytest.raises(AllocationInputError):
        parse_selection(changed)


def test_valid_korean_and_emoji_are_accepted(valid_bytes):
    raw = json.loads(valid_bytes)
    raw["candidates"][0]["target"]["name"] = "합성 종목 😀"
    assert parse_selection(json.dumps(raw).encode()).candidates[0].target.name == "합성 종목 😀"


def test_unavailable_candidate_cannot_hide_eligibility(valid_bytes):
    raw = json.loads(valid_bytes)
    raw["candidates"][1].update(
        status="unavailable",
        selection_order=None,
        metric_rank=None,
        reasons=[{"code": "FAKE", "description": "fake exclusion"}],
    )
    raw.update(
        selected_codes=["005930"],
        selected_count=1,
        eligible_count=1,
        unavailable_count=1,
        shortfall=1,
        selection_filled=False,
        evaluation_complete=False,
        complete=False,
    )
    with pytest.raises(AllocationInputError):
        parse_selection(json.dumps(raw).encode())

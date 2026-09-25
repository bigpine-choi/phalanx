from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest
from allocation_targets_helpers import CODES, target_inputs
from formation_room_helpers import saved_targets

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.risk_model import SCENARIO_KIND_ORDER
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.formation_room.errors import FormationRoomInputError
from phalanx.portfolio.formation_room.parser import parse_targets


@pytest.fixture(scope="module")
def saved_cases(tmp_path_factory):
    directory = tmp_path_factory.mktemp("formation-parser")
    return {
        case: saved_targets(directory / case, case)
        for case in (
            "succeeded",
            "boundary",
            "input_unavailable",
            "common_failure",
            "failed",
            "partial",
        )
    }


def encoded(raw):
    return json.dumps(raw, ensure_ascii=False).encode()


@pytest.mark.parametrize(
    "case,status,count",
    [
        ("succeeded", "succeeded", 4),
        ("boundary", "succeeded", 4),
        ("input_unavailable", "input_unavailable", 0),
        ("common_failure", "common_failure", 0),
        ("failed", "failed", 0),
        ("partial", "partial", 3),
    ],
)
def test_real_saved_results_support_all_states_and_boundary(saved_cases, case, status, count):
    payload = saved_cases[case]
    raw = json.loads(payload)
    model = parse_targets(payload, source_name=f"{case}.json").to_payload()
    assert model["status"] == status and model["succeeded_count"] == count
    assert model["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert model["source_name"] == f"{case}.json"
    assert model["selected_codes"] == raw["selected_codes"]
    assert model["selected_count"] == len(raw["selected_codes"])
    assert model["return_observation_count"] == raw["prepared"]["return_observation_count"]
    assert [row["kind"] for row in model["scenarios"]] == list(SCENARIO_KIND_ORDER)
    assert [row["code"] for row in model["symbols"]] == raw["selected_codes"]
    assert model["calculation_date"] == raw["calculation_date"]
    for projected, source in zip(model["scenarios"], raw["scenarios"], strict=True):
        if source["status"] != "succeeded":
            assert projected["holdings"] == [] and projected["volatility_display"] is None
            if source["failure"]:
                assert projected["failure"] == {
                    key: source["failure"][key] for key in ("code", "message")
                }
            continue
        assert [row["code"] for row in projected["holdings"]] == raw["selected_codes"]
        original = source["target"]["reconciled_decimal_weights"]
        assert [row["weight"] for row in projected["holdings"]] == original
        with localcontext(financial_decimal_context()):
            assert [row["weight_display"] for row in projected["holdings"]] == [
                f"{Decimal(value) * 100:.2f}%" for value in original
            ]
        if case == "boundary":
            assert all(row["weight_display"] == "20.00%" for row in projected["holdings"])
            assert all(row["bound_flag"] == "upper" for row in projected["holdings"])
    packed = json.dumps(model)
    assert "annualized_covariance" not in packed and '"matrix"' not in packed
    assert "diagnostics_before_reconciliation" not in packed


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema",), "unknown"),
        (("schema_version",), 1),
        (("code_model_version",), "future"),
        (("research_scope",), "account"),
        (("account_execution_target",), 0),
        (("recommended_scenario",), "fast_iewma"),
        (("complete",), 1),
        (("complete",), False),
        (("succeeded_count",), True),
        (("succeeded_count",), 3),
        (("status",), "partial"),
        (("selection_as_of",), "2026-01-01"),
        (("calculation_date",), None),
        (("reference_price_date",), "2026-08-19"),
        (("selected_codes", 0), "AAAAAA"),
        (("prepared", "input_ready"), 1),
        (("prepared", "return_observation_count"), True),
        (("prepared", "used_end"), "2026-08-19"),
        (("prepared", "features_consumed_input_hashes_verified"), True),
        (("prepared", "point_in_time_backtest_guaranteed"), True),
        (("prepared", "trading_day_completeness"), "verified"),
        (("prepared", "selection_completion", "selected_count"), 7),
        (("prepared", "selection_completion", "complete"), 1),
        (("prepared", "selection_source", "as_of"), "2026-08-19"),
        (("prepared", "matrix", "dates", 0), "2026-08-21"),
        (("prepared", "matrix", "values", 0, 0), True),
        (("prepared", "symbols", 0, "eligible_price_count"), False),
        (("prepared", "symbols", 0, "last_eligible_date"), "2026-08-21"),
        (("risk_snapshot", "consumed_input_fingerprint"), "0" * 64),
        (("risk_snapshot", "consumed_period", "observation_count"), 503),
        (("risk_snapshot", "stock_codes", 0), "999999"),
        (("scenarios", 0, "scenario_kind"), "fast_iewma"),
        (("scenarios", 0, "status"), "not_run"),
        (("scenarios", 0, "target"), None),
        (("scenarios", 0, "target", "policy_id"), "different_policy"),
        (("scenarios", 0, "target", "as_of_date"), "2026-08-19"),
        (("scenarios", 0, "target", "stock_codes", 0), "999999"),
        (("scenarios", 0, "target", "solver_config_fingerprint"), "0" * 64),
        (("scenarios", 0, "target", "covariance_fingerprint"), "0" * 64),
        (("scenarios", 0, "target", "reconciled_decimal_weights", 0), 0.15),
        (("scenarios", 0, "target", "reconciled_decimal_weights", 0), "NaN"),
        (("scenarios", 0, "target", "reconciled_decimal_weights", 0), "-0.01"),
        (("scenarios", 0, "target", "reconciled_decimal_weights", 0), "0.21"),
        (("scenarios", 0, "target", "reconciled_decimal_weights", 0), "0.10"),
        (("scenarios", 0, "target", "lower_bounds", 0), "0.01"),
        (("scenarios", 0, "target", "upper_bounds", 0), "0.30"),
    ],
)
def test_rejects_incoherent_projection_fields(saved_cases, path, value):
    raw = json.loads(saved_cases["succeeded"])
    node = raw
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("weights", [0.2] * 6),
        ("portfolio_volatility", True),
        ("portfolio_volatility", "0.12"),
        ("portfolio_volatility", 0),
        ("relative_risk_contributions", [0.2] * 5),
        ("relative_risk_contributions", [True] * 6),
        ("bound_flags", ["free"] * 5),
        ("bound_flags", ["unknown"] * 6),
        ("absolute_risk_contributions", [0.2] * 5),
        ("marginal_risks", ["0.2"] * 6),
        ("primal_residual", -0.1),
        ("free_asset_rc_dispersion", None),
    ],
)
def test_displayed_diagnostics_must_be_post_reconciliation_typed_and_aligned(
    saved_cases, field, value
):
    raw = json.loads(saved_cases["succeeded"])
    raw["scenarios"][0]["target"]["diagnostics_after_reconciliation"][field] = value
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


def test_negative_relative_risk_is_preserved_and_pre_reconciliation_not_used(saved_cases):
    raw = json.loads(saved_cases["succeeded"])
    target = raw["scenarios"][0]["target"]
    target["diagnostics_after_reconciliation"]["relative_risk_contributions"][0] = -0.015
    target["diagnostics_after_reconciliation"]["portfolio_volatility"] = 0.12345
    target["diagnostics_before_reconciliation"]["portfolio_volatility"] = 0.98765
    model = parse_targets(encoded(raw), source_name="targets.json")
    assert model.scenarios[0]["volatility_display"] == "12.34%"
    assert model.scenarios[0]["holdings"][0]["relative_risk_display"] == "-1.50%"


@pytest.mark.parametrize("case", ["input_unavailable", "common_failure", "failed", "partial"])
def test_failure_state_cannot_contain_stale_success_target(saved_cases, case):
    raw = json.loads(saved_cases[case])
    scenario = next(item for item in raw["scenarios"] if item["status"] != "succeeded")
    scenario["target"] = json.loads(saved_cases["succeeded"])["scenarios"][0]["target"]
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


@pytest.mark.parametrize("field", ["selected_codes", "scenarios"])
def test_duplicate_or_reordered_sequences_rejected(saved_cases, field):
    raw = json.loads(saved_cases["succeeded"])
    raw[field] = list(reversed(raw[field]))
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")
    raw[field][0] = raw[field][1]
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"[]",
        b"null",
        b"true",
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":"\\ud800"}',
        b"[" * 2000,
    ],
)
def test_malformed_json_always_has_safe_fixed_error(payload):
    with pytest.raises(FormationRoomInputError) as error:
        parse_targets(payload, source_name="PRIVATE_MARKER.json")
    assert "PRIVATE_MARKER" not in str(error.value)


def test_size_limit_and_missing_keys_are_safe(saved_cases, monkeypatch):
    monkeypatch.setattr("phalanx.portfolio.formation_room.parser.MAX_TARGETS_BYTES", 32)
    with pytest.raises(FormationRoomInputError):
        parse_targets(saved_cases["succeeded"], source_name="targets.json")
    with pytest.raises(FormationRoomInputError):
        parse_targets(b"{}", source_name="targets.json")


@pytest.mark.parametrize("case", ["succeeded", "boundary"])
def test_decimal_context_cannot_change_validation_or_display(saved_cases, case):
    payload = saved_cases[case]
    expected = parse_targets(payload, source_name="targets.json")
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert parse_targets(payload, source_name="targets.json") == expected
        assert context.prec == 3 and context.traps[Inexact] is True


def test_real_unready_alphanumeric_codes_and_null_endpoint_are_supported(tmp_path):
    repo, path, _, _ = target_inputs(tmp_path, codes=("0001A0", *CODES[1:]), missing=True)
    targets = calculate_allocation_targets(AllocationInputService(repo).prepare(path))
    result = parse_targets(targets.to_json_bytes(), source_name="unready.json")
    assert result.status == "input_unavailable" and "0001A0" in result.selected_codes
    assert result.used_start is None and result.used_end is None and result.calculation_date is None


def test_holiday_selection_date_is_distinct_from_calculation_endpoint(saved_cases):
    raw = json.loads(saved_cases["succeeded"])
    raw["selection_as_of"] = "2026-08-23"
    raw["prepared"]["selection_as_of"] = "2026-08-23"
    raw["prepared"]["selection_source"]["as_of"] = "2026-08-23"
    result = parse_targets(encoded(raw), source_name="targets.json")
    assert result.selection_as_of == "2026-08-23" and result.calculation_date == "2026-08-20"


def test_untrusted_text_is_preserved_for_safe_renderer_without_interpretation(saved_cases):
    raw = json.loads(saved_cases["common_failure"])
    text = '</script><img src=x onerror="alert(1)">&\u2028\u2029'
    raw["common_failure"]["message"] = text
    result = parse_targets(encoded(raw), source_name=text)
    assert result.source_name == text and result.reasons[-1]["message"] == text


def test_decimal_sum_cannot_hide_sub_precision_residual(saved_cases):
    raw = json.loads(saved_cases["boundary"])
    raw["scenarios"][0]["target"]["reconciled_decimal_weights"][0] = "0." + "1" + "9" * 70
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


@pytest.mark.parametrize(
    "case", ["ordinal", "price_count", "window_count", "last_eligible", "missing"]
)
def test_ready_symbol_provenance_must_agree_with_observation_window(saved_cases, case):
    raw = json.loads(saved_cases["succeeded"])
    first, second = raw["prepared"]["symbols"][:2]
    if case == "ordinal":
        first["ordinal"] = second["ordinal"]
    elif case == "price_count":
        first.update(stored_price_count=1, eligible_price_count=1, window_price_count=1)
    elif case == "window_count":
        first["window_price_count"] = 504
    elif case == "last_eligible":
        first["last_eligible_date"] = "2026-08-19"
    else:
        first["missing_dates"] = ["2026-08-19"]
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")


@pytest.mark.parametrize(
    "case,path,value",
    [
        ("common_failure", ("common_failure", "stage"), "scenario"),
        ("common_failure", ("common_failure", "as_of_date"), None),
        ("common_failure", ("common_failure", "scenario_kind"), "fast_iewma"),
        ("common_failure", ("complete",), True),
        ("input_unavailable", ("scenarios", 0, "status"), "failed"),
        ("input_unavailable", ("status",), "failed"),
        ("input_unavailable", ("scenarios", 0, "covariance_fingerprint"), "0" * 64),
        ("failed", ("scenarios", 0, "failure", "scenario_kind"), "fast_iewma"),
        ("failed", ("scenarios", 0, "failure", "as_of_date"), "2026-08-19"),
        ("failed", ("scenarios", 0, "failure"), None),
        ("failed", ("status",), "succeeded"),
        ("partial", ("scenarios", 1, "status"), "succeeded"),
        ("partial", ("succeeded_count",), 4),
        ("partial", ("status",), "failed"),
    ],
)
def test_failure_status_and_evidence_links_cannot_contradict(saved_cases, case, path, value):
    raw = json.loads(saved_cases[case])
    node = raw
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    with pytest.raises(FormationRoomInputError):
        parse_targets(encoded(raw), source_name="targets.json")

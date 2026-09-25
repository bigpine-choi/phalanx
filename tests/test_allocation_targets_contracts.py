from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal

import pytest
from allocation_targets_helpers import target_inputs

from phalanx.domain.risk_model import SCENARIO_KIND_ORDER
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    repo, path, _, _ = target_inputs(tmp_path_factory.mktemp("target-contracts"))
    return calculate_allocation_targets(AllocationInputService(repo).prepare(path))


def corrupted(value, **changes):
    # Simulate a defective external engine that bypasses its frozen domain model.
    result = copy.copy(value)
    for name, replacement in changes.items():
        object.__setattr__(result, name, replacement)
    return result


@pytest.mark.parametrize(
    "field",
    ["used_end", "reference_price_date", "selected_codes", "return_observation_count", "matrix"],
)
def test_prepared_endpoint_and_order_must_match_before_estimation(baseline, field):
    value = {
        "used_end": baseline.calculation_date + timedelta(days=1),
        "reference_price_date": baseline.calculation_date - timedelta(days=1),
        "selected_codes": tuple(reversed(baseline.prepared.selected_codes)),
        "return_observation_count": 503,
        "matrix": None,
    }[field]
    prepared = baseline.prepared.model_copy(update={field: value})

    class Forbidden:
        def estimate(self, *args, **kwargs):
            pytest.fail("inconsistent prepared input reached estimator")

    result = calculate_allocation_targets(prepared, estimator=Forbidden())
    assert result.status == "common_failure"
    assert result.common_failure.stage == "input_contract"
    assert result.common_failure.category == "contract"
    assert result.risk_snapshot is None
    assert all(item.target is None for item in result.scenarios)


@pytest.mark.parametrize(
    "case",
    [
        "date",
        "codes",
        "input_hash",
        "dates",
        "count",
        "scenario_order",
        "scenario_dates",
        "nonfinite",
        "type",
    ],
)
def test_returned_snapshot_must_match_actual_matrix(baseline, monkeypatch, case):
    snapshot = baseline.risk_snapshot
    if case == "date":
        snapshot = corrupted(snapshot, as_of_date=snapshot.as_of_date + timedelta(days=1))
    elif case == "codes":
        snapshot = corrupted(snapshot, stock_codes=tuple(reversed(snapshot.stock_codes)))
    elif case == "input_hash":
        snapshot = corrupted(snapshot, consumed_input_fingerprint="0" * 64)
    elif case == "dates":
        snapshot = corrupted(snapshot, consumed_dates=snapshot.consumed_dates[:-1])
    elif case == "count":
        snapshot = corrupted(snapshot, consumed_observation_count=503)
    elif case == "scenario_order":
        snapshot = corrupted(snapshot, scenarios=tuple(reversed(snapshot.scenarios)))
    elif case == "type":
        snapshot = object()
    else:
        scenario = snapshot.scenarios[0]
        if case == "scenario_dates":
            scenario = corrupted(scenario, observation_dates=scenario.observation_dates[:-1])
        else:
            row = (float("nan"), *scenario.annualized_covariance[0][1:])
            scenario = corrupted(
                scenario, annualized_covariance=(row, *scenario.annualized_covariance[1:])
            )
        snapshot = corrupted(snapshot, scenarios=(scenario, *snapshot.scenarios[1:]))

    class Estimator:
        def estimate(self, *args, **kwargs):
            return snapshot

    def forbidden(*args, **kwargs):
        pytest.fail("invalid snapshot must not reach solver")

    monkeypatch.setattr(ConstrainedErcSolver, "__init__", forbidden)
    result = calculate_allocation_targets(baseline.prepared, estimator=Estimator())
    assert result.status == "common_failure" and result.risk_snapshot is None
    assert result.common_failure.category == "contract"
    assert result.common_failure.stage == "risk_snapshot"
    assert all(item.status == "not_run" and item.target is None for item in result.scenarios)
    assert b"NaN" not in result.to_json_bytes()


@pytest.mark.parametrize(
    "case",
    [
        "date",
        "codes",
        "scenario",
        "policy",
        "covariance_hash",
        "solver_hash",
        "upper_bound",
        "lower_bound",
        "weights",
        "nonfinite",
        "type",
    ],
)
def test_returned_target_must_match_supplied_scenario_and_fingerprints(baseline, case):
    target = baseline.scenarios[0].target
    if case == "nonfinite":
        diag = corrupted(target.diagnostics_after_reconciliation, portfolio_volatility=float("inf"))
        target = corrupted(target, diagnostics_after_reconciliation=diag)
    elif case == "type":
        target = object()
    else:
        field, value = {
            "date": ("as_of_date", target.as_of_date + timedelta(days=1)),
            "codes": ("stock_codes", tuple(reversed(target.stock_codes))),
            "scenario": ("scenario_kind", SCENARIO_KIND_ORDER[1]),
            "policy": ("policy_id", "wrong_policy"),
            "covariance_hash": ("covariance_fingerprint", "0" * 64),
            "solver_hash": ("solver_config_fingerprint", "0" * 64),
            "upper_bound": ("upper_bounds", (Decimal("0.30"),) * 6),
            "lower_bound": ("lower_bounds", (Decimal("0.01"),) * 6),
            "weights": ("reconciled_weights", (Decimal("0.21"),) * 6),
        }[case]
        target = corrupted(target, **{field: value})
    calls = []

    class Solver:
        def solve_scenario(self, scenario, *, as_of_date):
            calls.append(scenario.kind)
            index = SCENARIO_KIND_ORDER.index(scenario.kind)
            return target if index == 0 else baseline.scenarios[index].target

    result = calculate_allocation_targets(baseline.prepared, solver=Solver())
    assert calls == list(SCENARIO_KIND_ORDER)
    assert result.status == "partial" and result.succeeded_count == 3
    assert result.scenarios[0].failure.category == "contract"
    assert result.scenarios[0].target is None
    assert result.scenarios[1:] == baseline.scenarios[1:]
    assert b"Infinity" not in result.to_json_bytes()


@pytest.mark.parametrize("stage", ["risk", "solver", "solver_init"])
def test_unexpected_engine_errors_are_explicit_safe_failures(baseline, monkeypatch, stage):
    class Broken:
        def estimate(self, *args, **kwargs):
            raise RuntimeError("SENSITIVE_TEST_MARKER")

        def solve_scenario(self, *args, **kwargs):
            raise RuntimeError("SENSITIVE_TEST_MARKER")

    options = {"estimator" if stage == "risk" else "solver": Broken()}
    if stage == "solver_init":

        def broken_init(*args, **kwargs):
            raise RuntimeError("SENSITIVE_TEST_MARKER")

        monkeypatch.setattr(ConstrainedErcSolver, "__init__", broken_init)
        options = {}
    result = calculate_allocation_targets(baseline.prepared, **options)
    if stage == "risk":
        assert result.status == "common_failure"
        assert result.common_failure.category == "unexpected"
    else:
        assert result.status == "failed" and result.risk_snapshot is not None
        assert all(item.failure.category == "unexpected" for item in result.scenarios)
    assert all(item.target is None for item in result.scenarios)
    assert b"SENSITIVE_TEST_MARKER" not in result.to_json_bytes()
    assert b"Traceback" not in result.to_json_bytes()

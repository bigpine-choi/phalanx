from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest
from allocation_targets_helpers import CODES, target_inputs

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.risk_model import SCENARIO_KIND_ORDER, CovarianceScenarioKind
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.allocation_targets.errors import AllocationTargetsContractError
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.constrained_erc import (
    ConstrainedErcSolver,
    fingerprint_consumed_covariance,
    fingerprint_solver_config,
)
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel, fingerprint_consumed_risk_input
from phalanx.portfolio.errors import ConstrainedErcCcdConvergenceError


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    repo, path, selection, view = target_inputs(
        tmp_path_factory.mktemp("targets"), failed_candidate=True
    )
    service = AllocationInputService(repo)
    prepared = service.prepare(path)
    result = AllocationTargetsService(service).calculate(path)
    assert result.complete, result.common_failure
    return repo, path, selection, view, prepared, result


def test_real_pipeline_matches_direct_engines_and_all_four_scenarios(pipeline):
    _, _, selection, view, prepared, result = pipeline
    assert selection.complete is False and selection.selection_filled is True
    assert all(state.result.row_count >= 505 for state in view.symbols[:6])
    assert prepared.selected_codes == selection.selected_codes
    assert prepared.selected_codes != CODES  # Ranking really changes column order.
    assert result.prepared == prepared and result.risk_snapshot is not None
    assert len(prepared.matrix.values) == 504
    assert result.calculation_date == prepared.used_end == prepared.reference_price_date
    assert tuple(item.scenario_kind for item in result.scenarios) == SCENARIO_KIND_ORDER
    assert result.status == "succeeded" and result.succeeded_count == 4
    with localcontext(financial_decimal_context()):
        engine = DynamicRiskModel()
        direct_snapshot = engine.estimate(prepared.matrix, as_of_date=prepared.used_end)
        assert result.risk_snapshot == direct_snapshot
        assert result.risk_input_fingerprint == fingerprint_consumed_risk_input(
            prepared.matrix.stock_codes,
            prepared.matrix.dates,
            prepared.matrix.values,
            engine.config,
        )
        solver = ConstrainedErcSolver()
        for item, scenario in zip(result.scenarios, direct_snapshot.scenarios, strict=True):
            direct = solver.solve_scenario(scenario, as_of_date=prepared.used_end)
            assert item.target == direct
            assert item.target.stock_codes == selection.selected_codes
            assert item.target.as_of_date == result.calculation_date
            assert item.target.reconciled_weights == direct.reconciled_weights
            assert sum(item.target.reconciled_weights) == Decimal(1)
            assert all(0 < value <= Decimal("0.20") for value in item.target.reconciled_weights)
            assert (
                item.covariance_fingerprint
                == fingerprint_consumed_covariance(
                    scenario.annualized_covariance, scenario.stock_codes
                )
                == direct.covariance_fingerprint
            )
            assert item.target.solver_config_fingerprint == fingerprint_solver_config(solver.config)
            assert item.target.expected_portfolio_volatility > 0
            assert item.target.diagnostics_after_reconciliation.normalized_max_kkt_residual <= 1e-10
    raw = json.loads(result.to_json_bytes())
    assert raw["prepared"] == prepared.model_dump(mode="json")
    assert raw["prepared"]["features_consumed_input_hashes_verified"] is False
    assert raw["prepared"]["selection_source"]["source_price_hashes_verified"] is False
    assert raw["library_provenance"]["numpy_version"]
    assert raw["account_execution_target"] is False and raw["recommended_scenario"] is None
    for item, encoded in zip(result.scenarios, raw["scenarios"], strict=True):
        assert (
            tuple(Decimal(value) for value in encoded["target"]["reconciled_decimal_weights"])
            == item.target.reconciled_weights
        )
        assert (
            encoded["target"]["diagnostics_after_reconciliation"]["portfolio_volatility"]
            == item.target.expected_portfolio_volatility
        )


def test_service_prepares_once_estimates_once_and_solves_each_scenario_once(pipeline, monkeypatch):
    repo, path, _, _, _, baseline = pipeline
    prepares, estimates, solves = [], [], []
    prepare = AllocationInputService.prepare
    estimate = DynamicRiskModel.estimate
    solve = ConstrainedErcSolver.solve_scenario

    def prepare_once(self, source):
        prepares.append(source)
        assert len(prepares) == 1
        return prepare(self, source)

    def estimate_once(self, matrix, *, as_of_date):
        estimates.append((matrix, as_of_date))
        assert len(estimates) == 1
        return estimate(self, matrix, as_of_date=as_of_date)

    def solve_once(self, scenario, *, as_of_date):
        solves.append((scenario, as_of_date))
        return solve(self, scenario, as_of_date=as_of_date)

    monkeypatch.setattr(AllocationInputService, "prepare", prepare_once)
    monkeypatch.setattr(DynamicRiskModel, "estimate", estimate_once)
    monkeypatch.setattr(ConstrainedErcSolver, "solve_scenario", solve_once)
    result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
    assert result == baseline
    assert prepares == [path]
    assert estimates == [(result.prepared.matrix, result.calculation_date)]
    assert [scenario for scenario, _ in solves] == list(result.risk_snapshot.scenarios)
    assert all(day == result.calculation_date for _, day in solves)


@pytest.mark.parametrize(
    "case,options,reason",
    [
        ("503-returns", {"count": 504}, "INSUFFICIENT_RETURN_OBSERVATIONS"),
        ("date-gap", {"missing": True}, "OBSERVED_DATE_MISMATCH"),
        ("alphanumeric", {"codes": ("0001A0", *CODES[1:])}, "RISK_MODEL_CODE_UNSUPPORTED"),
        ("shortfall", {"top": 7}, "SELECTION_SHORTFALL"),
    ],
)
def test_unavailable_inputs_preserve_reasons_and_never_call_engines(
    tmp_path, monkeypatch, case, options, reason
):
    repo, path, _, _ = target_inputs(tmp_path, **options)
    expected = AllocationInputService(repo).prepare(path)

    def forbidden(*args, **kwargs):
        pytest.fail("unavailable inputs must not construct or call risk/solver engines")

    monkeypatch.setattr(DynamicRiskModel, "__init__", forbidden)
    monkeypatch.setattr(ConstrainedErcSolver, "__init__", forbidden)
    result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
    assert result.prepared == expected
    assert reason in {r.code for r in result.prepared.reasons}
    assert result.status == "input_unavailable" and result.calculation_date is None
    assert result.common_failure is None and result.risk_snapshot is None
    assert all(item.status == "not_run" and item.target is None for item in result.scenarios)


def test_holiday_as_of_and_future_prices_use_only_observation_endpoint(tmp_path):
    as_of, endpoint = date(2026, 8, 23), date(2026, 8, 21)
    results = []
    for future in (0, 4):
        repo, path, _, _ = target_inputs(
            tmp_path / str(future), as_of=as_of, end=endpoint, future=future
        )
        results.append(AllocationTargetsService(AllocationInputService(repo)).calculate(path))
    baseline, result = results
    assert result.complete
    assert result.prepared.selection_as_of == as_of
    assert result.calculation_date == endpoint
    assert result.risk_snapshot.as_of_date == endpoint
    assert result.risk_snapshot == baseline.risk_snapshot
    assert result.scenarios == baseline.scenarios
    assert result.risk_input_fingerprint == baseline.risk_input_fingerprint
    assert all(day <= endpoint for day in result.risk_snapshot.consumed_dates)
    assert all(item.target.as_of_date == endpoint for item in result.scenarios)


@pytest.mark.parametrize("size", [4, 5])
def test_real_solver_cap_feasibility_boundaries(tmp_path, size):
    repo, path, _, _ = target_inputs(tmp_path, size=size)
    result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
    assert result.prepared.input_ready and result.risk_snapshot is not None
    if size == 4:
        assert result.status == "failed" and result.succeeded_count == 0
        assert all(item.target is None and item.status == "failed" for item in result.scenarios)
        assert all(
            item.failure.failure.code == "constrained_erc_infeasible_bounds"
            for item in result.scenarios
        )
        assert all(item.covariance_fingerprint is not None for item in result.scenarios)
    else:
        assert result.status == "succeeded"
        assert all(
            item.target.reconciled_weights == (Decimal("0.20"),) * 5 for item in result.scenarios
        )
        assert all(item.target.all_assets_bound_degeneracy for item in result.scenarios)


def test_one_solver_failure_preserves_other_scenarios(pipeline):
    *_, prepared, baseline = pipeline
    calls = []
    targets = {item.scenario_kind: item.target for item in baseline.scenarios}

    class Solver:
        def solve_scenario(self, scenario, *, as_of_date):
            calls.append(scenario.kind)
            if scenario.kind == CovarianceScenarioKind.FAST_IEWMA:
                raise ConstrainedErcCcdConvergenceError("SENSITIVE_TEST_MARKER")
            return targets[scenario.kind]

    result = calculate_allocation_targets(prepared, solver=Solver())
    assert calls == list(SCENARIO_KIND_ORDER)
    assert result.status == "partial" and result.succeeded_count == 3
    failed = result.scenarios[1]
    assert failed.target is None
    assert failed.failure.category == "calculation"
    assert failed.failure.failure.code == "constrained_erc_ccd_non_convergence"
    assert result.scenarios[0] == baseline.scenarios[0]
    assert result.scenarios[2:] == baseline.scenarios[2:]
    assert b"SENSITIVE_TEST_MARKER" not in result.to_json_bytes()


def test_degenerate_risk_input_is_common_failure_and_does_not_call_solver(tmp_path, monkeypatch):
    repo, path, _, _ = target_inputs(tmp_path, degenerate=True)

    def forbidden(*args, **kwargs):
        pytest.fail("risk snapshot failure must skip solver")

    monkeypatch.setattr(ConstrainedErcSolver, "__init__", forbidden)
    result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
    assert result.prepared.input_ready
    assert result.status == "common_failure" and result.risk_snapshot is None
    assert result.risk_input_fingerprint is not None
    assert result.common_failure.stage == "risk_snapshot"
    assert result.common_failure.category == "calculation"
    assert all(item.status == "not_run" and item.target is None for item in result.scenarios)


def test_external_decimal_context_does_not_change_service_or_json(pipeline):
    repo, path, _, _, _, baseline = pipeline
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
        assert result == baseline
        assert result.to_json_bytes() == baseline.to_json_bytes()
        assert context.prec == 3 and context.traps[Inexact] is True


def test_status_cannot_contradict_outcomes(pipeline):
    baseline = pipeline[-1]
    with pytest.raises(AllocationTargetsContractError, match="모순"):
        replace(baseline, status="partial")
    with pytest.raises(AllocationTargetsContractError, match="모순"):
        replace(baseline.scenarios[0], status="failed")

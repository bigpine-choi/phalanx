from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    CONSTRAINED_ERC_SCENARIO_POLICY_IDS,
    SCENARIO_KIND_ORDER,
    ConstrainedErcBoundFlag,
    ConstrainedErcCommonFailure,
    ConstrainedErcCommonFailureStage,
    ConstrainedErcFailure,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcPolicyOutcome,
    ConstrainedErcRiskSnapshotOutcome,
    ConstrainedErcSolverConfig,
    ConstrainedErcTarget,
    CovarianceScenarioKind,
    scenario_policy_id,
)
from phalanx.portfolio.constrained_erc import solve_constrained_erc
from phalanx.portfolio.errors import InvalidConstrainedErcDomainError


def _stock_codes(count: int = 6) -> tuple[str, ...]:
    return tuple(f"{index + 1:06d}" for index in range(count))


def _target() -> ConstrainedErcTarget:
    covariance = tuple(
        tuple(1.0 if row == column else 0.0 for column in range(6)) for row in range(6)
    )
    return solve_constrained_erc(
        covariance,
        _stock_codes(),
        as_of_date=date(2026, 8, 28),
    )


def _failure() -> ConstrainedErcFailure:
    return ConstrainedErcFailure(
        code="constrained_erc_kkt_validation",
        message="ERC KKT 검증을 완료하지 못했습니다.",
        as_of_date=date(2026, 8, 28),
        scenario_kind=CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
    )


def test_solver_config_has_fixed_preregistered_defaults_and_is_frozen() -> None:
    config = ConstrainedErcSolverConfig()

    assert config.weight_quantum == Decimal("0.000000000001")
    assert config.coordinate_change_tolerance == 1e-12
    assert config.normalized_kkt_tolerance == 1e-10
    assert config.outer_sum_tolerance == 1e-12
    assert config.maximum_ccd_sweeps == 10_000
    assert config.maximum_bisection_iterations == 200
    assert config.maximum_bracket_expansions == 128
    assert config.bracket_expansion_factor == 2.0
    with pytest.raises(FrozenInstanceError):
        config.maximum_ccd_sweeps = 1


@pytest.mark.parametrize(
    "changes",
    (
        {"weight_quantum": Decimal(0)},
        {"weight_quantum": Decimal("NaN")},
        {"coordinate_change_tolerance": 0.0},
        {"normalized_kkt_tolerance": float("inf")},
        {"outer_sum_tolerance": 1},
        {"maximum_ccd_sweeps": 0},
        {"maximum_bisection_iterations": True},
        {"maximum_bracket_expansions": -1},
        {"bracket_expansion_factor": 1.0},
        {"solver_version": "unsupported"},
    ),
)
def test_solver_config_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidConstrainedErcDomainError):
        replace(ConstrainedErcSolverConfig(), **changes)


def test_scenario_policy_mapping_and_fixed_seven_policy_order_are_stable() -> None:
    assert tuple(scenario_policy_id(kind) for kind in SCENARIO_KIND_ORDER) == (
        *CONSTRAINED_ERC_SCENARIO_POLICY_IDS,
    )
    assert CONSTRAINED_ERC_POLICY_ORDER == (
        "constrained_erc_long_run_ledoit_wolf",
        "constrained_erc_fast_iewma",
        "constrained_erc_slow_iewma",
        "constrained_erc_downside_stress_ledoit_wolf",
        "weekly_equal_weight",
        "weekly_inverse_volatility",
        "equal_weight_buy_and_hold",
    )
    with pytest.raises(InvalidConstrainedErcDomainError):
        scenario_policy_id("long_run_ledoit_wolf")


def test_target_is_frozen_and_exposes_reconciled_downstream_weights() -> None:
    target = _target()

    assert target.target_weights is target.reconciled_weights
    assert (
        target.expected_portfolio_volatility
        == target.diagnostics_after_reconciliation.portfolio_volatility
    )
    with pytest.raises(FrozenInstanceError):
        target.reconciled_weights = ()


@pytest.mark.parametrize(
    "changes, message",
    (
        ({"stock_codes": ()}, "비어"),
        ({"stock_codes": ("000001",) * 6}, "중복"),
        ({"stock_codes": ("bad", *_stock_codes()[1:])}, "6자리"),
        ({"as_of_date": "2026-08-28"}, "date"),
        ({"policy_id": "weekly_equal_weight"}, "scenario"),
        ({"risk_budgets": (Decimal("0.1"),) * 6}, "risk budgets"),
        ({"risk_budgets": (Decimal("NaN"),) + (Decimal("0.2"),) * 5}, "유한"),
        ({"lower_bounds": (Decimal("0.2"),) * 6}, "bounds"),
        ({"upper_bounds": (Decimal("NaN"),) + (Decimal("0.2"),) * 5}, "유한"),
        ({"reconciled_weights": (Decimal("0.2"),) * 5}, "길이"),
        (
            {
                "reconciled_weights": (
                    Decimal("0.21"),
                    Decimal("0.19"),
                    *_target().reconciled_weights[2:],
                )
            },
            "bounds",
        ),
        ({"raw_float_weights": (float("nan"),) * 6}, "raw float"),
        ({"lambda_value": 0.0}, "lambda"),
        ({"covariance_fingerprint": "not-a-fingerprint"}, "fingerprint"),
        ({"weight_sum_residual_after": Decimal("0.000000000001")}, "residual"),
        ({"ccd_sweeps": 0}, "sweep"),
        ({"bisection_iterations": -1}, "bisection"),
        ({"bracket_expansions": -1}, "bracket"),
        ({"all_assets_bound_degeneracy": True}, "all-assets-bound"),
    ),
)
def test_target_rejects_invalid_codes_dimensions_decimals_and_diagnostics_flags(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InvalidConstrainedErcDomainError, match=message):
        replace(_target(), **changes)


def test_kkt_diagnostics_reject_nonfinite_or_inconsistent_shapes() -> None:
    diagnostics = _target().diagnostics_after_reconciliation

    with pytest.raises(InvalidConstrainedErcDomainError, match="KKT weights"):
        replace(diagnostics, weights=())
    with pytest.raises(InvalidConstrainedErcDomainError, match="marginal risk"):
        replace(diagnostics, marginal_risks=(float("nan"),) * 6)
    with pytest.raises(InvalidConstrainedErcDomainError, match="bound flags"):
        replace(diagnostics, bound_flags=(ConstrainedErcBoundFlag.FREE,))
    with pytest.raises(InvalidConstrainedErcDomainError, match="KKT residual"):
        replace(diagnostics, normalized_max_kkt_residual=-1.0)
    with pytest.raises(InvalidConstrainedErcDomainError, match="N/A"):
        replace(diagnostics, free_asset_rc_dispersion=None)


def test_target_rejects_non_diagnostic_objects_with_a_typed_error() -> None:
    with pytest.raises(InvalidConstrainedErcDomainError, match="진단"):
        replace(_target(), diagnostics_before_reconciliation=None)
    with pytest.raises(InvalidConstrainedErcDomainError, match="진단"):
        replace(_target(), diagnostics_after_reconciliation=object())


@pytest.mark.parametrize(
    "changes",
    (
        {"code": "BAD CODE"},
        {"message": ""},
        {"as_of_date": "2026-08-28"},
        {"scenario_kind": "fast_iewma"},
    ),
)
def test_failure_rejects_unsafe_or_invalid_fields(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidConstrainedErcDomainError):
        replace(_failure(), **changes)


def test_common_failure_is_frozen_typed_and_not_scenario_specific() -> None:
    common_failure = ConstrainedErcCommonFailure(
        stage=ConstrainedErcCommonFailureStage.INPUT_PREPARATION,
        failure=ConstrainedErcFailure(
            code="constrained_erc_input_error",
            message="Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다.",
        ),
    )

    with pytest.raises(FrozenInstanceError):
        common_failure.stage = ConstrainedErcCommonFailureStage.INPUT_PREPARATION
    with pytest.raises(InvalidConstrainedErcDomainError, match="단계"):
        replace(common_failure, stage="input_preparation")
    with pytest.raises(InvalidConstrainedErcDomainError, match="타입"):
        replace(common_failure, failure=object())
    with pytest.raises(InvalidConstrainedErcDomainError, match="scenario"):
        replace(common_failure, failure=_failure())
    with pytest.raises(InvalidConstrainedErcDomainError, match="전역 입력 오류 코드"):
        replace(
            common_failure,
            failure=ConstrainedErcFailure(
                code="constrained_erc_calculation_error",
                message="Constrained ERC 정책 계산을 완료하지 못했습니다.",
            ),
        )
    with pytest.raises(InvalidConstrainedErcDomainError, match="전역 입력 오류 코드"):
        replace(
            common_failure,
            failure=replace(
                common_failure.failure,
                as_of_date=date(2026, 8, 28),
            ),
        )


def test_failed_policy_outcome_requires_a_typed_sanitized_failure() -> None:
    outcome = ConstrainedErcPolicyOutcome(
        policy_id="weekly_equal_weight",
        status=ConstrainedErcOutcomeStatus.FAILED,
        failure=_failure(),
    )

    assert outcome.result is None
    with pytest.raises(InvalidConstrainedErcDomainError, match="실패"):
        replace(outcome, failure=None)
    with pytest.raises(InvalidConstrainedErcDomainError, match="실패"):
        replace(outcome, failure=object())
    with pytest.raises(InvalidConstrainedErcDomainError, match="성공"):
        replace(outcome, status=ConstrainedErcOutcomeStatus.SUCCEEDED)


def test_policy_outcome_rejects_non_target_elements_with_a_typed_error() -> None:
    with pytest.raises(InvalidConstrainedErcDomainError, match="ERC target"):
        ConstrainedErcPolicyOutcome(
            policy_id="constrained_erc_long_run_ledoit_wolf",
            status=ConstrainedErcOutcomeStatus.FAILED,
            erc_targets=(object(),),
            failure=_failure(),
        )


def test_failed_risk_snapshot_outcome_requires_a_typed_sanitized_failure() -> None:
    outcome = ConstrainedErcRiskSnapshotOutcome(
        as_of_date=date(2026, 8, 28),
        status=ConstrainedErcOutcomeStatus.FAILED,
        failure=_failure(),
    )

    with pytest.raises(InvalidConstrainedErcDomainError, match="실패"):
        replace(outcome, failure=None)
    with pytest.raises(InvalidConstrainedErcDomainError, match="실패"):
        replace(outcome, failure=object())
    with pytest.raises(InvalidConstrainedErcDomainError, match="성공"):
        replace(outcome, status=ConstrainedErcOutcomeStatus.SUCCEEDED)

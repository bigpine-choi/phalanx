"""Dedicated canonical registry for constrained-ERC research trials."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    CONSTRAINED_ERC_SCHEMA,
    AlignedPricePanel,
    AlignedReturnMatrix,
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationRebalanceRecord,
    AllocationTarget,
    ConstrainedErcCommonFailure,
    ConstrainedErcFailure,
    ConstrainedErcPolicyOutcome,
    ConstrainedErcResearchTrial,
    ConstrainedErcRiskSnapshotOutcome,
    ConstrainedErcSolverConfig,
    ConstrainedErcTarget,
    CovarianceScenario,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
)
from phalanx.portfolio.dynamic_risk_model import risk_model_config_payload
from phalanx.portfolio.errors import (
    ConstrainedErcTrialAlreadyExistsError,
    ConstrainedErcTrialLockTimeoutError,
    ConstrainedErcTrialSerializationError,
    ConstrainedErcTrialStorageError,
)
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonLockTimeoutError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)

_LOCK_TIMEOUT_SECONDS = 10.0
_PRODUCTION_ERC_UPPER_BOUND = Decimal("0.20")
_GENERIC_FAILURE_CODE = "constrained_erc_calculation_error"
_SAFE_FAILURE_MESSAGES = {
    "constrained_erc_input_error": "Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다.",
    _GENERIC_FAILURE_CODE: "Constrained ERC 정책 계산을 완료하지 못했습니다.",
    "constrained_erc_infeasible_bounds": (
        "위험자산 합계 1을 만족하는 ERC bounds가 실행 불가능합니다."
    ),
    "constrained_erc_invalid_covariance": (
        "ERC covariance 차원 또는 수치 품질이 올바르지 않습니다."
    ),
    "constrained_erc_degenerate_variance": ("ERC feasible portfolio variance가 양수가 아닙니다."),
    "constrained_erc_lambda_bracket_failure": (
        "ERC positive lambda bracket을 생성하지 못했습니다."
    ),
    "constrained_erc_ccd_non_convergence": ("ERC CCD가 고정 반복 한도 안에 수렴하지 않았습니다."),
    "constrained_erc_bisection_non_convergence": (
        "ERC outer bisection이 고정 반복 한도 안에 수렴하지 않았습니다."
    ),
    "constrained_erc_decimal_reconciliation_failure": (
        "ERC float weights를 exact Decimal 목표비중으로 대사하지 못했습니다."
    ),
    "constrained_erc_kkt_validation_failure": (
        "ERC 해가 feasibility·Euler·KKT 검증을 통과하지 못했습니다."
    ),
    "constrained_erc_duplicate_risk_snapshot": (
        "동일 signal date의 위험 snapshot이 중복되었습니다."
    ),
    "constrained_erc_missing_risk_snapshot": ("정확한 signal date의 위험 snapshot이 없습니다."),
    "constrained_erc_scenario_schedule_mismatch": (
        "covariance scenario와 shared signal 일정이 일치하지 않습니다."
    ),
    "constrained_erc_risk_snapshot_failure": ("동적 위험모형 snapshot을 생성하지 못했습니다."),
    "constrained_erc_self_financing_failure": (
        "자산배분 자기금융 회계 계산을 완료하지 못했습니다."
    ),
    "constrained_erc_not_run_common_failure": ("공통 입력 준비 실패로 정책을 실행하지 않았습니다."),
}


class ConstrainedErcTrialRegistry(Protocol):
    """Persistence contract for one immutable constrained-ERC trial."""

    def save(self, trial: ConstrainedErcResearchTrial) -> Path: ...


class JsonConstrainedErcTrialRegistry:
    """Store each trial once with the shared private atomic-write primitive."""

    def __init__(self, output_dir: Path, *, lock_timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.output_dir = Path(output_dir)
        self.lock_timeout = lock_timeout

    def save(self, trial: ConstrainedErcResearchTrial) -> Path:
        """Persist exact serialized bytes without overwriting an existing trial."""

        payload = serialize_constrained_erc_trial(trial)
        output_path = self.output_dir / f"constrained_erc_research_trial_{trial.trial_id}.json"
        try:
            return store_private_json_bytes(
                output_path,
                payload,
                lock_timeout=self.lock_timeout,
            )
        except PrivateJsonAlreadyExistsError:
            raise ConstrainedErcTrialAlreadyExistsError(
                f"기존 Constrained ERC trial을 덮어쓰지 않습니다: {output_path}"
            ) from None
        except PrivateJsonLockTimeoutError:
            raise ConstrainedErcTrialLockTimeoutError(
                "Constrained ERC trial 출력 파일 잠금 대기시간이 초과되었습니다."
            ) from None
        except PrivateJsonStorageError:
            raise ConstrainedErcTrialStorageError(
                f"Constrained ERC trial을 원자적으로 저장하지 못했습니다: {output_path}"
            ) from None


def fingerprint_constrained_erc_config(
    allocation_config: AllocationBacktestConfig,
    risk_model_config: DynamicRiskModelConfig,
    solver_config: ConstrainedErcSolverConfig,
) -> str:
    """Fingerprint schedule, costs, risk model, solver, and fixed policy order."""

    return _fingerprint(
        {
            "schema": CONSTRAINED_ERC_SCHEMA,
            "allocation_config": _allocation_config_payload(allocation_config),
            "risk_model_config": risk_model_config_payload(risk_model_config),
            "solver_config": _solver_config_payload(solver_config),
            "erc_contract": _erc_contract_payload(),
            "policy_order": list(CONSTRAINED_ERC_POLICY_ORDER),
        }
    )


def fingerprint_constrained_erc_market_data(
    stock_codes: tuple[str, ...],
    panel: AlignedPricePanel | None,
    matrix: AlignedReturnMatrix | None,
) -> str:
    """Fingerprint the ordered adjusted open/close panel and Decimal returns."""

    return _fingerprint(
        {
            "schema": CONSTRAINED_ERC_SCHEMA,
            "stock_codes": list(stock_codes),
            "price_panel": None if panel is None else _price_panel_payload(panel),
            "aligned_returns": None if matrix is None else _return_matrix_payload(matrix),
        }
    )


def fingerprint_constrained_erc_covariances(
    outcomes: tuple[ConstrainedErcRiskSnapshotOutcome, ...],
) -> str:
    """Fingerprint each exact signal-date scenario sequence without failure text."""

    return _fingerprint(
        {
            "schema": CONSTRAINED_ERC_SCHEMA,
            "risk_snapshot_outcomes": [
                _deterministic_risk_outcome_payload(outcome) for outcome in outcomes
            ],
        }
    )


def fingerprint_constrained_erc_trial(
    *,
    config_fingerprint: str,
    market_data_fingerprint: str,
    covariance_fingerprint: str,
    signal_dates: tuple[date, ...],
    execution_dates: tuple[date, ...],
    policy_outcomes: tuple[ConstrainedErcPolicyOutcome, ...],
    common_failure: ConstrainedErcCommonFailure | None = None,
) -> str:
    """Return rerun identity excluding UUID, time, path, and failure messages."""

    payload: dict[str, object] = {
        "schema": CONSTRAINED_ERC_SCHEMA,
        "config_sha256": config_fingerprint,
        "market_data_sha256": market_data_fingerprint,
        "covariance_sha256": covariance_fingerprint,
        "schedule": [
            {
                "signal_number": index,
                "signal_date": signal.isoformat(),
                "execution_date": execution.isoformat(),
            }
            for index, (signal, execution) in enumerate(
                zip(signal_dates, execution_dates, strict=True)
            )
        ],
        "policy_outcomes": [
            _deterministic_policy_outcome_payload(outcome) for outcome in policy_outcomes
        ],
    }
    if common_failure is not None:
        payload["common_failure"] = {
            "stage": common_failure.stage.value,
            "failure_code": safe_constrained_erc_failure_display(common_failure.failure)[0],
        }
    return _fingerprint(payload)


def serialize_constrained_erc_trial(trial: ConstrainedErcResearchTrial) -> bytes:
    """Serialize an explicit secret-free allow-list as deterministic private JSON."""

    if not isinstance(trial, ConstrainedErcResearchTrial):
        raise ConstrainedErcTrialSerializationError(
            "저장할 trial은 ConstrainedErcResearchTrial이어야 합니다."
        )
    _validate_trial_fingerprints(trial)
    payload = {
        "schema": trial.schema,
        "schema_version": trial.schema_version,
        "code_model_version": trial.code_model_version,
        "solver_version": trial.solver_config.solver_version,
        "trial_id": trial.trial_id,
        "status": trial.status.value,
        "executed_at": trial.executed_at.isoformat(),
        "requested_period": {
            "start": trial.requested_start.isoformat(),
            "end": trial.requested_end.isoformat(),
        },
        "actual_evaluation_period": (
            None
            if trial.actual_evaluation_start is None or trial.actual_evaluation_end is None
            else {
                "start": trial.actual_evaluation_start.isoformat(),
                "end": trial.actual_evaluation_end.isoformat(),
            }
        ),
        "research_scope": trial.research_scope,
        "stock_codes": list(trial.stock_codes),
        "aligned_market_data": (
            None if trial.price_panel is None else _price_panel_payload(trial.price_panel)
        ),
        "aligned_returns": (
            None if trial.aligned_returns is None else _return_matrix_payload(trial.aligned_returns)
        ),
        "config": {
            "allocation": _allocation_config_payload(trial.allocation_config),
            "risk_model": risk_model_config_payload(trial.risk_model_config),
            "solver": _solver_config_payload(trial.solver_config),
            "erc_contract": _erc_contract_payload(),
            "erc_per_asset_target_cap": _decimal_text(_PRODUCTION_ERC_UPPER_BOUND),
            "policy_order": list(CONSTRAINED_ERC_POLICY_ORDER),
        },
        "schedule": _schedule_payload(trial),
        "risk_snapshot_outcomes": [
            _risk_outcome_payload(outcome) for outcome in trial.risk_snapshot_outcomes
        ],
        "policy_outcomes": [_policy_outcome_payload(outcome) for outcome in trial.policy_outcomes],
        "fingerprints": {
            "config_sha256": trial.config_fingerprint,
            "market_data_sha256": trial.market_data_fingerprint,
            "covariance_sha256": trial.covariance_fingerprint,
            "trial_sha256": trial.trial_fingerprint,
        },
        "provenance": {
            "python_version": trial.provenance.python_version,
            "numpy_version": trial.provenance.numpy_version,
            "scikit_learn_version": trial.provenance.scikit_learn_version,
            "risk_model_version": trial.provenance.model_version,
            "risk_schema_version": trial.provenance.schema_version,
            "solver_version": trial.solver_config.solver_version,
        },
    }
    if trial.common_failure is not None:
        payload["common_failure"] = _common_failure_payload(trial.common_failure)
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ConstrainedErcTrialSerializationError(
            "Constrained ERC trial에 안전하게 직렬화할 수 없는 값이 있습니다."
        ) from None
    return f"{serialized}\n".encode()


def _validate_trial_fingerprints(trial: ConstrainedErcResearchTrial) -> None:
    expected_config = fingerprint_constrained_erc_config(
        trial.allocation_config,
        trial.risk_model_config,
        trial.solver_config,
    )
    expected_market = fingerprint_constrained_erc_market_data(
        trial.stock_codes,
        trial.price_panel,
        trial.aligned_returns,
    )
    expected_covariance = fingerprint_constrained_erc_covariances(trial.risk_snapshot_outcomes)
    expected_trial = fingerprint_constrained_erc_trial(
        config_fingerprint=expected_config,
        market_data_fingerprint=expected_market,
        covariance_fingerprint=expected_covariance,
        signal_dates=trial.signal_dates,
        execution_dates=trial.execution_dates,
        policy_outcomes=trial.policy_outcomes,
        common_failure=trial.common_failure,
    )
    if (
        trial.config_fingerprint != expected_config
        or trial.market_data_fingerprint != expected_market
        or trial.covariance_fingerprint != expected_covariance
        or trial.trial_fingerprint != expected_trial
    ):
        raise ConstrainedErcTrialSerializationError(
            "Constrained ERC trial fingerprint가 현재 canonical payload와 일치하지 않습니다."
        )


def _schedule_payload(trial: ConstrainedErcResearchTrial) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    matrix = trial.aligned_returns
    for signal_number, (signal_date, execution_date) in enumerate(
        zip(trial.signal_dates, trial.execution_dates, strict=True)
    ):
        training: dict[str, object] | None = None
        if matrix is not None:
            as_of_index = matrix.dates.index(signal_date)
            start_index = max(
                0,
                as_of_index + 1 - trial.allocation_config.maximum_training_returns,
            )
            training_dates = matrix.dates[start_index : as_of_index + 1]
            training = {
                "start": training_dates[0].isoformat(),
                "end": training_dates[-1].isoformat(),
                "observation_count": len(training_dates),
            }
        result.append(
            {
                "signal_number": signal_number,
                "signal_date": signal_date.isoformat(),
                "execution_date": execution_date.isoformat(),
                "training_period": training,
            }
        )
    return result


def _price_panel_payload(panel: AlignedPricePanel) -> dict[str, object]:
    return {
        "stock_codes": list(panel.stock_codes),
        "dates": [value.isoformat() for value in panel.dates],
        "adjusted_open_prices": [
            [_decimal_text(value) for value in row] for row in panel.open_prices
        ],
        "adjusted_close_prices": [
            [_decimal_text(value) for value in row] for row in panel.close_prices
        ],
        "missing_value_adjustment": "none",
    }


def _return_matrix_payload(matrix: AlignedReturnMatrix) -> dict[str, object]:
    return {
        "stock_codes": list(matrix.stock_codes),
        "dates": [value.isoformat() for value in matrix.dates],
        "values": [[_decimal_text(value) for value in row] for row in matrix.values],
    }


def _allocation_config_payload(config: AllocationBacktestConfig) -> dict[str, object]:
    return {
        "minimum_training_returns": config.minimum_training_returns,
        "maximum_training_returns": config.maximum_training_returns,
        "rebalance_interval": config.rebalance_interval,
        "target_equity_weight": _decimal_text(config.target_equity_weight),
        "buy_cost_rate": _decimal_text(config.buy_cost_rate),
        "sell_cost_rate": _decimal_text(config.sell_cost_rate),
        "annualization_trading_days": config.annualization_trading_days,
        "fractional_shares": True,
        "cash_interest_rate": "0",
        "execution_price": "next_common_adjusted_open",
    }


def _solver_config_payload(config: ConstrainedErcSolverConfig) -> dict[str, object]:
    return {
        "solver_version": config.solver_version,
        "weight_quantum": _decimal_text(config.weight_quantum),
        "coordinate_change_tolerance": _json_float(config.coordinate_change_tolerance),
        "normalized_kkt_tolerance": _json_float(config.normalized_kkt_tolerance),
        "outer_sum_tolerance": _json_float(config.outer_sum_tolerance),
        "maximum_ccd_sweeps": config.maximum_ccd_sweeps,
        "maximum_bisection_iterations": config.maximum_bisection_iterations,
        "maximum_bracket_expansions": config.maximum_bracket_expansions,
        "bracket_expansion_factor": _json_float(config.bracket_expansion_factor),
        "coordinate_order": "stock_registration_order",
        "covariance_ridge": False,
        "fallback_policy": None,
    }


def _erc_contract_payload() -> dict[str, object]:
    return {
        "risk_budgets": "equal_1_over_n",
        "long_only": True,
        "risky_weight_sum": "1",
        "lower_bound": "0",
        "per_asset_upper_bound": _decimal_text(_PRODUCTION_ERC_UPPER_BOUND),
        "strategic_cash_target": "0",
        "leverage": False,
        "short": False,
        "expected_return_input": False,
        "alpha_tilt": False,
        "risk_free_rate_input": False,
        "volatility_target": False,
        "turnover_constraint": False,
    }


def _risk_outcome_payload(outcome: ConstrainedErcRiskSnapshotOutcome) -> dict[str, object]:
    return {
        "as_of_date": outcome.as_of_date.isoformat(),
        "status": outcome.status.value,
        "snapshot": None if outcome.snapshot is None else _snapshot_payload(outcome.snapshot),
        "failure": None if outcome.failure is None else _failure_payload(outcome.failure),
    }


def _deterministic_risk_outcome_payload(
    outcome: ConstrainedErcRiskSnapshotOutcome,
) -> dict[str, object]:
    return {
        "as_of_date": outcome.as_of_date.isoformat(),
        "status": outcome.status.value,
        "snapshot": None if outcome.snapshot is None else _snapshot_payload(outcome.snapshot),
        "failure_code": None if outcome.failure is None else outcome.failure.code,
    }


def _snapshot_payload(snapshot: DynamicRiskModelSnapshot) -> dict[str, object]:
    return {
        "as_of_date": snapshot.as_of_date.isoformat(),
        "consumed_period": {
            "start": snapshot.consumed_start_date.isoformat(),
            "end": snapshot.consumed_end_date.isoformat(),
            "observation_count": snapshot.consumed_observation_count,
        },
        "stock_codes": list(snapshot.stock_codes),
        "consumed_dates": [value.isoformat() for value in snapshot.consumed_dates],
        "consumed_input_fingerprint": snapshot.consumed_input_fingerprint,
        "model_version": snapshot.model_version,
        "schema_version": snapshot.schema_version,
        "scenarios": [_scenario_payload(value) for value in snapshot.scenarios],
    }


def _scenario_payload(scenario: CovarianceScenario) -> dict[str, object]:
    return {
        "kind": scenario.kind.value,
        "stock_codes": list(scenario.stock_codes),
        "observation_dates": [value.isoformat() for value in scenario.observation_dates],
        "annualized_covariance": [
            [_json_float(value) for value in row] for row in scenario.annualized_covariance
        ],
        "annualized_volatilities": [
            _json_float(value) for value in scenario.annualized_volatilities
        ],
        "correlation_matrix": [
            [_json_float(value) for value in row] for row in scenario.correlation_matrix
        ],
        "metadata": _scenario_metadata_payload(scenario),
        "psd_diagnostics": _psd_payload(scenario.psd_diagnostics),
    }


def _scenario_metadata_payload(scenario: CovarianceScenario) -> dict[str, object]:
    metadata = scenario.metadata
    if isinstance(metadata, LedoitWolfMetadata):
        return {
            "type": "ledoit_wolf",
            "shrinkage": _json_float(metadata.shrinkage),
            "assume_centered": metadata.assume_centered,
            "store_precision": metadata.store_precision,
            "estimator": metadata.estimator,
            "moment_assumption": metadata.moment_assumption,
        }
    if isinstance(metadata, IewmaMetadata):
        return {
            "type": "iewma",
            "volatility_half_life": metadata.volatility_half_life,
            "correlation_half_life": metadata.correlation_half_life,
            "volatility_seed_count": metadata.volatility_seed_count,
            "correlation_observation_count": metadata.correlation_observation_count,
            "volatility_effective_sample_size": _json_float(
                metadata.volatility_effective_sample_size
            ),
            "correlation_effective_sample_size": _json_float(
                metadata.correlation_effective_sample_size
            ),
            "clip_threshold": _json_float(metadata.clip_threshold),
            "clipped_scalar_count": metadata.clipped_scalar_count,
            "correlation_psd_diagnostics": _psd_payload(metadata.correlation_psd_diagnostics),
            "forecast_horizon": metadata.forecast_horizon,
        }
    if isinstance(metadata, DownsideStressMetadata):
        return {
            "type": "downside_stress_ledoit_wolf",
            "downside_fraction": _decimal_text(metadata.downside_fraction),
            "selected_count": metadata.selected_count,
            "cutoff_equal_weight_return": _decimal_text(metadata.cutoff_equal_weight_return),
            "selected_dates": [value.isoformat() for value in metadata.selected_dates],
            "selected_dates_fingerprint": metadata.selected_dates_fingerprint,
            "shrinkage": _json_float(metadata.shrinkage),
            "assume_centered": metadata.assume_centered,
            "store_precision": metadata.store_precision,
            "estimator": metadata.estimator,
            "moment_assumption": metadata.moment_assumption,
        }
    raise ConstrainedErcTrialSerializationError("지원하지 않는 covariance metadata 타입입니다.")


def _psd_payload(value: PsdDiagnostics) -> dict[str, object]:
    return {
        "minimum_eigenvalue_before": _json_float(value.minimum_eigenvalue_before),
        "minimum_eigenvalue_after": _json_float(value.minimum_eigenvalue_after),
        "maximum_eigenvalue_after": _json_float(value.maximum_eigenvalue_after),
        "numerical_tolerance": _json_float(value.numerical_tolerance),
        "rank": value.rank,
        "condition_number": (
            None if value.condition_number is None else _json_float(value.condition_number)
        ),
        "frobenius_repair_norm": _json_float(value.frobenius_repair_norm),
        "relative_repair_norm": _json_float(value.relative_repair_norm),
        "repaired": value.repaired,
    }


def _policy_outcome_payload(outcome: ConstrainedErcPolicyOutcome) -> dict[str, object]:
    return {
        "policy_id": outcome.policy_id,
        "status": outcome.status.value,
        "erc_targets": [_erc_target_payload(value) for value in outcome.erc_targets],
        "result": None if outcome.result is None else _backtest_result_payload(outcome.result),
        "failure": None if outcome.failure is None else _failure_payload(outcome.failure),
    }


def _deterministic_policy_outcome_payload(
    outcome: ConstrainedErcPolicyOutcome,
) -> dict[str, object]:
    return {
        "policy_id": outcome.policy_id,
        "status": outcome.status.value,
        "erc_targets": [_erc_target_payload(value) for value in outcome.erc_targets],
        "result": None if outcome.result is None else _backtest_result_payload(outcome.result),
        "failure_code": None if outcome.failure is None else outcome.failure.code,
    }


def _erc_target_payload(target: ConstrainedErcTarget) -> dict[str, object]:
    return {
        "policy_id": target.policy_id,
        "scenario_kind": target.scenario_kind.value,
        "as_of_date": target.as_of_date.isoformat(),
        "stock_codes": list(target.stock_codes),
        "risk_budgets": [_decimal_text(value) for value in target.risk_budgets],
        "lower_bounds": [_decimal_text(value) for value in target.lower_bounds],
        "upper_bounds": [_decimal_text(value) for value in target.upper_bounds],
        "covariance_fingerprint": target.covariance_fingerprint,
        "lambda": _json_float(target.lambda_value),
        "raw_float_weights": [_json_float(value) for value in target.raw_float_weights],
        "reconciled_decimal_weights": [_decimal_text(value) for value in target.reconciled_weights],
        "diagnostics_before_reconciliation": _kkt_payload(target.diagnostics_before_reconciliation),
        "diagnostics_after_reconciliation": _kkt_payload(target.diagnostics_after_reconciliation),
        "reconciliation_max_error": _json_float(target.reconciliation_max_error),
        "weight_sum_residual_before": _json_float(target.weight_sum_residual_before),
        "weight_sum_residual_after": _decimal_text(target.weight_sum_residual_after),
        "ccd_sweeps": target.ccd_sweeps,
        "bisection_iterations": target.bisection_iterations,
        "bracket_expansions": target.bracket_expansions,
        "solver_config_fingerprint": target.solver_config_fingerprint,
        "solver_version": target.solver_version,
        "all_assets_bound_degeneracy": target.all_assets_bound_degeneracy,
    }


def _kkt_payload(value: object) -> dict[str, object]:
    from phalanx.domain import ConstrainedErcKktDiagnostics

    if not isinstance(value, ConstrainedErcKktDiagnostics):
        raise ConstrainedErcTrialSerializationError("ERC KKT diagnostics 타입이 올바르지 않습니다.")
    return {
        "weights": [_json_float(item) for item in value.weights],
        "portfolio_volatility": _json_float(value.portfolio_volatility),
        "marginal_risks": [_json_float(item) for item in value.marginal_risks],
        "absolute_risk_contributions": [
            _json_float(item) for item in value.absolute_risk_contributions
        ],
        "relative_risk_contributions": [
            _json_float(item) for item in value.relative_risk_contributions
        ],
        "bound_flags": [item.value for item in value.bound_flags],
        "primal_residual": _json_float(value.primal_residual),
        "euler_residual": _json_float(value.euler_residual),
        "normalized_max_kkt_residual": _json_float(value.normalized_max_kkt_residual),
        "complementarity_residual": _json_float(value.complementarity_residual),
        "free_asset_rc_dispersion": (
            None
            if value.free_asset_rc_dispersion is None
            else _json_float(value.free_asset_rc_dispersion)
        ),
    }


def _backtest_result_payload(result: AllocationBacktestResult) -> dict[str, object]:
    return {
        "policy_id": result.policy_id,
        "stock_codes": list(result.stock_codes),
        "dates": [value.isoformat() for value in result.dates],
        "net_asset_values": [_decimal_text(value) for value in result.net_asset_values],
        "realized_weights": [
            [_decimal_text(value) for value in row] for row in result.realized_weights
        ],
        "realized_cash_weights": [_decimal_text(value) for value in result.realized_cash_weights],
        "rebalances": [_rebalance_payload(value) for value in result.rebalances],
        "buy_gross_turnover": _decimal_text(result.buy_gross_turnover),
        "sell_gross_turnover": _decimal_text(result.sell_gross_turnover),
        "cumulative_transaction_cost": _decimal_text(result.cumulative_transaction_cost),
        "cumulative_cost_rate": _decimal_text(result.cumulative_cost_rate),
        "total_return": _decimal_text(result.total_return),
        "annualized_return": _decimal_text(result.annualized_return),
        "annualized_volatility": _decimal_text(result.annualized_volatility),
        "max_drawdown": _decimal_text(result.max_drawdown),
    }


def _rebalance_payload(record: AllocationRebalanceRecord) -> dict[str, object]:
    return {
        "target": _allocation_target_payload(record.target),
        "execution_date": record.execution_date.isoformat(),
        "realized_weights": [_decimal_text(value) for value in record.realized_weights],
        "realized_cash_weight": _decimal_text(record.realized_cash_weight),
        "buy_gross_turnover": _decimal_text(record.buy_gross_turnover),
        "sell_gross_turnover": _decimal_text(record.sell_gross_turnover),
        "transaction_cost": _decimal_text(record.transaction_cost),
        "transaction_cost_rate": _decimal_text(record.transaction_cost_rate),
        "pre_trade_nav": _decimal_text(record.pre_trade_nav),
        "post_trade_nav": _decimal_text(record.post_trade_nav),
        "cash_after": _decimal_text(record.cash_after),
    }


def _allocation_target_payload(target: AllocationTarget) -> dict[str, object]:
    return {
        "signal_date": target.signal_date.isoformat(),
        "stock_codes": list(target.stock_codes),
        "target_weights": [_decimal_text(value) for value in target.target_weights],
        "policy_id": target.policy_id,
        "target_equity_weight": _decimal_text(target.target_equity_weight),
    }


def _failure_payload(failure: ConstrainedErcFailure) -> dict[str, object]:
    code, message = safe_constrained_erc_failure_display(failure)
    return {
        "code": code,
        "message": message,
        "as_of_date": None if failure.as_of_date is None else failure.as_of_date.isoformat(),
        "scenario_kind": (None if failure.scenario_kind is None else failure.scenario_kind.value),
    }


def _common_failure_payload(value: ConstrainedErcCommonFailure) -> dict[str, object]:
    return {
        "stage": value.stage.value,
        "failure": _failure_payload(value.failure),
    }


def safe_constrained_erc_failure_display(
    failure: ConstrainedErcFailure,
) -> tuple[str, str]:
    """Project a domain failure to one stable secret-free code and reason."""

    code = failure.code if failure.code in _SAFE_FAILURE_MESSAGES else _GENERIC_FAILURE_CODE
    return code, _SAFE_FAILURE_MESSAGES[code]


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ConstrainedErcTrialSerializationError(
            "Constrained ERC JSON에는 유한한 Decimal만 저장할 수 있습니다."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _json_float(value: float) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ConstrainedErcTrialSerializationError(
            "Constrained ERC JSON에는 유한한 float만 저장할 수 있습니다."
        )
    return 0.0 if value == 0.0 else value


def _fingerprint(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ConstrainedErcTrialSerializationError(
            "Constrained ERC fingerprint 입력을 canonical JSON으로 만들 수 없습니다."
        ) from None
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConstrainedErcTrialRegistry",
    "JsonConstrainedErcTrialRegistry",
    "fingerprint_constrained_erc_config",
    "fingerprint_constrained_erc_covariances",
    "fingerprint_constrained_erc_market_data",
    "fingerprint_constrained_erc_trial",
    "safe_constrained_erc_failure_display",
    "serialize_constrained_erc_trial",
]

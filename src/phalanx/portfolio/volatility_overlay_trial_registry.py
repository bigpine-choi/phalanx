"""Canonical private registry for volatility-target overlay research trials."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from phalanx.domain import (
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    VOLATILITY_OVERLAY_SCHEMA,
    AllocationBacktestResult,
    AllocationRebalanceRecord,
    AllocationTarget,
    ConstrainedErcResearchTrial,
    VolatilityOverlayConfig,
    VolatilityOverlayFailure,
    VolatilityOverlayPolicyOutcome,
    VolatilityOverlayResearchTrial,
    VolatilityOverlayTarget,
)
from phalanx.portfolio.allocation_backtest import (
    annual_cash_yield_to_daily_growth_factor,
)
from phalanx.portfolio.constrained_erc_trial_registry import (
    serialize_constrained_erc_trial,
)
from phalanx.portfolio.errors import (
    ConstrainedErcTrialSerializationError,
    VolatilityOverlayTrialAlreadyExistsError,
    VolatilityOverlayTrialLockTimeoutError,
    VolatilityOverlayTrialSerializationError,
    VolatilityOverlayTrialStorageError,
)
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonLockTimeoutError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)

_LOCK_TIMEOUT_SECONDS = 10.0
_GENERIC_FAILURE_CODE = "volatility_overlay_calculation_error"
_SAFE_FAILURE_MESSAGES = {
    _GENERIC_FAILURE_CODE: "volatility overlay 정책 계산을 완료하지 못했습니다.",
    "volatility_overlay_source_common_failure": (
        "Constrained ERC 공통 입력 실패로 overlay를 실행하지 않았습니다."
    ),
    "volatility_overlay_source_erc_failure": (
        "해당 covariance scenario의 Constrained ERC가 실패하여 overlay를 실행하지 않았습니다."
    ),
    "volatility_overlay_invalid_forecast": (
        "양의 유한한 forecast 연환산변동성이 없어 overlay를 계산하지 못했습니다."
    ),
    "volatility_overlay_schedule_mismatch": (
        "overlay target과 source signal·next-open 일정이 일치하지 않습니다."
    ),
    "volatility_overlay_self_financing_failure": (
        "동적 주식·현금 자기금융 backtest를 완료하지 못했습니다."
    ),
}


class VolatilityOverlayTrialRegistry(Protocol):
    """Persistence contract for one immutable volatility-overlay trial."""

    def save(self, trial: VolatilityOverlayResearchTrial) -> Path: ...


class JsonVolatilityOverlayTrialRegistry:
    """Store each versioned overlay trial privately, atomically, and once."""

    def __init__(self, output_dir: Path, *, lock_timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.output_dir = Path(output_dir)
        self.lock_timeout = lock_timeout

    def save(self, trial: VolatilityOverlayResearchTrial) -> Path:
        """Persist exact canonical bytes without overwriting an existing trial."""

        payload = serialize_volatility_overlay_trial(trial)
        output_path = self.output_dir / (f"volatility_overlay_research_trial_{trial.trial_id}.json")
        try:
            return store_private_json_bytes(
                output_path,
                payload,
                lock_timeout=self.lock_timeout,
            )
        except PrivateJsonAlreadyExistsError:
            raise VolatilityOverlayTrialAlreadyExistsError(
                f"기존 volatility overlay trial을 덮어쓰지 않습니다: {output_path}"
            ) from None
        except PrivateJsonLockTimeoutError:
            raise VolatilityOverlayTrialLockTimeoutError(
                "volatility overlay trial 출력 파일 잠금 대기시간이 초과되었습니다."
            ) from None
        except PrivateJsonStorageError:
            raise VolatilityOverlayTrialStorageError(
                f"volatility overlay trial을 원자적으로 저장하지 못했습니다: {output_path}"
            ) from None


def fingerprint_volatility_overlay_config(
    source_trial: ConstrainedErcResearchTrial,
    overlay_config: VolatilityOverlayConfig,
) -> str:
    """Fingerprint required CLI inputs and the unchanged ERC source contract."""

    if not isinstance(source_trial, ConstrainedErcResearchTrial) or not isinstance(
        overlay_config, VolatilityOverlayConfig
    ):
        raise VolatilityOverlayTrialSerializationError(
            "overlay config fingerprint 입력 타입이 올바르지 않습니다."
        )
    return _fingerprint(
        {
            "schema": VOLATILITY_OVERLAY_SCHEMA,
            "source_constrained_erc": _source_reference_payload(source_trial),
            "overlay_config": _overlay_config_payload(
                overlay_config,
                source_trial.allocation_config.annualization_trading_days,
            ),
            "policy_order": list(VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS),
            "overlay_contract": _overlay_contract_payload(),
        }
    )


def fingerprint_volatility_overlay_trial(
    *,
    source_trial_fingerprint: str,
    config_fingerprint: str,
    signal_dates: tuple[date, ...],
    execution_dates: tuple[date, ...],
    policy_outcomes: tuple[VolatilityOverlayPolicyOutcome, ...],
) -> str:
    """Return rerun identity excluding UUID, time, path, and failure messages."""

    return _fingerprint(
        {
            "schema": VOLATILITY_OVERLAY_SCHEMA,
            "source_constrained_erc_trial_sha256": source_trial_fingerprint,
            "config_sha256": config_fingerprint,
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
    )


def serialize_volatility_overlay_trial(trial: VolatilityOverlayResearchTrial) -> bytes:
    """Serialize the separate v1 overlay schema with exact Decimal input text."""

    if not isinstance(trial, VolatilityOverlayResearchTrial):
        raise VolatilityOverlayTrialSerializationError(
            "저장할 trial은 VolatilityOverlayResearchTrial이어야 합니다."
        )
    _validate_trial_fingerprints(trial)
    try:
        source_payload = json.loads(serialize_constrained_erc_trial(trial.source_trial))
    except (
        ConstrainedErcTrialSerializationError,
        json.JSONDecodeError,
        UnicodeError,
        TypeError,
    ):
        raise VolatilityOverlayTrialSerializationError(
            "source Constrained ERC trial을 안전하게 중첩 직렬화하지 못했습니다."
        ) from None
    payload = {
        "schema": trial.schema,
        "schema_version": trial.schema_version,
        "code_model_version": trial.code_model_version,
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
        "config": {
            "overlay": _overlay_config_payload(
                trial.overlay_config,
                trial.source_trial.allocation_config.annualization_trading_days,
            ),
            "overlay_contract": _overlay_contract_payload(),
            "policy_order": list(VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS),
        },
        "schedule": [
            {
                "signal_number": index,
                "signal_date": signal.isoformat(),
                "execution_date": execution.isoformat(),
            }
            for index, (signal, execution) in enumerate(
                zip(trial.signal_dates, trial.execution_dates, strict=True)
            )
        ],
        "source_constrained_erc_trial": source_payload,
        "policy_outcomes": [_policy_outcome_payload(outcome) for outcome in trial.policy_outcomes],
        "fingerprints": {
            "config_sha256": trial.config_fingerprint,
            "source_constrained_erc_config_sha256": (trial.source_trial.config_fingerprint),
            "source_constrained_erc_market_data_sha256": (
                trial.source_trial.market_data_fingerprint
            ),
            "source_constrained_erc_covariance_sha256": (trial.source_trial.covariance_fingerprint),
            "source_constrained_erc_trial_sha256": (trial.source_trial.trial_fingerprint),
            "trial_sha256": trial.trial_fingerprint,
        },
        "provenance": {
            "python_version": trial.provenance.python_version,
            "numpy_version": trial.provenance.numpy_version,
            "scikit_learn_version": trial.provenance.scikit_learn_version,
            "risk_model_version": trial.provenance.model_version,
            "risk_schema_version": trial.provenance.schema_version,
            "source_erc_solver_version": trial.source_trial.solver_config.solver_version,
            "overlay_code_model_version": trial.code_model_version,
        },
    }
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise VolatilityOverlayTrialSerializationError(
            "volatility overlay trial에 안전하게 직렬화할 수 없는 값이 있습니다."
        ) from None
    return f"{serialized}\n".encode()


def _validate_trial_fingerprints(trial: VolatilityOverlayResearchTrial) -> None:
    expected_config = fingerprint_volatility_overlay_config(
        trial.source_trial,
        trial.overlay_config,
    )
    expected_trial = fingerprint_volatility_overlay_trial(
        source_trial_fingerprint=trial.source_trial.trial_fingerprint,
        config_fingerprint=expected_config,
        signal_dates=trial.signal_dates,
        execution_dates=trial.execution_dates,
        policy_outcomes=trial.policy_outcomes,
    )
    if trial.config_fingerprint != expected_config or trial.trial_fingerprint != expected_trial:
        raise VolatilityOverlayTrialSerializationError(
            "volatility overlay trial fingerprint가 canonical payload와 일치하지 않습니다."
        )


def _overlay_config_payload(
    config: VolatilityOverlayConfig,
    annualization_trading_days: int,
) -> dict[str, object]:
    daily_factor = annual_cash_yield_to_daily_growth_factor(
        config.annual_cash_yield,
        annualization_trading_days,
    )
    return {
        "target_annual_volatility": _decimal_text(config.target_annual_volatility),
        "annual_cash_yield": _decimal_text(config.annual_cash_yield),
        "annualization_trading_days": annualization_trading_days,
        "daily_cash_growth_factor": _decimal_text(daily_factor),
        "cash_compounding": "daily_on_common_trading_days",
        "cash_accrual_timing": ("after_first_execution_once_before_each_subsequent_common_open"),
        "code_model_version": config.code_model_version,
    }


def _overlay_contract_payload() -> dict[str, object]:
    return {
        "risky_sleeve": "unchanged_constrained_erc_reconciled_weights",
        "scalar_formula": "min(1,target_annual_volatility/forecast_annual_volatility)",
        "final_asset_weight_formula": "scalar*erc_risky_sleeve_weight",
        "cash_residual_formula": "1-sum(final_asset_weights)",
        "long_only": True,
        "leverage": False,
        "short": False,
        "source_per_asset_target_cap": "0.2",
        "fallback_policy": None,
        "automatic_winner_selection": False,
        "risk_free_rate_input": False,
        "sharpe_hurdle_input": False,
        "cash_yield_is_risk_free_rate": False,
        "fractional_shares": True,
        "execution_price": "next_common_adjusted_open",
    }


def _source_reference_payload(trial: ConstrainedErcResearchTrial) -> dict[str, object]:
    return {
        "schema": trial.schema,
        "schema_version": trial.schema_version,
        "code_model_version": trial.code_model_version,
        "solver_version": trial.solver_config.solver_version,
        "config_sha256": trial.config_fingerprint,
        "market_data_sha256": trial.market_data_fingerprint,
        "covariance_sha256": trial.covariance_fingerprint,
        "trial_sha256": trial.trial_fingerprint,
    }


def _policy_outcome_payload(outcome: VolatilityOverlayPolicyOutcome) -> dict[str, object]:
    return {
        "policy_id": outcome.policy_id,
        "status": outcome.status.value,
        "overlay_targets": [_overlay_target_payload(target) for target in outcome.overlay_targets],
        "result": None if outcome.result is None else _backtest_result_payload(outcome.result),
        "failure": None if outcome.failure is None else _failure_payload(outcome.failure),
    }


def _deterministic_policy_outcome_payload(
    outcome: VolatilityOverlayPolicyOutcome,
) -> dict[str, object]:
    return {
        "policy_id": outcome.policy_id,
        "status": outcome.status.value,
        "overlay_targets": [_overlay_target_payload(target) for target in outcome.overlay_targets],
        "result": None if outcome.result is None else _backtest_result_payload(outcome.result),
        "failure_code": None if outcome.failure is None else outcome.failure.code,
    }


def _overlay_target_payload(target: VolatilityOverlayTarget) -> dict[str, object]:
    return {
        "scenario_kind": target.scenario_kind.value,
        "source_policy_id": target.source_policy_id,
        "policy_id": target.policy_id,
        "as_of_date": target.as_of_date.isoformat(),
        "stock_codes": list(target.stock_codes),
        "source_covariance_fingerprint": target.source_covariance_fingerprint,
        "source_solver_config_fingerprint": target.source_solver_config_fingerprint,
        "forecast_annual_volatility": _decimal_text(target.forecast_annual_volatility),
        "target_annual_volatility": _decimal_text(target.target_annual_volatility),
        "scalar": _decimal_text(target.scalar),
        "risky_sleeve_weights": [_decimal_text(value) for value in target.risky_sleeve_weights],
        "target_weights": [_decimal_text(value) for value in target.target_weights],
        "target_equity_weight": _decimal_text(target.target_equity_weight),
        "cash_residual": _decimal_text(target.cash_residual),
        "annual_cash_yield": _decimal_text(target.annual_cash_yield),
        "code_model_version": target.code_model_version,
        "schema_version": target.schema_version,
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
        "rebalances": [_rebalance_payload(record) for record in result.rebalances],
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


def _failure_payload(failure: VolatilityOverlayFailure) -> dict[str, object]:
    code, message = safe_volatility_overlay_failure_display(failure)
    return {
        "code": code,
        "message": message,
        "as_of_date": (None if failure.as_of_date is None else failure.as_of_date.isoformat()),
        "scenario_kind": (None if failure.scenario_kind is None else failure.scenario_kind.value),
    }


def safe_volatility_overlay_failure_display(
    failure: VolatilityOverlayFailure,
) -> tuple[str, str]:
    """Project any failure object to a fixed secret-free code and message."""

    code = failure.code if failure.code in _SAFE_FAILURE_MESSAGES else _GENERIC_FAILURE_CODE
    return code, _SAFE_FAILURE_MESSAGES[code]


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise VolatilityOverlayTrialSerializationError(
            "volatility overlay JSON에는 유한한 Decimal만 저장할 수 있습니다."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _fingerprint(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError):
        raise VolatilityOverlayTrialSerializationError(
            "volatility overlay fingerprint 입력을 canonical JSON으로 만들 수 없습니다."
        ) from None
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "JsonVolatilityOverlayTrialRegistry",
    "VolatilityOverlayTrialRegistry",
    "fingerprint_volatility_overlay_config",
    "fingerprint_volatility_overlay_trial",
    "safe_volatility_overlay_failure_display",
    "serialize_volatility_overlay_trial",
]

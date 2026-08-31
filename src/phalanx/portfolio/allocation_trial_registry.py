"""Canonical fingerprints and private atomic JSON storage for allocation trials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from phalanx.domain import (
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationPolicyOutcome,
    AllocationPolicyOutcomeStatus,
    AllocationRebalanceRecord,
    AllocationResearchTrial,
    AllocationTarget,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_policies import AllocationPolicy
from phalanx.portfolio.errors import (
    AllocationTrialAlreadyExistsError,
    AllocationTrialLockTimeoutError,
    AllocationTrialStorageError,
    InvalidAllocationResearchTrialError,
)
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonDirectoryError,
    PrivateJsonLockError,
    PrivateJsonLockTimeoutError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)

_SCHEMA_VERSION = "1"
_LOCK_TIMEOUT_SECONDS = 10.0
_SAFE_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_FAILURE_CODES = frozenset(
    {
        "allocation_data_error",
        "allocation_policy_error",
        "allocation_self_financing",
        "allocation_zero_volatility",
        "insufficient_allocation_observations",
        "invalid_allocation_target",
        "unexpected_calculation_error",
        "unexpected_policy_error",
    }
)
_GENERIC_FAILURE_CODE = "allocation_policy_error"
_GENERIC_FAILURE_MESSAGE = "정책 계산을 완료하지 못했습니다."


class AllocationTrialRegistry(Protocol):
    """Persistence contract for one immutable allocation research trial."""

    def save(self, trial: AllocationResearchTrial) -> Path: ...


def fingerprint_allocation_config(config: AllocationBacktestConfig) -> str:
    """Return a deterministic SHA-256 over research configuration only."""

    if not isinstance(config, AllocationBacktestConfig):
        raise InvalidAllocationResearchTrialError(
            "설정 fingerprint 입력은 AllocationBacktestConfig여야 합니다."
        )
    return _fingerprint(
        {
            "schema_version": _SCHEMA_VERSION,
            "config": _config_payload(config),
        }
    )


def fingerprint_allocation_policies(
    policies: Sequence[AllocationPolicy],
    code_model_version: str,
) -> str:
    """Fingerprint the ordered policy identities, versions, and code model."""

    if not isinstance(code_model_version, str) or not code_model_version.strip():
        raise InvalidAllocationResearchTrialError(
            "정책 fingerprint의 코드 모델 버전은 비어 있을 수 없습니다."
        )
    if not policies:
        raise InvalidAllocationResearchTrialError(
            "정책 fingerprint에는 최소 1개의 정책이 필요합니다."
        )

    policy_payloads: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for policy in policies:
        policy_id = policy.policy_id
        policy_version = policy.policy_version
        if (
            not isinstance(policy_id, str)
            or not policy_id.strip()
            or policy_id != policy_id.strip()
            or len(policy_id) > 128
        ):
            raise InvalidAllocationResearchTrialError(
                "정책 fingerprint의 정책 식별자가 올바르지 않습니다."
            )
        if policy_id in seen_ids:
            raise InvalidAllocationResearchTrialError(
                "정책 fingerprint에 중복 정책 식별자가 있습니다."
            )
        if (
            not isinstance(policy_version, str)
            or not policy_version.strip()
            or policy_version != policy_version.strip()
            or len(policy_version) > 128
        ):
            raise InvalidAllocationResearchTrialError(
                "정책 fingerprint의 정책 버전이 올바르지 않습니다."
            )
        seen_ids.add(policy_id)
        policy_payloads.append(
            {
                "policy_id": policy_id,
                "policy_version": policy_version,
            }
        )

    return _fingerprint(
        {
            "schema_version": _SCHEMA_VERSION,
            "code_model_version": code_model_version,
            "policies": policy_payloads,
        }
    )


def fingerprint_market_data(histories: Sequence[StockDailyBars]) -> str:
    """Fingerprint ordered, adjusted OHLCV histories without persisting them."""

    history_payloads: list[dict[str, object]] = []
    for history in histories:
        if not isinstance(history, StockDailyBars):
            raise InvalidAllocationResearchTrialError(
                "시장데이터 fingerprint 입력은 StockDailyBars여야 합니다."
            )
        stock_code = history.stock.stock_code
        if not isinstance(history.bars, tuple):
            raise InvalidAllocationResearchTrialError(
                "시장데이터 fingerprint의 일별 시세는 tuple이어야 합니다."
            )
        history_payloads.append(
            {
                "stock_code": stock_code,
                "bars": [
                    {
                        "stock_code": bar.stock_code,
                        "trade_date": bar.trade_date.isoformat(),
                        "open_price": _decimal_text(bar.open_price),
                        "high_price": _decimal_text(bar.high_price),
                        "low_price": _decimal_text(bar.low_price),
                        "close_price": _decimal_text(bar.close_price),
                        "volume": bar.volume,
                    }
                    for bar in history.bars
                ],
            }
        )
    return _fingerprint(
        {
            "schema_version": _SCHEMA_VERSION,
            "histories": history_payloads,
        }
    )


def serialize_allocation_trial(trial: AllocationResearchTrial) -> bytes:
    """Serialize only explicitly allow-listed trial fields as private JSON bytes."""

    if not isinstance(trial, AllocationResearchTrial):
        raise AllocationTrialStorageError("저장할 trial은 AllocationResearchTrial이어야 합니다.")
    payload = {
        "schema_version": _SCHEMA_VERSION,
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
        "stock_codes": list(trial.stock_codes),
        "config": _config_payload(trial.config),
        "fingerprints": {
            "policy_sha256": trial.policy_fingerprint,
            "config_sha256": trial.config_fingerprint,
            "market_data_sha256": trial.market_data_fingerprint,
        },
        "policy_outcomes": [_policy_outcome_payload(outcome) for outcome in trial.policy_outcomes],
        "code_model_version": trial.code_model_version,
        "research_scope": trial.research_scope,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    return f"{serialized}\n".encode()


class JsonAllocationTrialRegistry:
    """Store each allocation trial once under a trial-specific file lock."""

    def __init__(
        self,
        output_dir: Path,
        *,
        lock_timeout: float = _LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.lock_timeout = lock_timeout

    def save(self, trial: AllocationResearchTrial) -> Path:
        """Atomically save one private JSON trial without overwriting a target."""

        payload = serialize_allocation_trial(trial)
        output_path = self.output_dir / f"allocation_research_trial_{trial.trial_id}.json"
        try:
            return store_private_json_bytes(
                output_path,
                payload,
                lock_timeout=self.lock_timeout,
                path_exists=_path_exists,
                link=os.link,
                token_hex=secrets.token_hex,
                write_all=_write_all,
                fsync_directory=_fsync_directory,
            )
        except PrivateJsonAlreadyExistsError:
            raise AllocationTrialAlreadyExistsError(
                f"기존 자산배분 trial을 덮어쓰지 않습니다: {output_path}"
            ) from None
        except PrivateJsonLockTimeoutError:
            raise AllocationTrialLockTimeoutError(
                "자산배분 trial 출력 파일 잠금 대기시간이 초과되었습니다."
            ) from None
        except PrivateJsonDirectoryError:
            raise AllocationTrialStorageError(
                "자산배분 trial 출력 디렉터리를 만들 수 없습니다."
            ) from None
        except PrivateJsonLockError:
            raise AllocationTrialStorageError(
                "자산배분 trial 출력 파일 잠금을 안전하게 사용할 수 없습니다."
            ) from None
        except PrivateJsonStorageError:
            raise AllocationTrialStorageError(
                f"자산배분 trial을 원자적으로 저장하지 못했습니다: {output_path}"
            ) from None


def _config_payload(config: AllocationBacktestConfig) -> dict[str, object]:
    return {
        "minimum_training_returns": config.minimum_training_returns,
        "maximum_training_returns": config.maximum_training_returns,
        "rebalance_interval": config.rebalance_interval,
        "target_equity_weight": _decimal_text(config.target_equity_weight),
        "buy_cost_rate": _decimal_text(config.buy_cost_rate),
        "sell_cost_rate": _decimal_text(config.sell_cost_rate),
        "annualization_trading_days": config.annualization_trading_days,
    }


def _policy_outcome_payload(outcome: AllocationPolicyOutcome) -> dict[str, object]:
    if outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED:
        if outcome.result is None:
            raise AllocationTrialStorageError("성공 정책 결과에 backtest 결과가 없습니다.")
        return {
            "policy_id": outcome.policy_id,
            "status": outcome.status.value,
            "result": _backtest_result_payload(outcome.result),
            "failure": None,
        }
    if outcome.failure is None:
        raise AllocationTrialStorageError("실패 정책 결과에 실패 정보가 없습니다.")
    return {
        "policy_id": outcome.policy_id,
        "status": outcome.status.value,
        "result": None,
        "failure": {
            "code": _safe_failure_code(outcome.failure.code),
            "message": _GENERIC_FAILURE_MESSAGE,
        },
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
        "target": _target_payload(record.target),
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


def _target_payload(target: AllocationTarget) -> dict[str, object]:
    return {
        "signal_date": target.signal_date.isoformat(),
        "stock_codes": list(target.stock_codes),
        "target_weights": [_decimal_text(value) for value in target.target_weights],
        "policy_id": target.policy_id,
        "target_equity_weight": _decimal_text(target.target_equity_weight),
    }


def _safe_failure_code(value: str) -> str:
    if _SAFE_FAILURE_CODE_PATTERN.fullmatch(value) is None:
        return _GENERIC_FAILURE_CODE
    return value if value in _SAFE_FAILURE_CODES else _GENERIC_FAILURE_CODE


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("allocation trial write made no progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "AllocationTrialRegistry",
    "JsonAllocationTrialRegistry",
    "fingerprint_allocation_config",
    "fingerprint_allocation_policies",
    "fingerprint_market_data",
    "serialize_allocation_trial",
]

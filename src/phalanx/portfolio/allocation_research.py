"""Orchestrate comparable allocation policies over one immutable market-data input."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from phalanx.domain import (
    AllocationBacktestConfig,
    AllocationPolicyFailure,
    AllocationPolicyOutcome,
    AllocationPolicyOutcomeStatus,
    AllocationResearchTrial,
    AllocationTrialStatus,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_backtest import run_allocation_backtest
from phalanx.portfolio.allocation_data import build_aligned_price_panel
from phalanx.portfolio.allocation_policies import (
    AllocationPolicy,
    default_allocation_policies,
)
from phalanx.portfolio.allocation_trial_registry import (
    fingerprint_allocation_config,
    fingerprint_allocation_policies,
    fingerprint_market_data,
)
from phalanx.portfolio.errors import AllocationResearchError

ALLOCATION_CODE_MODEL_VERSION = "allocation-research-v1"


def conduct_allocation_research(
    histories: Sequence[StockDailyBars],
    requested_start: date,
    requested_end: date,
    *,
    config: AllocationBacktestConfig | None = None,
    policies: tuple[AllocationPolicy, ...] | None = None,
    trial_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AllocationResearchTrial:
    """Run every policy independently and retain sanitized failures in one trial."""

    selected_config = AllocationBacktestConfig() if config is None else config
    selected_policies = default_allocation_policies() if policies is None else policies
    if not selected_policies:
        raise AllocationResearchError("자산배분 연구에는 최소 1개의 정책이 필요합니다.")
    policy_ids = tuple(policy.policy_id for policy in selected_policies)
    if len(set(policy_ids)) != len(policy_ids):
        raise AllocationResearchError("자산배분 연구 정책 식별자에 중복이 있습니다.")

    trial_id = uuid4().hex if trial_id_factory is None else trial_id_factory()
    executed_at = datetime.now(UTC) if clock is None else clock()
    histories_tuple = tuple(histories)
    stock_codes = _unique_stock_codes(histories_tuple)
    config_fingerprint = fingerprint_allocation_config(selected_config)
    policy_fingerprint = fingerprint_allocation_policies(
        selected_policies,
        ALLOCATION_CODE_MODEL_VERSION,
    )
    data_fingerprint = fingerprint_market_data(histories_tuple)

    try:
        panel = build_aligned_price_panel(
            histories_tuple,
            minimum_common_observations=selected_config.minimum_training_returns + 2,
        )
    except Exception as error:
        failure = _safe_failure(error, data_level=True)
        outcomes = tuple(
            AllocationPolicyOutcome(
                policy_id=policy.policy_id,
                status=AllocationPolicyOutcomeStatus.FAILED,
                failure=failure,
            )
            for policy in selected_policies
        )
        return AllocationResearchTrial(
            trial_id=trial_id,
            status=AllocationTrialStatus.FAILED,
            executed_at=executed_at,
            requested_start=requested_start,
            requested_end=requested_end,
            actual_evaluation_start=None,
            actual_evaluation_end=None,
            stock_codes=stock_codes,
            config=selected_config,
            policy_fingerprint=policy_fingerprint,
            config_fingerprint=config_fingerprint,
            market_data_fingerprint=data_fingerprint,
            policy_outcomes=outcomes,
            code_model_version=ALLOCATION_CODE_MODEL_VERSION,
        )

    outcomes_list: list[AllocationPolicyOutcome] = []
    for policy in selected_policies:
        try:
            result = run_allocation_backtest(panel, policy, selected_config)
            outcomes_list.append(
                AllocationPolicyOutcome(
                    policy_id=policy.policy_id,
                    status=AllocationPolicyOutcomeStatus.SUCCEEDED,
                    result=result,
                )
            )
        except Exception as error:
            outcomes_list.append(
                AllocationPolicyOutcome(
                    policy_id=policy.policy_id,
                    status=AllocationPolicyOutcomeStatus.FAILED,
                    failure=_safe_failure(error, data_level=False),
                )
            )

    outcomes = _enforce_shared_evaluation_period(
        tuple(outcomes_list),
        panel.dates[selected_config.minimum_training_returns + 1 :],
    )
    successes = tuple(
        outcome.result
        for outcome in outcomes
        if outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED and outcome.result is not None
    )
    status = (
        AllocationTrialStatus.SUCCEEDED
        if len(successes) == len(outcomes)
        else AllocationTrialStatus.FAILED
        if not successes
        else AllocationTrialStatus.PARTIAL_FAILURE
    )
    actual_start = successes[0].dates[0] if successes else None
    actual_end = successes[0].dates[-1] if successes else None
    return AllocationResearchTrial(
        trial_id=trial_id,
        status=status,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        actual_evaluation_start=actual_start,
        actual_evaluation_end=actual_end,
        stock_codes=panel.stock_codes,
        config=selected_config,
        policy_fingerprint=policy_fingerprint,
        config_fingerprint=config_fingerprint,
        market_data_fingerprint=data_fingerprint,
        policy_outcomes=outcomes,
        code_model_version=ALLOCATION_CODE_MODEL_VERSION,
    )


def _unique_stock_codes(histories: tuple[StockDailyBars, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for history in histories:
        stock_code = history.stock.stock_code
        if stock_code not in seen:
            seen.add(stock_code)
            result.append(stock_code)
    return tuple(result)


def _safe_failure(error: Exception, *, data_level: bool) -> AllocationPolicyFailure:
    if isinstance(error, AllocationResearchError):
        code = "allocation_data_error" if data_level else "allocation_policy_error"
    else:
        code = "unexpected_calculation_error"
    message = (
        "자산배분 공통 가격 데이터를 구성하지 못했습니다."
        if data_level
        else "자산배분 정책 계산을 완료하지 못했습니다."
    )
    return AllocationPolicyFailure(code=code, message=message)


def _enforce_shared_evaluation_period(
    outcomes: tuple[AllocationPolicyOutcome, ...],
    expected_dates: tuple[date, ...],
) -> tuple[AllocationPolicyOutcome, ...]:
    normalized: list[AllocationPolicyOutcome] = []
    for outcome in outcomes:
        if (
            outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED
            and outcome.result is not None
            and outcome.result.dates != expected_dates
        ):
            normalized.append(
                AllocationPolicyOutcome(
                    policy_id=outcome.policy_id,
                    status=AllocationPolicyOutcomeStatus.FAILED,
                    failure=AllocationPolicyFailure(
                        code="allocation_policy_error",
                        message="정책 실제 평가기간이 공통 비교기간과 일치하지 않습니다.",
                    ),
                )
            )
        else:
            normalized.append(outcome)
    return tuple(normalized)


__all__ = ["ALLOCATION_CODE_MODEL_VERSION", "conduct_allocation_research"]

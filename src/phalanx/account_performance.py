"""Offline whole-account performance from two observations and an explicit ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, localcontext

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.account import AccountSnapshot
from phalanx.domain.account_performance import (
    AccountPerformance,
    AccountPerformanceAssumptions,
    CashFlowLedger,
    WeightedCashFlow,
)


class AccountPerformanceError(RuntimeError):
    """An input pair or numerical range cannot support this offline calculation."""


def account_performance_decimal_context() -> Context:
    """Return a fresh context independent of process-global Decimal settings."""

    return financial_decimal_context()


def _utc_microseconds_between(start: datetime, end: datetime) -> int:
    difference = end.astimezone(UTC) - start.astimezone(UTC)
    return (
        difference.days * 86400 * 1_000_000
        + difference.seconds * 1_000_000
        + difference.microseconds
    )


def _validate_inputs(
    start: AccountSnapshot, end: AccountSnapshot, cash_flows: CashFlowLedger
) -> None:
    for field in ("provider", "currency", "account_number_masked"):
        if getattr(start, field) != getattr(end, field):
            raise AccountPerformanceError(
                "두 스냅샷의 provider, currency, account_number_masked가 일치해야 합니다."
            )
    if start.evidence.summary_consistency_warnings or end.evidence.summary_consistency_warnings:
        raise AccountPerformanceError(
            "summary_consistency_warnings가 있는 스냅샷은 기간 성과 계산에 사용할 수 없습니다."
        )
    start_begin = start.query_started_at.astimezone(UTC)
    start_end = start.query_completed_at.astimezone(UTC)
    end_begin = end.query_started_at.astimezone(UTC)
    end_end = end.query_completed_at.astimezone(UTC)
    if start_begin > start_end or end_begin > end_end:
        raise AccountPerformanceError("스냅샷 조회 시작시각이 완료시각보다 늦습니다.")
    if start_end >= end_end:
        raise AccountPerformanceError("시작 관측시각은 종료 관측시각보다 빨라야 합니다.")
    if start_end >= end_begin:
        raise AccountPerformanceError("두 스냅샷 조회구간이 겹치거나 경계가 맞닿아 있습니다.")
    if (
        cash_flows.coverage_start.astimezone(UTC) != start_end
        or cash_flows.coverage_end.astimezone(UTC) != end_end
    ):
        raise AccountPerformanceError(
            "원장의 coverage_start/end는 분석 관측시각과 일치해야 합니다."
        )
    for event in cash_flows.events:
        instant = event.occurred_at.astimezone(UTC)
        if start_begin <= instant <= start_end or end_begin <= instant <= end_end:
            raise AccountPerformanceError(
                "스냅샷 조회 시작~완료 구간 또는 경계의 입출금은 "
                "순자산(NAV) 반영 여부가 모호하여 지원하지 않습니다."
            )
        if not start_end < instant < end_end:
            raise AccountPerformanceError("외부 입출금은 두 관측시각 사이에 있어야 합니다.")


def calculate_account_performance(
    start: AccountSnapshot, end: AccountSnapshot, cash_flows: CashFlowLedger
) -> AccountPerformance:
    """Estimate Modified Dietz using stored net assets, without prices or network access."""

    try:
        _validate_inputs(start, end, cash_flows)
        with localcontext(account_performance_decimal_context()):
            return _calculate(start, end, cash_flows)
    except OverflowError:
        raise AccountPerformanceError(
            "스냅샷 시각이 UTC로 변환 가능한 날짜 범위를 벗어났습니다."
        ) from None
    except DecimalException:
        raise AccountPerformanceError(
            "입력 금액 또는 계산 결과가 고정 Decimal context의 지원 범위를 벗어났습니다."
        ) from None


def _calculate(
    start: AccountSnapshot, end: AccountSnapshot, cash_flows: CashFlowLedger
) -> AccountPerformance:
    beginning = start.summary.net_assets
    ending = end.summary.net_assets
    period = _utc_microseconds_between(start.query_completed_at, end.query_completed_at)
    weighted_flows: list[WeightedCashFlow] = []
    total_deposits = Decimal(0)
    total_withdrawals = Decimal(0)
    net_cash_flow = Decimal(0)
    weighted_total = Decimal(0)
    for event in sorted(
        cash_flows.events, key=lambda item: (item.occurred_at.astimezone(UTC), item.event_id)
    ):
        remaining = _utc_microseconds_between(event.occurred_at, end.query_completed_at)
        weight = Decimal(remaining) / Decimal(period)
        weighted_amount = weight * event.amount
        weighted_flows.append(
            WeightedCashFlow(
                event_id=event.event_id,
                occurred_at=event.occurred_at.astimezone(UTC),
                amount=event.amount,
                remaining_microseconds=remaining,
                weight=weight,
                weighted_amount=weighted_amount,
            )
        )
        if event.amount > 0:
            total_deposits += event.amount
        else:
            total_withdrawals -= event.amount
        net_cash_flow += event.amount
        weighted_total += weighted_amount
    profit_loss = ending - beginning - net_cash_flow
    average_invested_capital = beginning + weighted_total
    unavailable_reasons: list[str] = []
    if beginning <= 0:
        unavailable_reasons.append("기초 순자산이 0 이하이므로 수익률을 산출하지 않습니다.")
    if average_invested_capital <= 0:
        unavailable_reasons.append("평균투하자본이 0 이하이므로 수익률을 산출하지 않습니다.")
    estimated_return = None if unavailable_reasons else profit_loss / average_invested_capital
    return AccountPerformance(
        provider=start.provider,
        currency=start.currency,
        account_number_masked=start.account_number_masked,
        start_observed_at=start.query_completed_at.astimezone(UTC),
        end_observed_at=end.query_completed_at.astimezone(UTC),
        start_query_started_at=start.query_started_at.astimezone(UTC),
        end_query_started_at=end.query_started_at.astimezone(UTC),
        beginning_net_assets=beginning,
        ending_net_assets=ending,
        total_deposits=total_deposits,
        total_withdrawals=total_withdrawals,
        net_cash_flow=net_cash_flow,
        profit_loss=profit_loss,
        average_invested_capital=average_invested_capital,
        estimated_return=estimated_return,
        return_unavailable_reasons=tuple(unavailable_reasons),
        weighted_cash_flows=tuple(weighted_flows),
        period_microseconds=period,
        assumptions=AccountPerformanceAssumptions(
            ledger_schema_version=cash_flows.schema_version,
            coverage_start=cash_flows.coverage_start.astimezone(UTC),
            coverage_end=cash_flows.coverage_end.astimezone(UTC),
            same_account_confirmed=cash_flows.same_account_confirmed,
            external_flows_complete=cash_flows.external_flows_complete,
            no_in_kind_transfers=cash_flows.no_in_kind_transfers,
        ),
    )

"""Pure account-overview validation and calculation, independent of any UI or I/O."""

from __future__ import annotations

from datetime import UTC, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)

from pydantic import ValidationError

from phalanx.domain import AccountSnapshot, AccountSummary, CurrentPriceMarket, ValuationPriceBundle
from phalanx.domain.account_overview import AccountOverview, OverviewPosition, OverviewTotals
from phalanx.market_data.errors import MarketDataError
from phalanx.market_data.validation import validate_market_data_stock_code


class AccountOverviewError(RuntimeError):
    """A stable application error code with secret-free, actionable guidance."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def overview_decimal_context() -> Context:
    return Context(
        prec=50,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
    )


def validate_observation_span(seconds: int) -> timedelta:
    if type(seconds) is not int or seconds <= 0:
        raise AccountOverviewError("invalid_span", "전체 관측 허용시간은 양의 정수 초여야 합니다.")
    try:
        return timedelta(seconds=seconds)
    except OverflowError:
        raise AccountOverviewError(
            "invalid_span", "전체 관측 허용시간이 지원 범위를 벗어났습니다."
        ) from None


def validate_overview_snapshot(snapshot: AccountSnapshot) -> tuple[str, ...]:
    """Reject unsupported or inconsistent holdings before requesting any prices."""

    try:
        AccountSnapshot.model_validate(snapshot.model_dump())
    except (ValidationError, ValueError):
        raise AccountOverviewError(
            "invalid_snapshot", "계좌 자료를 확인할 수 없습니다. 다시 조회해 주세요."
        ) from None
    if snapshot.evidence.summary_consistency_warnings:
        raise AccountOverviewError(
            "inconsistent_snapshot",
            "조회 중 계좌 요약이 변경되었습니다. 계좌를 다시 조회해 주세요.",
        )
    codes = tuple(position.stock_code for position in snapshot.positions)
    for code in codes:
        try:
            validate_market_data_stock_code(code)
        except MarketDataError:
            raise AccountOverviewError(
                "unsupported_holding",
                "현재가 조회를 지원하지 않는 보유종목이 있습니다. 계좌 스냅샷을 확인해 주세요.",
            ) from None
    return codes


def calculate_asset_reconciliation(summary: AccountSummary) -> tuple[Decimal, Decimal]:
    """Reverse-derived display amounts, never measures of spendable cash."""

    with localcontext(overview_decimal_context()):
        return (
            summary.total_assets - summary.deposit_total - summary.securities_evaluation_amount,
            summary.total_assets - summary.net_assets,
        )


def build_account_overview(
    snapshot: AccountSnapshot,
    prices: ValuationPriceBundle | None,
    *,
    max_observation_span_seconds: int = 60,
) -> AccountOverview:
    """Value recorded holdings without changing the broker-provided net assets."""

    maximum_span = validate_observation_span(max_observation_span_seconds)
    codes = validate_overview_snapshot(snapshot)
    try:
        if prices is not None:
            prices = ValuationPriceBundle.model_validate(prices)
        if (bool(codes) != (prices is not None)) or (
            prices is not None
            and (prices.stock_codes != codes or prices.market != CurrentPriceMarket.KRX)
        ):
            raise AccountOverviewError(
                "price_mismatch", "보유종목과 시세 묶음이 일치하지 않습니다. 다시 조회해 주세요."
            )
        started = snapshot.query_started_at.astimezone(UTC)
        completed = snapshot.query_completed_at.astimezone(UTC)
        if prices is not None:
            if prices.request_started_at.astimezone(UTC) < completed:
                raise AccountOverviewError(
                    "price_precedes_snapshot",
                    "계좌 조회보다 앞선 시세가 포함되었습니다. 다시 조회해 주세요.",
                )
            completed = prices.received_at.astimezone(UTC)
        span = completed - started
        if span > maximum_span:
            raise AccountOverviewError(
                "observation_span_exceeded",
                "계좌·시세 전체 관측 허용시간을 초과했습니다. 다시 조회해 주세요.",
            )
        with localcontext(overview_decimal_context()):
            return _calculate(snapshot, prices, max_observation_span_seconds, span)
    except (ValidationError, ValueError, OverflowError):
        raise AccountOverviewError(
            "invalid_prices", "시세 자료의 종목·가격·관측시각을 확인할 수 없습니다."
        ) from None
    except DecimalException:
        raise AccountOverviewError(
            "calculation_range", "평가금액이 계산 가능한 범위를 벗어났습니다."
        ) from None


def _calculate(
    snapshot: AccountSnapshot,
    prices: ValuationPriceBundle | None,
    maximum_span_seconds: int,
    span: timedelta,
) -> AccountOverview:
    observations = prices.observations if prices is not None else ()
    observed_values = tuple(
        position.holding_quantity * observation.current_price
        for position, observation in zip(snapshot.positions, observations, strict=True)
    )
    observed_total = sum(observed_values, Decimal(0))
    broker_total = sum((p.evaluation_amount for p in snapshot.positions), Decimal(0))
    other_assets, liabilities = calculate_asset_reconciliation(snapshot.summary)
    positions = tuple(
        OverviewPosition(
            stock_code=position.stock_code,
            product_name=position.product_name,
            holding_quantity=position.holding_quantity,
            sellable_quantity=position.sellable_quantity,
            broker_evaluation_amount=position.evaluation_amount,
            observed_price=observation.current_price,
            observed_evaluation_amount=value,
            observed_stock_weight=value / observed_total,
            price_request_started_at=observation.request_started_at,
            price_received_at=observation.received_at,
        )
        for position, observation, value in zip(
            snapshot.positions, observations, observed_values, strict=True
        )
    )
    return AccountOverview(
        snapshot=snapshot,
        positions=positions,
        totals=OverviewTotals(
            broker_positions_evaluation_amount=broker_total,
            broker_summary_minus_positions=snapshot.summary.securities_evaluation_amount
            - broker_total,
            broker_other_assets_and_settlement_adjustments=other_assets,
            broker_liabilities_and_deductions=liabilities,
            observed_positions_evaluation_amount=observed_total,
            observed_minus_broker_positions=observed_total - broker_total,
        ),
        observation_started_at=snapshot.query_started_at,
        observation_completed_at=prices.received_at if prices else snapshot.query_completed_at,
        observation_span_microseconds=(span.days * 86400 + span.seconds) * 1_000_000
        + span.microseconds,
        max_observation_span_seconds=maximum_span_seconds,
    )

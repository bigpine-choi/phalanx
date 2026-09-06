"""Deterministic trade-date accounting, with conservative sequential gap recovery."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext

from phalanx.account_performance import account_performance_decimal_context
from phalanx.nav.models import (
    AccountState,
    DailyInput,
    DailyNav,
    Inception,
    LedgerEvent,
    NavError,
)

ZERO = Decimal(0)
BASE = Decimal(1000)


class _Unconfirmed(Exception):
    """Evidence cannot support a valid daily accounting state."""


def _validate(
    inception: Inception, events: Sequence[LedgerEvent], days: Sequence[DailyInput], through: date
) -> None:
    if type(through) is not date or through < inception.inception_date:
        raise NavError("복원 종료일은 설정일 이후의 명시적인 날짜여야 합니다.")
    if len({event.event_id for event in events}) != len(events):
        raise NavError("계산 입력에 중복 event_id가 있습니다. 최신 정정본 하나만 사용하세요.")
    if len({day.date for day in days}) != len(days):
        raise NavError("계산 입력에 중복 평가일이 있습니다. 최신 정정본 하나만 사용하세요.")
    if any(event.date <= inception.inception_date for event in events):
        raise NavError("설정일 종가 상태에 포함된 거래는 원장에 다시 입력할 수 없습니다.")
    if any(day.date < inception.inception_date for day in days):
        raise NavError("설정일 이전의 평가자료는 이 성과 계열에 입력할 수 없습니다.")


def _apply_events(
    previous: DailyNav, events: Sequence[LedgerEvent]
) -> tuple[AccountState, Decimal, Decimal]:
    assert previous.state is not None and previous.units is not None
    assert previous.unit_value is not None
    cash = previous.state.cash
    positions = dict(previous.state.positions)
    receivables = dict(previous.state.receivables)
    payables = dict(previous.state.payables)
    units = previous.units
    net_flow = ZERO
    active = [event for event in events if not event.void]
    if len({event.sequence for event in active}) != len(active):
        raise _Unconfirmed("ambiguous_event_sequence")
    for event in sorted(active, key=lambda item: item.sequence):
        amount = event.amount
        kind = event.kind
        if kind in ("buy", "sell", "dividend", "interest", "fee", "tax") and (
            event.event_id in receivables or event.event_id in payables
        ):
            raise _Unconfirmed("obligation_identifier_conflict")
        if kind in ("buy", "sell"):
            assert event.instrument is not None and event.quantity is not None
            quantity = positions.get(event.instrument, ZERO)
            if kind == "buy":
                positions[event.instrument] = quantity + event.quantity
                payables[event.event_id] = amount
            else:
                if quantity < event.quantity:
                    raise _Unconfirmed("insufficient_position")
                positions[event.instrument] = quantity - event.quantity
                receivables[event.event_id] = amount
        elif kind in ("dividend", "interest"):
            receivables[event.event_id] = amount
        elif kind in ("fee", "tax"):
            payables[event.event_id] = amount
        elif kind in ("settle_receivable", "settle_payable"):
            assert event.reference_id is not None
            obligations = receivables if kind == "settle_receivable" else payables
            outstanding = obligations.get(event.reference_id)
            if outstanding is None or amount > outstanding:
                raise _Unconfirmed("unmatched_or_excess_settlement")
            remaining = outstanding - amount
            if remaining:
                obligations[event.reference_id] = remaining
            else:
                del obligations[event.reference_id]
            cash += amount if kind == "settle_receivable" else -amount
        else:
            flow = amount if kind == "deposit" else -amount
            net_flow += flow
            cash += flow
            # Explicit approximation: every flow receives/redeems units at yesterday's close.
            # Preserve intraday order so a full redemption cannot be hidden by a later deposit.
            units += flow / previous.unit_value
            if units <= ZERO:
                raise _Unconfirmed("nonpositive_units")
    return (
        AccountState(cash=cash, positions=positions, receivables=receivables, payables=payables),
        units,
        net_flow,
    )


def _nav(state: AccountState, day: DailyInput) -> Decimal:
    if any(code not in day.prices for code, quantity in state.positions.items() if quantity > ZERO):
        raise _Unconfirmed("missing_position_price")
    # Canonical order removes JSON map insertion order as a source of rounded Decimal differences.
    holdings = sum(
        (
            state.positions[code] * day.prices[code]
            for code in sorted(state.positions)
            if state.positions[code] > ZERO
        ),
        ZERO,
    )
    value = (
        state.cash
        + holdings
        + sum((state.receivables[key] for key in sorted(state.receivables)), ZERO)
        - sum((state.payables[key] for key in sorted(state.payables)), ZERO)
    )
    if value <= ZERO:
        raise _Unconfirmed("nonpositive_nav")
    return value


def _confirmed_day(
    inception: Inception,
    day: DailyInput,
    events: Sequence[LedgerEvent],
    previous: DailyNav | None,
    benchmark_base: Decimal,
    peak: Decimal,
    benchmark_peak: Decimal,
) -> DailyNav:
    assert day.benchmark_close is not None
    if previous is None:
        state = inception.initial_state.model_copy(deep=True)
        nav = _nav(state, day)
        return DailyNav(
            date=day.date,
            status="confirmed",
            nav=nav,
            units=nav / BASE,
            unit_value=BASE,
            cumulative_return=ZERO,
            drawdown=ZERO,
            mdd=ZERO,
            benchmark_unit_value=BASE,
            benchmark_cumulative_return=ZERO,
            benchmark_drawdown=ZERO,
            benchmark_mdd=ZERO,
            excess_return=ZERO,
            state=state,
        )
    assert previous.unit_value is not None and previous.nav is not None
    assert previous.mdd is not None and previous.benchmark_unit_value is not None
    assert previous.benchmark_mdd is not None
    state, units, external_flow = _apply_events(previous, events)
    nav = _nav(state, day)
    value = nav / units
    benchmark_value = day.benchmark_close / benchmark_base * BASE
    drawdown = value / max(peak, value) - 1
    benchmark_drawdown = benchmark_value / max(benchmark_peak, benchmark_value) - 1
    cumulative = value / BASE - 1
    benchmark_cumulative = benchmark_value / BASE - 1
    return DailyNav(
        date=day.date,
        status="confirmed",
        nav=nav,
        units=units,
        unit_value=value,
        daily_return=value / previous.unit_value - 1,
        cumulative_return=cumulative,
        drawdown=drawdown,
        mdd=min(previous.mdd, drawdown),
        benchmark_unit_value=benchmark_value,
        benchmark_daily_return=benchmark_value / previous.benchmark_unit_value - 1,
        benchmark_cumulative_return=benchmark_cumulative,
        benchmark_drawdown=benchmark_drawdown,
        benchmark_mdd=min(previous.benchmark_mdd, benchmark_drawdown),
        excess_return=cumulative - benchmark_cumulative,
        profit_loss=nav - previous.nav - external_flow,
        external_flow=external_flow,
        state=state,
    )


def calculate_daily_nav(
    inception: Inception,
    events: Sequence[LedgerEvent],
    days: Sequence[DailyInput],
    through: date,
) -> tuple[DailyNav, ...]:
    """Replay the latest normalized ledger from an immutable EOD inception.

    Calendar days are explicit. Missing evidence blocks the complete dependent chain;
    no prices, empty ledgers, settlement dates or official inception are inferred.
    Replaying from the baseline intentionally favors reproducibility over incremental speed.
    """

    _validate(inception, events, days, through)
    by_date = {day.date: day for day in days}
    events_by_date: dict[date, list[LedgerEvent]] = {}
    opening_ids = (
        inception.initial_state.receivables.keys() | inception.initial_state.payables.keys()
    )
    for event in events:
        events_by_date.setdefault(event.date, []).append(event)
    rows: list[DailyNav] = []
    peak = benchmark_peak = BASE
    benchmark_base: Decimal | None = None
    previous: DailyNav | None = None
    blocked = False
    with localcontext(account_performance_decimal_context()):
        for offset in range((through - inception.inception_date).days + 1):
            current = inception.inception_date + timedelta(days=offset)
            day = by_date.get(current)
            reasons: list[str] = []
            if blocked:
                reasons.append("preceding_day_pending")
            if day is None:
                reasons.append("missing_daily_input")
            else:
                if not day.ledger_complete:
                    reasons.append("ledger_incomplete")
                if day.benchmark_close is None:
                    reasons.append("missing_benchmark")
            current_events = events_by_date.get(current, [])
            if any(event.event_id in opening_ids and not event.void for event in current_events):
                reasons.append("opening_obligation_identifier_conflict")
            if not reasons:
                assert day is not None and day.benchmark_close is not None
                try:
                    row = _confirmed_day(
                        inception,
                        day,
                        current_events,
                        previous,
                        day.benchmark_close if benchmark_base is None else benchmark_base,
                        peak,
                        benchmark_peak,
                    )
                except _Unconfirmed as error:
                    reasons.append(str(error))
                except DecimalException:
                    reasons.append("unsupported_decimal_range")
                else:
                    rows.append(row)
                    previous = row
                    if benchmark_base is None:
                        benchmark_base = day.benchmark_close
                    assert row.unit_value is not None and row.benchmark_unit_value is not None
                    peak = max(peak, row.unit_value)
                    benchmark_peak = max(benchmark_peak, row.benchmark_unit_value)
            if reasons:
                blocked = True
                rows.append(DailyNav(date=current, status="pending", reasons=tuple(reasons)))
    return tuple(rows)

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal, Inexact, Rounded, localcontext
from typing import Any

import pytest
from pydantic import ValidationError

from phalanx.nav.engine import calculate_daily_nav
from phalanx.nav.models import AccountState, DailyInput, DailyNav, Inception, LedgerEvent, NavError

D0 = date(2026, 9, 4)  # Friday: Saturday and Sunday still need explicit daily coverage.


def _state(
    cash: str = "1000",
    positions: dict[str, str] | None = None,
    receivables: dict[str, str] | None = None,
    payables: dict[str, str] | None = None,
) -> AccountState:
    return AccountState.model_validate(
        {
            "cash": cash,
            "positions": positions or {},
            "receivables": receivables or {},
            "payables": payables or {},
        }
    )


def _inception(state: AccountState | None = None, **changes: Any) -> Inception:
    return Inception.model_validate(
        {
            "series_id": "synthetic-engine",
            "environment": "development",
            "inception_date": D0,
            "initial_state": state or _state(),
            "cash_flow_policy": "previous_close_unit_value",
            "benchmark_id": "KOSPI_TR",
            "source_ref": "synthetic:opening-state",
            **changes,
        }
    )


def _day(
    offset: int,
    prices: dict[str, str] | None = None,
    benchmark: str | None = "100",
    **changes: Any,
) -> DailyInput:
    return DailyInput.model_validate(
        {
            "date": D0 + timedelta(days=offset),
            "ledger_complete": True,
            "prices": prices or {},
            "benchmark_close": benchmark,
            "source_ref": f"synthetic:valuation:{offset}",
            **changes,
        }
    )


def _event(
    event_id: str, offset: int, kind: str, amount: str, sequence: int = 0, **changes: Any
) -> LedgerEvent:
    return LedgerEvent.model_validate(
        {
            "event_id": event_id,
            "date": D0 + timedelta(days=offset),
            "sequence": sequence,
            "kind": kind,
            "amount": amount,
            "source_ref": f"synthetic:event:{event_id}",
            **changes,
        }
    )


def _calculate(
    inception: Inception,
    days: tuple[DailyInput, ...],
    events: tuple[LedgerEvent, ...] = (),
    through: date | None = None,
) -> tuple[DailyNav, ...]:
    return calculate_daily_nav(inception, events, days, through or max(day.date for day in days))


def _assert_pending(row: DailyNav) -> None:
    assert row.status == "pending"
    assert row.reasons
    assert row.state is None
    for field in (
        "nav",
        "units",
        "unit_value",
        "daily_return",
        "cumulative_return",
        "drawdown",
        "mdd",
        "benchmark_unit_value",
        "benchmark_daily_return",
        "benchmark_cumulative_return",
        "benchmark_drawdown",
        "benchmark_mdd",
        "excess_return",
        "profit_loss",
        "external_flow",
    ):
        assert getattr(row, field) is None, field


def _trade_cycle() -> tuple[Inception, tuple[DailyInput, ...], tuple[LedgerEvent, ...]]:
    inception = _inception(_state("1000", {"A": "10"}, {"opening-r": "40"}, {"opening-p": "40"}))
    days = tuple(_day(i, {"A": "100" if i < 3 else "110"}) for i in range(5))
    events = (
        _event("buy", 1, "buy", "200", 0, instrument="A", quantity="2"),
        _event("dividend", 1, "dividend", "30", 1),
        _event("interest", 1, "interest", "10", 2),
        _event("fee", 1, "fee", "5", 3),
        _event("tax", 1, "tax", "5", 4),
        _event("deposit", 1, "deposit", "1000", 5),
        _event("opening-r-settled", 2, "settle_receivable", "40", 0, reference_id="opening-r"),
        _event("opening-p-settled", 2, "settle_payable", "40", 1, reference_id="opening-p"),
        _event("buy-settled", 2, "settle_payable", "200", 2, reference_id="buy"),
        _event("dividend-settled", 2, "settle_receivable", "30", 3, reference_id="dividend"),
        _event("interest-settled", 2, "settle_receivable", "10", 4, reference_id="interest"),
        _event("fee-settled", 2, "settle_payable", "5", 5, reference_id="fee"),
        _event("tax-settled", 2, "settle_payable", "5", 6, reference_id="tax"),
        _event("sell", 3, "sell", "220", 0, instrument="A", quantity="2"),
        _event("sell-settled", 4, "settle_receivable", "220", 0, reference_id="sell"),
        _event("withdrawal", 4, "withdrawal", "1050", 1),
    )
    return inception, days, events


def test_inception_preserves_full_state_and_anchors_both_unit_values() -> None:
    inception = _inception(_state("500", {"A": "10"}, {"r": "60"}, {"p": "10"}))

    (row,) = _calculate(inception, (_day(0, {"A": "100"}, "456.78"),))

    assert row.status == "confirmed"
    assert row.date == D0
    assert row.state == inception.initial_state
    assert row.nav == Decimal("1550")
    assert row.units == Decimal("1.55")
    assert row.unit_value == row.benchmark_unit_value == Decimal("1000")
    assert row.cumulative_return == row.benchmark_cumulative_return == Decimal(0)
    assert row.drawdown == row.mdd == row.benchmark_drawdown == row.benchmark_mdd == 0
    assert row.daily_return is row.benchmark_daily_return is row.profit_loss is None


def test_hand_checked_trades_settlements_income_costs_and_external_flows() -> None:
    inception, days, events = _trade_cycle()

    rows = _calculate(inception, days, events)

    assert all(row.status == "confirmed" for row in rows)
    assert [row.nav for row in rows] == list(map(Decimal, ("2000", "3030", "3030", "3150", "2100")))
    assert [row.units for row in rows] == list(map(Decimal, ("2", "3", "3", "3", "2")))
    assert [row.unit_value for row in rows] == list(
        map(Decimal, ("1000", "1010", "1010", "1050", "1050"))
    )
    assert [row.profit_loss for row in rows[1:]] == list(map(Decimal, ("30", "0", "120", "0")))
    assert [row.external_flow for row in rows[1:]] == list(
        map(Decimal, ("1000", "0", "0", "-1050"))
    )
    first = rows[1].state
    assert first is not None
    assert first.cash == Decimal("2000")
    assert first.positions == {"A": Decimal("12")}
    assert first.receivables == {
        "opening-r": Decimal("40"),
        "dividend": Decimal("30"),
        "interest": Decimal("10"),
    }
    assert first.payables == {
        "opening-p": Decimal("40"),
        "buy": Decimal("200"),
        "fee": Decimal("5"),
        "tax": Decimal("5"),
    }
    settled = rows[2].state
    assert settled is not None
    assert settled.cash == Decimal("1830")
    assert sum(settled.receivables.values()) == sum(settled.payables.values()) == 0
    final = rows[-1].state
    assert final is not None
    assert final.cash == Decimal("1000")
    assert final.positions == {"A": Decimal("10")}
    assert sum(final.receivables.values()) == sum(final.payables.values()) == 0
    assert inception.initial_state == _state(
        "1000", {"A": "10"}, {"opening-r": "40"}, {"opening-p": "40"}
    )


def test_daily_calculation_matches_single_ordered_backfill_and_is_repeatable() -> None:
    inception, days, events = _trade_cycle()
    batch = _calculate(inception, tuple(reversed(days)), tuple(reversed(events)))

    for last in range(len(days)):
        incremental = _calculate(
            inception,
            days[: last + 1],
            tuple(event for event in events if event.date <= days[last].date),
        )
        assert incremental == batch[: last + 1]
    assert _calculate(inception, days, events) == batch


def test_flow_uses_previous_close_value_and_income_is_operating_profit() -> None:
    days = (_day(0), _day(1), _day(2))
    events = (
        _event("interest", 1, "interest", "100", 0),
        _event("deposit", 1, "deposit", "1000", 1),
        _event("withdrawal", 2, "withdrawal", "1050"),
    )

    rows = _calculate(_inception(), days, events)

    assert rows[1].nav == Decimal("2100")
    assert rows[1].units == 2
    assert rows[1].unit_value == Decimal("1050")
    assert rows[1].daily_return == Decimal("0.05")
    assert rows[1].profit_loss == Decimal("100")
    assert rows[2].nav == Decimal("1050")
    assert rows[2].units == 1
    assert rows[2].unit_value == Decimal("1050")
    assert rows[2].profit_loss == rows[2].daily_return == 0


def test_drawdowns_follow_unit_values_and_benchmark_uses_same_inception() -> None:
    days = tuple(
        _day(i, {"A": price}, benchmark)
        for i, (price, benchmark) in enumerate(
            (("100", "100"), ("120", "110"), ("90", "88"), ("108", "121"))
        )
    )

    rows = _calculate(_inception(_state("0", {"A": "10"})), days)

    assert [row.unit_value for row in rows] == list(map(Decimal, ("1000", "1200", "900", "1080")))
    assert [row.drawdown for row in rows] == list(map(Decimal, ("0", "0", "-0.25", "-0.1")))
    assert [row.mdd for row in rows] == list(map(Decimal, ("0", "0", "-0.25", "-0.25")))
    assert [row.benchmark_unit_value for row in rows] == list(
        map(Decimal, ("1000", "1100", "880", "1210"))
    )
    assert rows[2].benchmark_drawdown == rows[-1].benchmark_mdd == Decimal("-0.2")
    assert rows[-1].benchmark_drawdown == 0
    assert rows[-1].daily_return == Decimal("0.2")
    assert rows[-1].benchmark_daily_return == Decimal("0.375")
    assert rows[-1].cumulative_return == Decimal("0.08")
    assert rows[-1].benchmark_cumulative_return == Decimal("0.21")
    assert rows[-1].excess_return == Decimal("-0.13")


def test_external_withdrawal_does_not_create_drawdown_when_nav_falls() -> None:
    rows = _calculate(
        _inception(),
        (_day(0), _day(1)),
        (_event("cash-out", 1, "withdrawal", "750"),),
    )

    assert rows[1].nav == 250
    assert rows[1].units == Decimal("0.25")
    assert rows[1].unit_value == 1000
    assert rows[1].mdd == rows[1].daily_return == rows[1].profit_loss == 0


@pytest.mark.parametrize("missing", ["date", "ledger", "price", "benchmark"])
def test_missing_inputs_leave_pending_chain_until_explicitly_supplemented(missing: str) -> None:
    inception = _inception(_state("0", {"A": "10"}))
    complete_days = (_day(0, {"A": "100"}), _day(1, {"A": "110"}), _day(2, {"A": "120"}))
    days = list(complete_days)
    if missing == "date":
        days.pop(1)
    elif missing == "ledger":
        days[1] = _day(1, {"A": "110"}, ledger_complete=False)
    elif missing == "price":
        days[1] = _day(1)
    else:
        days[1] = _day(1, {"A": "110"}, benchmark=None)

    incomplete = _calculate(inception, tuple(days))

    assert [row.date for row in incomplete] == [D0 + timedelta(days=i) for i in range(3)]
    assert incomplete[0].status == "confirmed"
    _assert_pending(incomplete[1])
    _assert_pending(incomplete[2])
    repaired = _calculate(inception, complete_days)
    assert all(row.status == "confirmed" for row in repaired)
    assert repaired[0] == incomplete[0]
    assert repaired[-1].unit_value == 1200


@pytest.mark.parametrize("missing", ["day", "ledger", "price", "benchmark"])
def test_missing_inception_evidence_never_rebases_to_first_later_day(missing: str) -> None:
    inception = _inception(_state("0", {"A": "10"}))
    initial = _day(0, {"A": "100"})
    if missing == "ledger":
        initial = _day(0, {"A": "100"}, ledger_complete=False)
    elif missing == "price":
        initial = _day(0)
    elif missing == "benchmark":
        initial = _day(0, {"A": "100"}, benchmark=None)
    days = (_day(1, {"A": "120"}),) if missing == "day" else (initial, _day(1, {"A": "120"}))

    rows = _calculate(inception, days)

    assert len(rows) == 2
    assert rows[0].date == D0
    for row in rows:
        _assert_pending(row)


def test_partial_settlement_changes_cash_without_recognizing_income_twice() -> None:
    events = (
        _event("dividend", 1, "dividend", "100"),
        _event("part-one", 2, "settle_receivable", "30", reference_id="dividend"),
        _event("part-two", 3, "settle_receivable", "70", reference_id="dividend"),
    )

    rows = _calculate(_inception(), tuple(_day(i) for i in range(4)), events)

    assert [row.nav for row in rows] == [1000, 1100, 1100, 1100]
    assert [row.profit_loss for row in rows[1:]] == [100, 0, 0]
    assert rows[2].state is not None
    assert rows[2].state.cash == 1030
    assert rows[2].state.receivables == {"dividend": Decimal("70")}


@pytest.mark.parametrize("problem", ["reference", "overpayment", "wrong_side", "order", "oversell"])
def test_invalid_ledger_state_is_pending_and_does_not_abort_rest_of_history(problem: str) -> None:
    events = (
        _event("income", 1, "interest", "10", 0),
        _event("payment", 1, "settle_receivable", "10", 1, reference_id="income"),
    )
    if problem == "reference":
        events = (_event("bad", 1, "settle_receivable", "10", reference_id="missing"),)
    elif problem == "overpayment":
        events = (
            events[0],
            _event("payment", 1, "settle_receivable", "11", 1, reference_id="income"),
        )
    elif problem == "wrong_side":
        events = (events[0], _event("payment", 1, "settle_payable", "10", 1, reference_id="income"))
    elif problem == "order":
        events = (
            _event("income", 1, "interest", "10", 1),
            _event("payment", 1, "settle_receivable", "10", 0, reference_id="income"),
        )
    else:
        events = (_event("short-sale", 1, "sell", "100", instrument="A", quantity="1"),)

    rows = _calculate(_inception(), (_day(0), _day(1), _day(2)), events)

    assert rows[0].status == "confirmed"
    _assert_pending(rows[1])
    _assert_pending(rows[2])


def test_duplicate_settlement_of_paid_obligation_is_pending() -> None:
    events = (
        _event("income", 1, "interest", "10", 0),
        _event("payment-one", 1, "settle_receivable", "10", 1, reference_id="income"),
        _event("payment-two", 2, "settle_receivable", "10", reference_id="income"),
    )

    rows = _calculate(_inception(), (_day(0), _day(1), _day(2)), events)

    assert rows[1].status == "confirmed"
    _assert_pending(rows[2])


@pytest.mark.parametrize("kind", ["withdrawal", "fee"])
def test_nonpositive_nav_or_units_are_pending(kind: str) -> None:
    rows = _calculate(_inception(), (_day(0), _day(1)), (_event("all-assets", 1, kind, "1000"),))

    _assert_pending(rows[1])


def test_later_deposit_cannot_hide_an_earlier_full_redemption() -> None:
    rows = _calculate(
        _inception(),
        (_day(0), _day(1)),
        (
            _event("withdrawal", 1, "withdrawal", "1000", 0),
            _event("deposit", 1, "deposit", "1000", 1),
        ),
    )

    _assert_pending(rows[1])


def test_zero_initial_nav_is_pending_without_automatic_reinitialization() -> None:
    rows = _calculate(
        _inception(_state("0")),
        (_day(0), _day(1)),
        (_event("later-capital", 1, "deposit", "1000"),),
    )

    for row in rows:
        _assert_pending(row)


def test_void_event_is_not_applied() -> None:
    rows = _calculate(
        _inception(),
        (_day(0), _day(1)),
        (
            _event(
                "cancelled-interest",
                1,
                "interest",
                "100",
                void=True,
                revision=2,
                correction_reason="source transaction cancelled",
            ),
        ),
    )

    assert rows[1].status == "confirmed"
    assert rows[1].nav == 1000
    assert rows[1].profit_loss == 0


@pytest.mark.parametrize("offset", [-1, 0])
def test_event_at_or_before_explicit_eod_inception_is_rejected(offset: int) -> None:
    with pytest.raises(NavError):
        _calculate(
            _inception(), (_day(0), _day(1)), (_event("ambiguous", offset, "interest", "1"),)
        )


def test_engine_rejects_duplicate_event_identifiers_and_duplicate_days() -> None:
    event = _event("same-event", 1, "interest", "10")
    with pytest.raises(NavError):
        _calculate(_inception(), (_day(0), _day(1)), (event, event))
    with pytest.raises(NavError):
        _calculate(_inception(), (_day(0), _day(0)))


def test_same_day_sequence_collision_is_pending_until_order_is_supplied() -> None:
    rows = _calculate(
        _inception(),
        (_day(0), _day(1)),
        (_event("first", 1, "interest", "10"), _event("second", 1, "interest", "20")),
    )

    _assert_pending(rows[1])


def test_opening_obligation_identifier_cannot_be_reused_after_settlement() -> None:
    rows = _calculate(
        _inception(_state("1000", receivables={"opening-interest": "10"})),
        (_day(0), _day(1), _day(2)),
        (
            _event("settled", 1, "settle_receivable", "10", reference_id="opening-interest"),
            _event("opening-interest", 2, "interest", "10"),
        ),
    )

    assert rows[1].status == "confirmed"
    _assert_pending(rows[2])


def test_past_price_correction_recomputes_all_later_drawdowns() -> None:
    inception = _inception(_state("0", {"A": "10"}))
    days = tuple(_day(i, {"A": price}) for i, price in enumerate(("100", "120", "90", "108")))
    original = _calculate(inception, days)
    corrected_days = (
        days[0],
        _day(1, {"A": "150"}, revision=2, correction_reason="verified unadjusted close"),
        *days[2:],
    )

    corrected = _calculate(inception, corrected_days)

    assert corrected[0] == original[0]
    assert original[-1].mdd == Decimal("-0.25")
    assert corrected[-1].mdd == Decimal("-0.4")
    assert corrected[-1].drawdown == Decimal("-0.28")
    assert corrected[-1].unit_value == original[-1].unit_value == 1080
    assert [row.benchmark_unit_value for row in corrected] == [
        row.benchmark_unit_value for row in original
    ]
    assert _calculate(inception, days) == original


def test_past_event_correction_recomputes_units_issued_on_following_days() -> None:
    inception = _inception()
    days = (_day(0), _day(1), _day(2))
    events = (_event("income", 1, "interest", "100"), _event("deposit", 2, "deposit", "1100"))
    original = _calculate(inception, days, events)
    corrected_event = _event(
        "income", 1, "interest", "1200", revision=2, correction_reason="verified gross income"
    )

    corrected = _calculate(inception, days, (corrected_event, events[1]))

    assert original[-1].units == 2
    assert original[-1].unit_value == 1100
    assert corrected[0] == original[0]
    assert corrected[-1].units == Decimal("1.5")
    assert corrected[-1].nav == 3300
    assert corrected[-1].unit_value == 2200
    assert corrected[-1].profit_loss == 0


def test_explicit_zero_price_is_usable_for_worthless_asset_with_positive_total_nav() -> None:
    rows = _calculate(
        _inception(_state("1000", {"A": "10"})),
        (_day(0, {"A": "100"}), _day(1, {"A": "0"})),
    )

    assert rows[1].status == "confirmed"
    assert rows[1].nav == 1000
    assert rows[1].unit_value == 500
    assert rows[1].mdd == rows[1].daily_return == Decimal("-0.5")


def test_sold_out_holding_needs_no_price_and_trade_profit_is_preserved() -> None:
    rows = _calculate(
        _inception(_state("0", {"A": "10"})),
        (_day(0, {"A": "100"}), _day(1)),
        (_event("exit", 1, "sell", "1100", instrument="A", quantity="10"),),
    )

    assert rows[1].status == "confirmed"
    assert rows[1].nav == 1100
    assert rows[1].profit_loss == 100
    assert rows[1].state is not None
    assert rows[1].state.positions.get("A", Decimal(0)) == 0


def test_out_of_range_arithmetic_remains_pending() -> None:
    rows = _calculate(
        _inception(_state("1000", {"A": "1e999999"})),
        (_day(0, {"A": "1e999999"}), _day(1, {"A": "1"})),
    )

    for row in rows:
        _assert_pending(row)


def test_future_input_does_not_change_requested_prefix() -> None:
    inception, days, events = _trade_cycle()

    rows = _calculate(inception, days, events, through=days[1].date)

    assert rows == _calculate(
        inception, days[:2], tuple(e for e in events if e.date <= days[1].date)
    )


def test_ambient_decimal_precision_rounding_and_traps_cannot_change_output() -> None:
    inception = _inception(_state("0", {"A": "3"}))
    days = (_day(0, {"A": "100"}, "3"), _day(1, {"A": "101"}, "7"))
    events = (_event("deposit", 1, "deposit", "1"),)
    expected = _calculate(inception, days, events)

    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_FLOOR
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        observed = _calculate(inception, days, events)
        assert context.prec == 3
        assert context.rounding == ROUND_FLOOR
        assert context.traps[Inexact] and context.traps[Rounded]

    assert observed == expected


@pytest.mark.parametrize("invalid", [0.1, True, "NaN", "Infinity", "-Infinity"])
def test_decimal_input_rejects_binary_floats_booleans_and_nonfinite_values(invalid: Any) -> None:
    with pytest.raises(ValidationError):
        _state(cash=invalid)
    with pytest.raises(ValidationError):
        _event("invalid", 1, "deposit", invalid)
    with pytest.raises(ValidationError):
        _day(0, {"A": invalid})


@pytest.mark.parametrize("field", ["inception_date", "environment", "cash_flow_policy"])
def test_inception_has_no_implicit_date_environment_or_cash_flow_policy(field: str) -> None:
    payload = _inception().model_dump(mode="json")
    del payload[field]

    with pytest.raises(ValidationError):
        Inception.model_validate(payload)


@pytest.mark.parametrize("invalid", [1, 0, "true", "false", None])
def test_daily_ledger_completeness_requires_an_explicit_boolean(invalid: Any) -> None:
    with pytest.raises(ValidationError):
        _day(0, ledger_complete=invalid)


@pytest.mark.parametrize("model", ["event", "valuation"])
def test_correction_requires_an_explanation(model: str) -> None:
    with pytest.raises(ValidationError):
        if model == "event":
            _event("revised", 1, "interest", "100", revision=2)
        else:
            _day(1, revision=2)


@pytest.mark.parametrize("kind", ["buy", "sell"])
def test_trade_requires_explicit_positive_quantity_and_instrument(kind: str) -> None:
    with pytest.raises(ValidationError):
        _event("missing-details", 1, kind, "100")
    with pytest.raises(ValidationError):
        _event("zero-quantity", 1, kind, "100", instrument="A", quantity="0")

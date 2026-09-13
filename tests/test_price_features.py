from __future__ import annotations

import json
from datetime import timedelta
from decimal import ROUND_UP, Context, Decimal, DefaultContext, Inexact, localcontext

import pytest
from feature_helpers import CODES, END, NOW, START, bars, history

from phalanx.domain.price_features import CandidatePriceFeatures
from phalanx.domain.price_history import SymbolStatus
from phalanx.market_data.features.calculation import calculate_price_features
from phalanx.market_data.features.errors import PriceFeatureError


def calculate(series, *, as_of=END, calculated_at=NOW):
    view = history((series,), codes=(CODES[1],))
    return calculate_price_features(
        view.job, view.symbols, as_of=as_of, calculated_at=calculated_at
    )


def metric(result, name, intervals, *, symbol=0):
    return next(
        m for m in result.symbols[symbol].metrics if m.name == name and m.intervals == intervals
    )


@pytest.mark.parametrize("intervals", [20, 60, 120, 252])
def test_exact_price_return_uses_n_intervals_and_last_observed_close(intervals: int) -> None:
    series = bars(CODES[1], ["100"] * intervals + ["125"], step=2)
    result = calculate(series)
    value = metric(result, "price_return", intervals)
    assert value.value == Decimal("0.25")
    assert value.window_start == series[0].trade_date
    assert value.window_end == series[-1].trade_date
    assert result.symbols[0].used_end == series[-1].trade_date
    assert (
        result.symbols[0].calendar_days_since_last_observation == (END - series[-1].trade_date).days
    )


@pytest.mark.parametrize("intervals,annualized_variance", [(20, "0.126"), (60, "0.042")])
def test_sample_volatility_matches_hand_calculation(
    intervals: int, annualized_variance: str
) -> None:
    # N-1 zero returns followed by 0.1: sample variance = 0.01/N (ddof=1).
    result = calculate(bars(CODES[1], ["100"] * intervals + ["110"]))
    actual = metric(result, "annualized_volatility", intervals).value
    with localcontext(Context(prec=80)):
        expected = Decimal(annualized_variance).sqrt()
        assert abs(actual - expected) < Decimal("1e-48")
    assert result.policy.variance_ddof == 1
    assert result.policy.annualization_periods == 252
    assert result.policy.interval_basis == "consecutive_observed_closes"


@pytest.mark.parametrize("intervals", [60, 252])
def test_drawdown_starts_at_first_close_inside_window(intervals: int) -> None:
    # The outside 1000 peak must not enter the N+1 close window.
    series = bars(CODES[1], ["1000", "100", "120", "60"] + ["90"] * (intervals - 2))
    result = calculate(series)
    value = metric(result, "maximum_drawdown", intervals)
    assert value.value == Decimal("-0.5")
    assert value.window_start == series[1].trade_date
    first_peak = calculate(bars(CODES[1], ["200"] + ["100"] * intervals))
    assert metric(first_peak, "maximum_drawdown", intervals).value == Decimal("-0.5")


@pytest.mark.parametrize(
    "name,intervals",
    [("price_return", n) for n in (20, 60, 120, 252)]
    + [("annualized_volatility", n) for n in (20, 60)]
    + [("maximum_drawdown", n) for n in (60, 252)],
)
def test_n_and_n_plus_one_observations_are_distinct(name: str, intervals: int) -> None:
    short = metric(calculate(bars(CODES[1], ["100"] * intervals)), name, intervals)
    assert short.value is None and not short.available
    assert short.reason_code == "INSUFFICIENT_OBSERVATIONS"
    assert short.required_observations == intervals + 1
    assert short.available_observations == intervals
    assert str(intervals + 1) in short.reason and str(intervals) in short.reason
    enough = metric(calculate(bars(CODES[1], ["100"] * (intervals + 1))), name, intervals)
    assert enough.value == 0 and enough.available
    assert enough.reason_code is None and enough.reason is None


def test_constant_prices_produce_zero_and_json_decimal_strings() -> None:
    result = calculate(bars(CODES[1], ["100.0010"] * 253))
    assert result.complete
    assert all(m.value == Decimal(0) and m.available for m in result.symbols[0].metrics)
    payload = json.loads(result.to_json_bytes())
    assert all(m["value"] == "0" for m in payload["symbols"][0]["metrics"])
    assert payload["symbols"][0]["last_close"] == "100.0010"
    restored = CandidatePriceFeatures.model_validate_json(result.to_json_bytes())
    assert restored == result
    assert restored.to_json_bytes() == result.to_json_bytes()


def test_future_changes_do_not_change_metrics_or_consumed_hash() -> None:
    past = bars(CODES[1], ["100"] * 60 + ["110"])
    cutoff = past[-1].trade_date
    first = calculate(past, as_of=cutoff)
    changed_future = bars(CODES[1], ["999", "1", "2000"], start=cutoff + timedelta(days=1))
    second = calculate(past + changed_future, as_of=cutoff, calculated_at=NOW + timedelta(days=1))
    a, b = first.symbols[0], second.symbols[0]
    assert a.metrics == b.metrics
    assert a.consumed_input_sha256 == b.consumed_input_sha256
    assert a.source_price_sha256 != b.source_price_sha256
    assert first.calculated_at != second.calculated_at
    assert a.used_start == b.used_start and a.used_end == b.used_end
    assert a.used_observation_count == b.used_observation_count == 61
    replaced_future = bars(CODES[1], ["10", "200", "30"], start=cutoff + timedelta(days=1))
    third = calculate(past + replaced_future, as_of=cutoff)
    assert third.symbols[0].metrics == b.metrics
    assert third.symbols[0].consumed_input_sha256 == b.consumed_input_sha256
    assert third.symbols[0].source_price_sha256 != b.source_price_sha256
    different = calculate(past[:-1] + bars(CODES[1], ["111"], start=cutoff), as_of=cutoff)
    assert different.symbols[0].consumed_input_sha256 != a.consumed_input_sha256


def test_consumed_hash_excludes_unused_fields_and_older_closes() -> None:
    series = bars(CODES[1], ["100"] * 300)
    result = calculate(series)
    changed = (
        bars(CODES[1], ["200"])[0],
        *(bar.model_copy(update={"volume": 999}) for bar in series[1:]),
    )
    revised = calculate(changed)
    a, b = result.symbols[0], revised.symbols[0]
    assert a.consumed_input_sha256 == b.consumed_input_sha256
    assert a.source_price_sha256 != b.source_price_sha256
    assert a.metrics == b.metrics
    assert a.eligible_observation_count == 300
    assert a.used_observation_count == 253
    assert a.used_start == series[-253].trade_date


def test_symbols_use_independent_dates_and_partial_metrics() -> None:
    full = bars(CODES[0], ["100"] * 253)
    short = bars(CODES[1], ["100"] * 20 + ["110"], start=START + timedelta(days=1), step=3)
    view = history((full, short))
    result = calculate_price_features(view.job, view.symbols, as_of=END, calculated_at=NOW)
    assert not result.complete
    assert result.symbols[0].complete
    assert result.symbols[1].target.short_code == "0001A0"
    assert result.symbols[1].eligible_observation_count == 21
    assert metric(result, "price_return", 20, symbol=1).value == Decimal("0.1")
    assert metric(result, "annualized_volatility", 20, symbol=1).available
    assert not metric(result, "price_return", 60, symbol=1).available
    assert result.symbols[0].used_end != result.symbols[1].used_end
    assert result.trading_day_completeness == "unverified"
    assert result.point_in_time_backtest_guaranteed is False


@pytest.mark.parametrize(
    "source",
    [
        SymbolStatus.PENDING,
        SymbolStatus.IN_PROGRESS,
        SymbolStatus.FAILED,
        SymbolStatus.UNSUPPORTED,
        (),
    ],
)
def test_source_states_are_retained_with_per_metric_reasons(source) -> None:
    result = calculate(source)
    state = result.symbols[0]
    expected = source if isinstance(source, SymbolStatus) else SymbolStatus.EMPTY
    assert state.source_status == expected
    assert all(
        m.value is None and m.reason_code == f"SOURCE_{expected.value.upper()}"
        for m in state.metrics
    )
    assert state.used_observation_count == 0
    assert state.used_start is None and state.used_end is None and state.last_close is None
    assert state.calendar_days_since_last_observation is None
    if expected == SymbolStatus.EMPTY:
        assert state.source_price_sha256 is not None and state.consumed_input_sha256 is not None
    else:
        assert state.source_price_sha256 is None and state.consumed_input_sha256 is None
    if expected == SymbolStatus.FAILED:
        assert state.source_error_code == "SOURCE_TEST_ERROR"
    assert not result.complete


def test_no_observations_at_cutoff_has_distinct_reason() -> None:
    result = calculate(bars(CODES[1], ["100"], start=START + timedelta(days=1)), as_of=START)
    assert result.symbols[0].source_status == "completed"
    assert all(m.reason_code == "NO_OBSERVATIONS_AS_OF" for m in result.symbols[0].metrics)


@pytest.mark.parametrize(
    "as_of", [START - timedelta(days=1), END + timedelta(days=1), NOW, "2025-01-01"]
)
def test_as_of_must_be_an_exact_date_inside_request(as_of) -> None:
    with pytest.raises(PriceFeatureError) as error:
        calculate(bars(CODES[1], ["100"]), as_of=as_of)
    assert error.value.code == "INVALID_AS_OF"


def test_decimal_defaults_and_active_context_cannot_affect_results_or_hashes() -> None:
    series = bars(CODES[1], ["97"] * 60 + ["113"])
    expected = calculate(series).to_json_bytes()
    original = DefaultContext.copy()
    try:
        DefaultContext.prec = 3
        DefaultContext.rounding = ROUND_UP
        DefaultContext.Emax = 4
        DefaultContext.traps[Inexact] = True
        with localcontext() as active:
            active.prec = 4
            active.rounding = ROUND_UP
            active.traps[Inexact] = True
            before = active.copy()
            assert calculate(series).to_json_bytes() == expected
            assert str(active) == str(before)
    finally:
        DefaultContext.prec = original.prec
        DefaultContext.rounding = original.rounding
        DefaultContext.Emax = original.Emax
        DefaultContext.traps = original.traps


def test_calculation_timestamp_requires_timezone() -> None:
    with pytest.raises(PriceFeatureError) as error:
        calculate(bars(CODES[1], ["100"]), calculated_at=NOW.replace(tzinfo=None))
    assert error.value.code == "INVALID_CLOCK"

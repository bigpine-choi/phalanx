from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from phalanx.domain import DailyBar


def _bar(**overrides: object) -> DailyBar:
    values: dict[str, object] = {
        "stock_code": "005930",
        "trade_date": date(2026, 8, 28),
        "open_price": Decimal("70000.10"),
        "high_price": Decimal("72000.20"),
        "low_price": Decimal("69000.30"),
        "close_price": Decimal("71000.40"),
        "volume": 1234567,
    }
    values.update(overrides)
    return DailyBar.model_validate(values)


def test_daily_bar_preserves_exact_values_and_is_immutable() -> None:
    bar = _bar()

    assert bar.stock_code == "005930"
    assert bar.trade_date == date(2026, 8, 28)
    assert bar.close_price == Decimal("71000.40")
    assert bar.volume == 1234567
    assert '"close_price":"71000.40"' in bar.model_dump_json()
    with pytest.raises(ValidationError):
        bar.close_price = Decimal("1")


@pytest.mark.parametrize(
    "stock_code",
    (
        "5930",
        "0005930",
        "005 930",
        " 005930",
        "005930 ",
        "\uff10\uff10\uff15\uff19\uff13\uff10",
        5930,
    ),
)
def test_daily_bar_rejects_invalid_stock_codes(stock_code: object) -> None:
    with pytest.raises(ValidationError):
        _bar(stock_code=stock_code)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("open_price", Decimal("0")),
        ("high_price", Decimal("-1")),
        ("low_price", Decimal("NaN")),
        ("close_price", Decimal("Infinity")),
        ("close_price", 71000.4),
        ("close_price", True),
    ),
)
def test_daily_bar_rejects_nonpositive_nonfinite_or_binary_float_prices(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _bar(**{field: value})


@pytest.mark.parametrize("volume", (-1, Decimal("1"), 1.5, True, "1"))
def test_daily_bar_requires_a_nonnegative_strict_integer_volume(volume: object) -> None:
    with pytest.raises(ValidationError):
        _bar(volume=volume)


@pytest.mark.parametrize(
    "overrides",
    (
        {"high_price": Decimal("69999")},
        {"low_price": Decimal("71001")},
        {"high_price": Decimal("68000"), "low_price": Decimal("69000")},
    ),
)
def test_daily_bar_rejects_impossible_ohlc_relationships(
    overrides: dict[str, Decimal],
) -> None:
    with pytest.raises(ValidationError):
        _bar(**overrides)


@pytest.mark.parametrize(
    "trade_date",
    ("2026-08-28", datetime(2026, 8, 28), 20260828),
)
def test_daily_bar_requires_an_exact_date_instance(trade_date: object) -> None:
    with pytest.raises(ValidationError):
        _bar(trade_date=trade_date)


def test_daily_bar_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _bar(provider="KIS")

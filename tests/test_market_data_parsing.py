from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from phalanx.kis.errors import (
    InvalidMarketDataDateError,
    InvalidMarketDataNumericFieldError,
    InvalidMarketDataResponseStructure,
    KisMarketDataApiError,
    MarketDataDomainInvariantError,
    MissingMarketDataFieldError,
)
from phalanx.kis.market_data_parsing import parse_daily_bars_page


def _row(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "stck_bsop_date": "20260828",
        "stck_oprc": "70000.10",
        "stck_hgpr": "72000.20",
        "stck_lwpr": "69000.30",
        "stck_clpr": "71000.40",
        "acml_vol": "1234567",
    }
    result.update(overrides)
    return result


def _payload(*rows: object) -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "SYNTHETIC_SUCCESS",
        "msg1": "synthetic success",
        "output1": {},
        "output2": list(rows),
    }


def test_parser_maps_documented_output2_fields_without_side_effects() -> None:
    payload = _payload(_row(), _row(stck_bsop_date="20260827", stck_clpr="70001"))
    original = deepcopy(payload)

    bars = parse_daily_bars_page(payload, stock_code="005930")

    assert payload == original
    assert len(bars) == 2
    assert bars[0].stock_code == "005930"
    assert bars[0].trade_date == date(2026, 8, 28)
    assert bars[0].open_price == Decimal("70000.10")
    assert bars[0].high_price == Decimal("72000.20")
    assert bars[0].low_price == Decimal("69000.30")
    assert bars[0].close_price == Decimal("71000.40")
    assert bars[0].volume == 1234567


def test_parser_accepts_a_documented_empty_output2_array() -> None:
    assert parse_daily_bars_page(_payload(), stock_code="005930") == ()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stck_bsop_date", None),
        ("stck_bsop_date", ""),
        ("stck_oprc", None),
        ("stck_hgpr", " "),
        ("stck_lwpr", None),
        ("stck_clpr", ""),
        ("acml_vol", None),
    ),
)
def test_parser_raises_dedicated_error_for_missing_or_blank_fields(
    field_name: str,
    value: object,
) -> None:
    row = _row()
    row[field_name] = value

    with pytest.raises(MissingMarketDataFieldError) as captured:
        parse_daily_bars_page(_payload(row), stock_code="005930")

    assert captured.value.field_name == field_name
    assert captured.value.location == "output2[0]"


@pytest.mark.parametrize(
    "value",
    ("2026-08-28", "20260230", "2026082", 20260828),
)
def test_parser_rejects_malformed_or_nonexistent_dates(value: object) -> None:
    with pytest.raises(InvalidMarketDataDateError) as captured:
        parse_daily_bars_page(
            _payload(_row(stck_bsop_date=value)),
            stock_code="005930",
        )

    assert captured.value.field_name == "stck_bsop_date"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stck_oprc", "70,000"),
        ("stck_hgpr", "NaN"),
        ("stck_lwpr", 69000),
        ("stck_clpr", "1e5"),
        ("acml_vol", "-1"),
        ("acml_vol", "1.5"),
    ),
)
def test_parser_rejects_non_contract_numeric_values(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(InvalidMarketDataNumericFieldError) as captured:
        parse_daily_bars_page(
            _payload(_row(**{field_name: value})),
            stock_code="005930",
        )

    assert captured.value.field_name == field_name


@pytest.mark.parametrize(
    "row",
    (
        _row(stck_oprc="0"),
        _row(stck_hgpr="68000"),
        _row(stck_lwpr="73000"),
    ),
)
def test_parser_maps_valid_numbers_that_violate_domain_rules_to_dedicated_error(
    row: dict[str, object],
) -> None:
    with pytest.raises(MarketDataDomainInvariantError):
        parse_daily_bars_page(_payload(row), stock_code="005930")


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok"},
        {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok", "output2": {}},
        {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok", "output2": [None]},
        {"rt_cd": 0, "msg_cd": "OK", "msg1": "ok", "output2": []},
    ),
)
def test_parser_rejects_invalid_response_structures(payload: object) -> None:
    expected_error = (
        MissingMarketDataFieldError
        if isinstance(payload, dict) and "output2" not in payload
        else InvalidMarketDataResponseStructure
    )
    with pytest.raises(expected_error):
        parse_daily_bars_page(payload, stock_code="005930")


def test_parser_reports_api_error_metadata_but_masks_supplied_secrets() -> None:
    secret = "synthetic-sensitive-value"
    payload: dict[str, Any] = {
        "rt_cd": "1",
        "msg_cd": "SYNTHETIC_REJECTED",
        "msg1": f"request rejected for {secret}",
        "output2": [],
    }

    with pytest.raises(KisMarketDataApiError) as captured:
        parse_daily_bars_page(
            payload,
            stock_code="005930",
            sensitive_values=(secret,),
        )

    assert captured.value.rt_cd == "1"
    assert captured.value.msg_cd == "SYNTHETIC_REJECTED"
    assert captured.value.msg1 == "request rejected for [REDACTED]"
    assert secret not in str(captured.value)

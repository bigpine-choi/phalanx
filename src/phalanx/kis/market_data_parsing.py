"""Strict, side-effect-free parsing for KIS domestic daily-price output2 rows."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import ValidationError

from phalanx.domain import DailyBar
from phalanx.kis.errors import (
    InvalidMarketDataDateError,
    InvalidMarketDataNumericFieldError,
    InvalidMarketDataResponseStructure,
    KisMarketDataApiError,
    MarketDataDomainInvariantError,
    MissingMarketDataFieldError,
)

_PRICE_FIELDS = {
    "open_price": "stck_oprc",
    "high_price": "stck_hgpr",
    "low_price": "stck_lwpr",
    "close_price": "stck_clpr",
}
_DATE_PATTERN = re.compile(r"^[0-9]{8}$")
_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")
_INTEGER_PATTERN = re.compile(r"^[0-9]+$")
_REDACTED = "[REDACTED]"


def parse_daily_bars_page(
    payload: object,
    *,
    stock_code: str,
    sensitive_values: Iterable[str] = (),
) -> tuple[DailyBar, ...]:
    """Parse one decoded KIS response into immutable DailyBar values."""

    secrets = _normalize_sensitive_values(sensitive_values)
    response = _require_object(payload, "response")
    rt_cd = _require_string(response, "rt_cd", "response", secrets=())
    msg_cd = _require_string(response, "msg_cd", "response", secrets=())
    msg1 = _require_string(
        response,
        "msg1",
        "response",
        allow_blank=True,
        secrets=secrets,
    )
    if rt_cd != "0":
        raise KisMarketDataApiError(rt_cd=rt_cd, msg_cd=msg_cd, msg1=msg1)

    if "output2" not in response or response["output2"] is None:
        raise MissingMarketDataFieldError("output2", "response")
    raw_rows = response["output2"]
    if not isinstance(raw_rows, list):
        raise InvalidMarketDataResponseStructure("output2 must be a JSON array.")

    bars: list[DailyBar] = []
    for index, raw_row in enumerate(raw_rows):
        location = f"output2[{index}]"
        row = _require_object(raw_row, location)
        trade_date = _parse_trade_date(row, "stck_bsop_date", location)
        prices = {
            model_field: _parse_decimal(row, kis_field, location)
            for model_field, kis_field in _PRICE_FIELDS.items()
        }
        volume = _parse_volume(row, "acml_vol", location)
        try:
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=prices["open_price"],
                    high_price=prices["high_price"],
                    low_price=prices["low_price"],
                    close_price=prices["close_price"],
                    volume=volume,
                )
            )
        except ValidationError:
            raise MarketDataDomainInvariantError(
                f"KIS daily-price values violate DailyBar invariants at {location}."
            ) from None
    return tuple(bars)


def _require_object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidMarketDataResponseStructure(f"{location} must be a JSON object.")
    return cast(dict[str, Any], value)


def _require_string(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
    *,
    allow_blank: bool = False,
    secrets: tuple[str, ...],
) -> str:
    if field_name not in record:
        raise MissingMarketDataFieldError(field_name, location)
    value = record[field_name]
    if not isinstance(value, str):
        raise InvalidMarketDataResponseStructure(f"{field_name} must be a string at {location}.")
    if not allow_blank and not value.strip():
        raise MissingMarketDataFieldError(field_name, location)
    return _mask_text(value, secrets)


def _required_numeric_text(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
) -> str:
    if field_name not in record:
        raise MissingMarketDataFieldError(field_name, location)
    value = record[field_name]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingMarketDataFieldError(field_name, location)
    if not isinstance(value, str):
        raise InvalidMarketDataNumericFieldError(field_name, location)
    return value


def _parse_trade_date(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
) -> date:
    if field_name not in record:
        raise MissingMarketDataFieldError(field_name, location)
    value = record[field_name]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingMarketDataFieldError(field_name, location)
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        raise InvalidMarketDataDateError(field_name, location)
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise InvalidMarketDataDateError(field_name, location) from None


def _parse_decimal(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
) -> Decimal:
    value = _required_numeric_text(record, field_name, location)
    if _DECIMAL_PATTERN.fullmatch(value) is None:
        raise InvalidMarketDataNumericFieldError(field_name, location)
    return Decimal(value)


def _parse_volume(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
) -> int:
    value = _required_numeric_text(record, field_name, location)
    if _INTEGER_PATTERN.fullmatch(value) is None:
        raise InvalidMarketDataNumericFieldError(field_name, location)
    return int(value)


def _normalize_sensitive_values(sensitive_values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {value for value in sensitive_values if isinstance(value, str) and value},
            key=len,
            reverse=True,
        )
    )


def _mask_text(value: str, secrets: tuple[str, ...]) -> str:
    masked = value
    for secret in secrets:
        masked = masked.replace(secret, _REDACTED)
    return masked


__all__ = ["parse_daily_bars_page"]

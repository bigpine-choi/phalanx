"""Immutable provider-neutral daily market-data models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)


def _reject_binary_float(value: Any) -> Any:
    if isinstance(value, (bool, float)):
        raise ValueError("prices must not be provided as float or bool")
    return value


def _require_finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("prices must be finite")
    return value


def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


PositivePrice = Annotated[
    Decimal,
    BeforeValidator(_reject_binary_float),
    AfterValidator(_require_finite_decimal),
    Field(gt=Decimal("0")),
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]


class DailyBar(BaseModel):
    """One immutable adjusted-price domestic-stock daily OHLCV bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    trade_date: date
    open_price: PositivePrice
    high_price: PositivePrice
    low_price: PositivePrice
    close_price: PositivePrice
    volume: int = Field(strict=True, ge=0)

    @field_validator("trade_date", mode="before")
    @classmethod
    def _require_date_instance(cls, value: Any) -> Any:
        if type(value) is not date:
            raise ValueError("trade_date must be a date instance")
        return value

    @model_validator(mode="after")
    def _validate_ohlc_relationships(self) -> Self:
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("high_price must not be below open_price or close_price")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("low_price must not exceed open_price or close_price")
        if self.low_price > self.high_price:
            raise ValueError("low_price must not exceed high_price")
        return self


__all__ = ["DailyBar", "PositivePrice"]

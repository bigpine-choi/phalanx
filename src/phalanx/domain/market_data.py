"""Immutable provider-neutral historical and current market-data models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
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


class CurrentPriceMarket(StrEnum):
    """Trading-market source requested for a current-price observation."""

    KRX = "KRX"
    NXT = "NXT"
    INTEGRATED = "INTEGRATED"


class CurrentPriceObservation(BaseModel):
    """One immutable REST current-price observation bounded by local timestamps.

    It is not a streaming quote, a provider as-of time, an executable price, or
    evidence that the security is currently tradable. Pydantic ``model_construct``
    is an explicitly unsupported unsafe escape hatch for this validated value.
    Only ordinary human-readable validation text hides rejected inputs;
    structured Pydantic validation details are not safe operational errors.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
    )

    stock_code: str
    current_price: PositivePrice
    market: CurrentPriceMarket
    request_started_at: datetime
    received_at: datetime

    @field_validator("stock_code", mode="before")
    @classmethod
    def _require_exact_stock_code(cls, value: Any) -> Any:
        if type(value) is not str or len(value) != 6 or not value.isascii() or not value.isdigit():
            raise ValueError("stock_code must be exactly six ASCII digits")
        return value

    @field_validator("current_price", mode="before")
    @classmethod
    def _require_exact_decimal_price(cls, value: Any) -> Any:
        if type(value) is not Decimal:
            raise ValueError("current_price must be a Decimal instance")
        return value

    @field_validator("market", mode="before")
    @classmethod
    def _require_market_instance(cls, value: Any) -> Any:
        if type(value) is not CurrentPriceMarket:
            raise ValueError("market must be a CurrentPriceMarket instance")
        return value

    @field_validator("request_started_at", "received_at", mode="before")
    @classmethod
    def _require_aware_datetime(cls, value: Any) -> Any:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamps must be timezone-aware datetime instances")
        return value

    @model_validator(mode="after")
    def _require_ordered_timestamps(self) -> Self:
        if self.received_at.astimezone(UTC) < self.request_started_at.astimezone(UTC):
            raise ValueError("received_at must not be earlier than request_started_at")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy this immutable value without permitting unvalidated updates."""

        if update:
            raise TypeError("CurrentPriceObservation model_copy updates are unsupported.")
        return super().model_copy(deep=deep)


class ValuationPriceBundle(BaseModel):
    """A complete ordered set of current prices for one KRW valuation.

    Pydantic ``model_construct`` is an explicitly unsupported unsafe escape hatch
    for this validated value. Only ordinary human-readable validation text hides
    rejected inputs; structured Pydantic validation details are not safe
    operational errors.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
    )

    stock_codes: tuple[str, ...]
    observations: tuple[CurrentPriceObservation, ...]
    currency: Literal["KRW"]

    @field_validator("stock_codes", mode="before")
    @classmethod
    def _require_exact_stock_code_tuple(cls, value: Any) -> Any:
        if type(value) is not tuple:
            raise ValueError("stock_codes must be a tuple")
        for stock_code in value:
            if (
                type(stock_code) is not str
                or len(stock_code) != 6
                or not stock_code.isascii()
                or not stock_code.isdigit()
            ):
                raise ValueError("stock_codes must contain exactly six ASCII digits")
        return value

    @field_validator("observations", mode="before")
    @classmethod
    def _require_exact_observation_tuple(cls, value: Any) -> Any:
        if type(value) is not tuple:
            raise ValueError("observations must be a tuple")
        if any(type(observation) is not CurrentPriceObservation for observation in value):
            raise ValueError("observations must contain CurrentPriceObservation instances")
        return value

    @model_validator(mode="after")
    def _validate_bundle_coherence(self) -> Self:
        if not self.stock_codes:
            raise ValueError("a valuation-price bundle must contain at least one stock code")
        if len(self.stock_codes) != len(set(self.stock_codes)):
            raise ValueError("stock_codes must not contain duplicates")
        if len(self.observations) != len(self.stock_codes):
            raise ValueError("observations must have the same length as stock_codes")
        observation_codes = tuple(observation.stock_code for observation in self.observations)
        if observation_codes != self.stock_codes:
            raise ValueError("observation stock codes must exactly match stock_codes in order")
        first_market = self.observations[0].market
        if any(observation.market is not first_market for observation in self.observations[1:]):
            raise ValueError("all observations must use one common current-price market")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy this immutable value without permitting unvalidated updates."""

        if update:
            raise TypeError("ValuationPriceBundle model_copy updates are unsupported.")
        return super().model_copy(deep=deep)

    @property
    def valuation_prices(self) -> tuple[Decimal, ...]:
        """Return exact prices in the same order as ``stock_codes``."""

        return tuple(observation.current_price for observation in self.observations)

    @property
    def market(self) -> CurrentPriceMarket:
        """Return the common current-price market."""

        return self.observations[0].market

    @property
    def request_started_at(self) -> datetime:
        """Return the earliest local request-start instant in the bundle."""

        return min(
            (observation.request_started_at for observation in self.observations),
            key=lambda value: value.astimezone(UTC),
        )

    @property
    def received_at(self) -> datetime:
        """Return the latest local response-receipt instant in the bundle."""

        return max(
            (observation.received_at for observation in self.observations),
            key=lambda value: value.astimezone(UTC),
        )

    @property
    def acquisition_span(self) -> timedelta:
        """Return the conservative client-side acquisition interval."""

        return self.received_at.astimezone(UTC) - self.request_started_at.astimezone(UTC)


class DailyBar(BaseModel):
    """One immutable adjusted-price domestic-stock daily OHLCV bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    trade_date: date
    open_price: PositivePrice
    high_price: PositivePrice
    low_price: PositivePrice
    close_price: PositivePrice
    volume: int = Field(strict=True, ge=0)

    @field_validator("trade_date", mode="before")
    @classmethod
    def _require_date_instance(cls, value: Any, info: ValidationInfo) -> Any:
        if info.mode == "json" and isinstance(value, str):
            return date.fromisoformat(value)
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


__all__ = [
    "CurrentPriceMarket",
    "CurrentPriceObservation",
    "DailyBar",
    "PositivePrice",
    "ValuationPriceBundle",
]

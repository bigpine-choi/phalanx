"""Provider-neutral services for historical and current market-data reads."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from pydantic import ValidationError

from phalanx.domain import (
    CurrentPriceMarket,
    CurrentPriceObservation,
    DailyBar,
    KoreanStock,
    ValuationPriceBundle,
)
from phalanx.market_data.errors import (
    CurrentPriceObservationReadError,
    InvalidValuationPriceAcquisitionRecencyError,
    InvalidValuationPriceRequestError,
    UniverseReaderRequiredError,
    UniverseStockMarketDataError,
    UnsupportedCurrentPriceMarketError,
    ValuationPriceBundleAcquisitionTooOldError,
    ValuationPriceBundleCoherenceError,
)
from phalanx.market_data.validation import validate_daily_date_range


class DailyBarReader(Protocol):
    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]: ...


class UniverseReader(Protocol):
    def list_stocks(self) -> tuple[KoreanStock, ...]: ...


class CurrentPriceReader(Protocol):
    def fetch_current_price(
        self,
        stock_code: str,
        market: CurrentPriceMarket,
    ) -> CurrentPriceObservation: ...


@dataclass(frozen=True, slots=True)
class StockDailyBars:
    """One active universe stock and its complete immutable daily history."""

    stock: KoreanStock
    bars: tuple[DailyBar, ...]


class MarketDataService:
    """Coordinate market-data reads without persistence or portfolio decisions."""

    def __init__(
        self,
        daily_bar_reader: DailyBarReader,
        universe_reader: UniverseReader | None = None,
    ) -> None:
        self._daily_bar_reader = daily_bar_reader
        self._universe_reader = universe_reader

    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]:
        """Fetch one stock through the provider-neutral service boundary."""

        return self._daily_bar_reader.fetch_daily_bars(stock_code, start, end)

    def fetch_active_universe(
        self,
        start: date,
        end: date,
    ) -> tuple[StockDailyBars, ...]:
        """Sequentially fetch every enabled stock and never hide a stock failure."""

        validated_start, validated_end = validate_daily_date_range(start, end)
        if self._universe_reader is None:
            raise UniverseReaderRequiredError("활성 유니버스 조회기가 구성되지 않았습니다.")

        results: list[StockDailyBars] = []
        for stock in self._universe_reader.list_stocks():
            if not stock.enabled:
                continue
            try:
                bars = self._daily_bar_reader.fetch_daily_bars(
                    stock.stock_code,
                    validated_start,
                    validated_end,
                )
            except Exception as error:
                raise UniverseStockMarketDataError(
                    stock.stock_code,
                    stock.stock_name,
                ) from error
            results.append(StockDailyBars(stock=stock, bars=bars))
        return tuple(results)


class ValuationPriceService:
    """Collect a complete, ordered valuation bundle without portfolio decisions."""

    def __init__(self, current_price_reader: CurrentPriceReader) -> None:
        self._current_price_reader = current_price_reader

    def fetch_valuation_price_bundle(
        self,
        stock_codes: tuple[str, ...],
        *,
        market: CurrentPriceMarket,
        maximum_acquisition_span: timedelta,
    ) -> ValuationPriceBundle:
        """Read every requested price sequentially or return no bundle.

        Atomicity applies only to this return boundary; completed external reads
        cannot be rolled back.
        """

        _validate_valuation_price_request(
            stock_codes,
            market=market,
            maximum_acquisition_span=maximum_acquisition_span,
        )

        observations: list[CurrentPriceObservation] = []
        for request_index, stock_code in enumerate(stock_codes):
            observation: object | None = None
            read_failed = False
            try:
                observation = self._current_price_reader.fetch_current_price(stock_code, market)
            except UnsupportedCurrentPriceMarketError:
                raise
            except Exception:
                read_failed = True

            if read_failed:
                raise CurrentPriceObservationReadError(stock_code, request_index)
            if type(observation) is not CurrentPriceObservation:
                observation = None
                raise ValuationPriceBundleCoherenceError(
                    "The current-price reader returned an invalid observation type."
                )
            validated_observation = _reconstruct_current_price_observation(observation)
            observation = None
            if validated_observation is None:
                raise ValuationPriceBundleCoherenceError(
                    "The current-price reader returned an invalid observation."
                )
            if validated_observation.stock_code != stock_code:
                raise ValuationPriceBundleCoherenceError(
                    "A current-price observation did not match its requested stock code."
                )
            if validated_observation.market is not market:
                raise ValuationPriceBundleCoherenceError(
                    "A current-price observation did not match the requested market."
                )
            observations.append(validated_observation)

        bundle: ValuationPriceBundle | None = None
        with suppress(ValidationError):
            bundle = ValuationPriceBundle(
                stock_codes=stock_codes,
                observations=tuple(observations),
                currency="KRW",
            )
        if bundle is None:
            raise ValuationPriceBundleCoherenceError(
                "The current-price observations could not form a coherent valuation bundle."
            )
        if bundle.acquisition_span > maximum_acquisition_span:
            raise ValuationPriceBundleCoherenceError(
                "The valuation-price acquisition span exceeded its configured maximum."
            )
        return bundle


def validate_valuation_price_bundle_acquisition_recency(
    bundle: ValuationPriceBundle,
    *,
    evaluated_at: datetime,
    maximum_acquisition_age: timedelta,
) -> ValuationPriceBundle:
    """Require recent client acquisition without claiming an exchange trade time.

    This evaluates only the locally bounded REST acquisition interval. A recent
    acquisition can still contain an old price after market close, during a
    suspension, or when there have been no recent trades.
    """

    if type(bundle) is not ValuationPriceBundle:
        raise InvalidValuationPriceAcquisitionRecencyError("bundle must be a ValuationPriceBundle")
    validated_bundle = _reconstruct_valuation_price_bundle(bundle)
    if validated_bundle is None:
        del bundle
        raise InvalidValuationPriceAcquisitionRecencyError(
            "bundle must contain valid immutable valuation-price values"
        )
    bundle = validated_bundle
    if (
        type(evaluated_at) is not datetime
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise InvalidValuationPriceAcquisitionRecencyError(
            "evaluated_at must be a timezone-aware datetime"
        )
    if type(maximum_acquisition_age) is not timedelta or maximum_acquisition_age < timedelta(0):
        raise InvalidValuationPriceAcquisitionRecencyError(
            "maximum_acquisition_age must be a nonnegative timedelta"
        )
    evaluated_at_utc = evaluated_at.astimezone(UTC)
    if evaluated_at_utc < bundle.received_at.astimezone(UTC):
        raise InvalidValuationPriceAcquisitionRecencyError(
            "evaluated_at must not be earlier than the latest response receipt"
        )

    acquisition_age = evaluated_at_utc - bundle.request_started_at.astimezone(UTC)
    if acquisition_age > maximum_acquisition_age:
        raise ValuationPriceBundleAcquisitionTooOldError(
            acquisition_age,
            maximum_acquisition_age,
        )
    return bundle


def _validate_valuation_price_request(
    stock_codes: object,
    *,
    market: object,
    maximum_acquisition_span: object,
) -> None:
    if type(stock_codes) is not tuple:
        raise InvalidValuationPriceRequestError("stock_codes must be a tuple")
    if not stock_codes:
        raise InvalidValuationPriceRequestError(
            "a valuation-price request must contain at least one stock code"
        )
    for stock_code in stock_codes:
        if (
            type(stock_code) is not str
            or len(stock_code) != 6
            or not stock_code.isascii()
            or not stock_code.isdigit()
        ):
            raise InvalidValuationPriceRequestError(
                "stock_codes must contain exactly six ASCII digits"
            )
    if len(stock_codes) != len(set(stock_codes)):
        raise InvalidValuationPriceRequestError("stock_codes must not contain duplicates")
    if type(market) is not CurrentPriceMarket:
        raise InvalidValuationPriceRequestError("market must be a CurrentPriceMarket instance")
    if type(maximum_acquisition_span) is not timedelta or maximum_acquisition_span <= timedelta(0):
        raise InvalidValuationPriceRequestError(
            "maximum_acquisition_span must be a positive timedelta"
        )


def _reconstruct_current_price_observation(
    observation: CurrentPriceObservation,
) -> CurrentPriceObservation | None:
    """Return a fresh validated observation without propagating forged state."""

    reconstructed: CurrentPriceObservation | None = None
    with suppress(Exception):
        reconstructed = CurrentPriceObservation(
            stock_code=observation.stock_code,
            current_price=observation.current_price,
            market=observation.market,
            request_started_at=observation.request_started_at,
            received_at=observation.received_at,
        )
    return reconstructed


def _reconstruct_valuation_price_bundle(
    bundle: ValuationPriceBundle,
) -> ValuationPriceBundle | None:
    """Return a fresh validated bundle without propagating forged state."""

    reconstructed: ValuationPriceBundle | None = None
    with suppress(Exception):
        reconstructed = ValuationPriceBundle(
            stock_codes=bundle.stock_codes,
            observations=bundle.observations,
            currency=bundle.currency,
        )
    return reconstructed


__all__ = [
    "CurrentPriceReader",
    "DailyBarReader",
    "MarketDataService",
    "StockDailyBars",
    "UniverseReader",
    "ValuationPriceService",
    "validate_valuation_price_bundle_acquisition_recency",
]

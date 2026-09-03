"""Provider-neutral errors for read-only market-data use cases."""

from __future__ import annotations

from datetime import timedelta

from phalanx.domain.market_data import CurrentPriceMarket


class MarketDataError(Exception):
    """Base class for expected market-data failures safe to show to users."""


class InvalidMarketDataRequestError(MarketDataError):
    """Base class for invalid stock-code or date-range requests."""


class InvalidMarketDataStockCodeError(InvalidMarketDataRequestError):
    """Raised when a requested stock code is not six ASCII digits."""


class InvalidMarketDataRangeError(InvalidMarketDataRequestError):
    """Raised when a daily market-data date range is invalid."""


class InvalidValuationPriceRequestError(InvalidMarketDataRequestError):
    """Raised when a valuation-price request is invalid before any read."""


class UnsupportedCurrentPriceMarketError(InvalidValuationPriceRequestError):
    """Raised when the requested market is deliberately unsupported."""

    def __init__(self, market: CurrentPriceMarket) -> None:
        self.market = market
        super().__init__(f"Current-price market {market.value} is not supported.")


class MarketDataServiceError(MarketDataError):
    """Base class for failures while coordinating market-data use cases."""


class UniverseReaderRequiredError(MarketDataServiceError):
    """Raised when an active-universe query has no universe reader."""


class UniverseStockMarketDataError(MarketDataServiceError):
    """Report exactly which active universe stock failed."""

    def __init__(self, stock_code: str, stock_name: str) -> None:
        self.stock_code = stock_code
        self.stock_name = stock_name
        super().__init__(
            f"종목코드 {stock_code} ({stock_name})의 일별 시세 조회를 완료하지 못했습니다."
        )


class CurrentPriceObservationReadError(MarketDataServiceError):
    """Report the zero-based failed request without retaining an arbitrary reader error."""

    def __init__(self, stock_code: str, request_index: int) -> None:
        self.stock_code = stock_code
        self.request_index = request_index
        super().__init__(
            "A current-price observation could not be read "
            f"for stock code {stock_code} at request index {request_index}."
        )


class ValuationPriceBundleCoherenceError(MarketDataServiceError):
    """Raised when complete reads cannot form one coherent ordered bundle."""


class InvalidValuationPriceAcquisitionRecencyError(MarketDataServiceError):
    """Raised when acquisition-recency evaluation inputs are invalid."""


class ValuationPriceBundleAcquisitionTooOldError(MarketDataServiceError):
    """Raised when a bundle exceeds the explicitly allowed acquisition age."""

    def __init__(
        self,
        acquisition_age: timedelta,
        maximum_acquisition_age: timedelta,
    ) -> None:
        self.acquisition_age = acquisition_age
        self.maximum_acquisition_age = maximum_acquisition_age
        super().__init__("The valuation-price bundle acquisition is too old.")


__all__ = [
    "CurrentPriceObservationReadError",
    "InvalidMarketDataRangeError",
    "InvalidMarketDataRequestError",
    "InvalidMarketDataStockCodeError",
    "InvalidValuationPriceAcquisitionRecencyError",
    "InvalidValuationPriceRequestError",
    "MarketDataError",
    "MarketDataServiceError",
    "UniverseReaderRequiredError",
    "UniverseStockMarketDataError",
    "UnsupportedCurrentPriceMarketError",
    "ValuationPriceBundleAcquisitionTooOldError",
    "ValuationPriceBundleCoherenceError",
]

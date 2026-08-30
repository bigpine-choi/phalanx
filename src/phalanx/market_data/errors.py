"""Provider-neutral errors for daily market-data use cases."""


class MarketDataError(Exception):
    """Base class for expected market-data failures safe to show to users."""


class InvalidMarketDataRequestError(MarketDataError):
    """Base class for invalid stock-code or date-range requests."""


class InvalidMarketDataStockCodeError(InvalidMarketDataRequestError):
    """Raised when a requested stock code is not six ASCII digits."""


class InvalidMarketDataRangeError(InvalidMarketDataRequestError):
    """Raised when a daily market-data date range is invalid."""


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


__all__ = [
    "InvalidMarketDataRangeError",
    "InvalidMarketDataRequestError",
    "InvalidMarketDataStockCodeError",
    "MarketDataError",
    "MarketDataServiceError",
    "UniverseReaderRequiredError",
    "UniverseStockMarketDataError",
]

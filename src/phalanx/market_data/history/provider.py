"""Adapt the existing KIS reader without duplicating pagination or retry logic."""

from datetime import date

from phalanx.domain.market_data import DailyBar
from phalanx.kis.errors import (
    KisMarketDataApiError,
    KisMarketDataAuthenticationError,
    KisMarketDataClientError,
    KisMarketDataHttpError,
    KisMarketDataParsingError,
    KisMarketDataRateLimitError,
)
from phalanx.kis.market_data_client import KisDailyPriceClient
from phalanx.market_data.history.errors import HistoryFetchError


class KisHistoryReader:
    def __init__(self, client: KisDailyPriceClient) -> None:
        self._client = client

    def fetch_daily_bars(self, stock_code: str, start: date, end: date) -> tuple[DailyBar, ...]:
        try:
            return self._client.fetch_daily_bars(stock_code, start, end)
        except KisMarketDataAuthenticationError as error:
            raise HistoryFetchError("AUTHENTICATION_FAILED", str(error), common=True) from None
        except KisMarketDataRateLimitError as error:
            raise HistoryFetchError("RATE_LIMIT_EXHAUSTED", str(error), common=True) from None
        except KisMarketDataApiError as error:
            raise HistoryFetchError(f"KIS_API_{error.msg_cd}", str(error)) from None
        except KisMarketDataHttpError as error:
            if error.status_code in (403, 429):
                code = "AUTHENTICATION_FAILED" if error.status_code == 403 else "HTTP_RATE_LIMIT"
                raise HistoryFetchError(code, str(error), common=True) from None
            raise HistoryFetchError(type(error).__name__, str(error)) from None
        except (KisMarketDataClientError, KisMarketDataParsingError) as error:
            # These exceptions already contain bounded, sanitized KIS diagnostics.
            raise HistoryFetchError(type(error).__name__, str(error)) from None
        except Exception:
            raise HistoryFetchError(
                "UNEXPECTED_PROVIDER_ERROR",
                "공급자 호출 중 예상하지 못한 오류로 작업을 중단합니다.",
                common=True,
            ) from None

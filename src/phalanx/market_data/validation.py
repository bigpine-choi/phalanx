"""Separate daily-history and numeric current-price identifier contracts."""

from __future__ import annotations

import re
from datetime import date

from phalanx.market_data.errors import (
    InvalidMarketDataRangeError,
    InvalidMarketDataStockCodeError,
)

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


def validate_market_data_stock_code(stock_code: object) -> str:
    """Return an exact six-digit domestic stock code."""

    if not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None:
        raise InvalidMarketDataStockCodeError(
            "시세 조회 종목코드는 공백 없는 6자리 숫자여야 합니다. 예: 005930"
        )
    return stock_code


def validate_daily_date_range(start: object, end: object) -> tuple[date, date]:
    """Return an ordered pair of real date objects."""

    if type(start) is not date or type(end) is not date:
        raise InvalidMarketDataRangeError("시작일과 종료일은 YYYY-MM-DD 날짜여야 합니다.")
    if start > end:
        raise InvalidMarketDataRangeError("시작일은 종료일보다 늦을 수 없습니다.")
    return start, end


def validate_daily_stock_code(stock_code: object) -> str:
    """Accept an exact ASCII identifier; provider query support is a separate matter."""
    if not isinstance(stock_code, str) or re.fullmatch(r"[0-9A-Z]{6}", stock_code) is None:
        raise InvalidMarketDataStockCodeError(
            "일봉 종목코드는 정확한 ASCII 숫자·대문자 6자리여야 합니다. 예: 005930, 0001A0"
        )
    return stock_code


__all__ = [
    "validate_daily_date_range",
    "validate_daily_stock_code",
    "validate_market_data_stock_code",
]

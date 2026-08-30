"""Immutable provider-neutral portfolio analysis models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from phalanx.portfolio.errors import InvalidAlignedReturnMatrixError

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


@dataclass(frozen=True, slots=True)
class AlignedReturnMatrix:
    """Daily simple returns aligned to common close dates.

    Each row belongs to the corresponding return end date and each column
    belongs to the stock code at the same position in ``stock_codes``.
    """

    stock_codes: tuple[str, ...]
    dates: tuple[date, ...]
    values: tuple[tuple[Decimal, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stock_codes, tuple):
            raise InvalidAlignedReturnMatrixError("stock_codes는 tuple이어야 합니다.")
        if not isinstance(self.dates, tuple):
            raise InvalidAlignedReturnMatrixError("dates는 tuple이어야 합니다.")
        if not isinstance(self.values, tuple):
            raise InvalidAlignedReturnMatrixError("values는 tuple이어야 합니다.")
        if not self.stock_codes:
            raise InvalidAlignedReturnMatrixError(
                "수익률 행렬에는 최소 1개의 종목코드가 필요합니다."
            )
        if not self.dates or not self.values:
            raise InvalidAlignedReturnMatrixError(
                "수익률 행렬에는 최소 1개의 수익률 관측치가 필요합니다."
            )

        seen_codes: set[str] = set()
        for stock_code in self.stock_codes:
            if not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None:
                raise InvalidAlignedReturnMatrixError(
                    "stock_codes는 공백 없는 6자리 숫자여야 합니다."
                )
            if stock_code in seen_codes:
                raise InvalidAlignedReturnMatrixError(
                    f"stock_codes에 종목코드 {stock_code}가 중복되었습니다."
                )
            seen_codes.add(stock_code)

        previous_date: date | None = None
        seen_dates: set[date] = set()
        for return_date in self.dates:
            if type(return_date) is not date:
                raise InvalidAlignedReturnMatrixError("dates는 date 값이어야 합니다.")
            if return_date in seen_dates:
                raise InvalidAlignedReturnMatrixError("dates에 중복 날짜가 있습니다.")
            if previous_date is not None and return_date <= previous_date:
                raise InvalidAlignedReturnMatrixError("dates는 엄격한 오름차순이어야 합니다.")
            seen_dates.add(return_date)
            previous_date = return_date

        if len(self.values) != len(self.dates):
            raise InvalidAlignedReturnMatrixError("values 행 수는 dates 길이와 일치해야 합니다.")
        for row in self.values:
            if not isinstance(row, tuple):
                raise InvalidAlignedReturnMatrixError("values의 각 행은 tuple이어야 합니다.")
            if len(row) != len(self.stock_codes):
                raise InvalidAlignedReturnMatrixError(
                    "values 열 수는 stock_codes 길이와 일치해야 합니다."
                )
            if any(not isinstance(value, Decimal) or not value.is_finite() for value in row):
                raise InvalidAlignedReturnMatrixError(
                    "values는 유한한 Decimal 값만 포함해야 합니다."
                )


__all__ = ["AlignedReturnMatrix"]

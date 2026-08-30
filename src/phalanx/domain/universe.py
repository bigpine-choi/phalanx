"""Immutable domain model for one human-curated Korean stock candidate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from phalanx.universe.errors import (
    InvalidEnabledStateError,
    InvalidMarketError,
    InvalidStockCodeError,
    InvalidStockNameError,
    InvalidStockNoteError,
)

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_MAX_STOCK_NAME_LENGTH = 200
_MAX_STOCK_NOTE_LENGTH = 2_000


class StockMarket(StrEnum):
    """Supported Korean exchange markets for investment candidates."""

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"

    @classmethod
    def parse(cls, value: object) -> StockMarket:
        """Parse an exact public market value into the domain enum."""

        if not isinstance(value, str):
            raise InvalidMarketError("시장은 KOSPI 또는 KOSDAQ이어야 합니다.")
        try:
            return cls(value)
        except ValueError:
            raise InvalidMarketError(
                f"지원하지 않는 시장 '{value}'입니다. KOSPI 또는 KOSDAQ을 입력해 주세요."
            ) from None


def validate_stock_code(stock_code: object) -> str:
    """Return a valid domestic stock code without silently normalizing it."""

    if not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None:
        raise InvalidStockCodeError("종목코드는 공백 없는 6자리 숫자여야 합니다. 예: 005930")
    return stock_code


@dataclass(frozen=True, slots=True)
class KoreanStock:
    """One immutable, provider-neutral Korean stock universe entry."""

    stock_code: str
    stock_name: str
    market: StockMarket
    enabled: bool = True
    note: str | None = None

    def __post_init__(self) -> None:
        validate_stock_code(self.stock_code)

        if not isinstance(self.stock_name, str):
            raise InvalidStockNameError("종목명은 비어 있지 않은 문자열이어야 합니다.")
        normalized_name = self.stock_name.strip()
        if not normalized_name:
            raise InvalidStockNameError("종목명은 비어 있지 않은 문자열이어야 합니다.")
        if len(normalized_name) > _MAX_STOCK_NAME_LENGTH:
            raise InvalidStockNameError(
                f"종목명은 {_MAX_STOCK_NAME_LENGTH}자를 초과할 수 없습니다."
            )
        object.__setattr__(self, "stock_name", normalized_name)

        if not isinstance(self.market, StockMarket):
            raise InvalidMarketError("시장은 KOSPI 또는 KOSDAQ이어야 합니다.")
        if type(self.enabled) is not bool:
            raise InvalidEnabledStateError("활성화 여부는 true 또는 false여야 합니다.")

        if self.note is None:
            return
        if not isinstance(self.note, str):
            raise InvalidStockNoteError("메모는 문자열이거나 비어 있어야 합니다.")
        normalized_note = self.note.strip()
        if len(normalized_note) > _MAX_STOCK_NOTE_LENGTH:
            raise InvalidStockNoteError(f"메모는 {_MAX_STOCK_NOTE_LENGTH}자를 초과할 수 없습니다.")
        object.__setattr__(self, "note", normalized_note or None)


__all__ = ["KoreanStock", "StockMarket", "validate_stock_code"]

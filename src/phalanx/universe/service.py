"""Application service for the human-curated investment universe."""

from __future__ import annotations

from phalanx.domain import KoreanStock, StockMarket
from phalanx.domain.universe import validate_stock_code
from phalanx.universe.repository import UniverseRepository


class UniverseService:
    """Expose provider-neutral universe use cases to CLI and future GUI callers."""

    def __init__(self, repository: UniverseRepository) -> None:
        self._repository = repository

    def list_stocks(self) -> tuple[KoreanStock, ...]:
        """Return all candidates in their human-managed registration order."""

        return self._repository.list_all()

    def add_stock(
        self,
        stock_code: str,
        stock_name: str,
        market: str | StockMarket,
        *,
        note: str | None = None,
    ) -> KoreanStock:
        """Validate and register one enabled investment candidate."""

        parsed_market = market if isinstance(market, StockMarket) else StockMarket.parse(market)
        stock = KoreanStock(
            stock_code=stock_code,
            stock_name=stock_name,
            market=parsed_market,
            enabled=True,
            note=note,
        )
        return self._repository.add(stock)

    def enable_stock(self, stock_code: str) -> KoreanStock:
        """Enable one existing candidate."""

        validated_code = validate_stock_code(stock_code)
        return self._repository.set_enabled(validated_code, enabled=True)

    def disable_stock(self, stock_code: str) -> KoreanStock:
        """Disable one existing candidate without deleting its metadata."""

        validated_code = validate_stock_code(stock_code)
        return self._repository.set_enabled(validated_code, enabled=False)

    def remove_stock(self, stock_code: str) -> KoreanStock:
        """Remove one existing candidate from the universe."""

        validated_code = validate_stock_code(stock_code)
        return self._repository.remove(validated_code)


__all__ = ["UniverseService"]

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from phalanx.domain import KoreanStock, StockMarket
from phalanx.universe.errors import (
    DuplicateStockError,
    InvalidMarketError,
    InvalidStockCodeError,
    InvalidStockNameError,
    StockNotFoundError,
)
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> UniverseService:
    return UniverseService(JsonUniverseRepository(tmp_path / "universe" / "universe.json"))


def test_korean_stock_is_immutable_and_normalizes_human_text() -> None:
    stock = KoreanStock(
        stock_code="005930",
        stock_name="  삼성전자  ",
        market=StockMarket.KOSPI,
        enabled=True,
        note="  장기 관찰  ",
    )

    assert stock == KoreanStock(
        stock_code="005930",
        stock_name="삼성전자",
        market=StockMarket.KOSPI,
        enabled=True,
        note="장기 관찰",
    )
    with pytest.raises(FrozenInstanceError):
        stock.enabled = False


def test_blank_note_is_normalized_to_none() -> None:
    stock = KoreanStock(
        stock_code="035720",
        stock_name="카카오",
        market=StockMarket.KOSDAQ,
        note="   ",
    )

    assert stock.note is None


@pytest.mark.parametrize(
    "stock_code",
    (
        "5930",
        "0005930",
        "00593A",
        " 005930",
        "005930 ",
        "".join(chr(value) for value in (0xFF10, 0xFF10, 0xFF15, 0xFF19, 0xFF13, 0xFF10)),
        "",
    ),
)
def test_stock_code_requires_exactly_six_ascii_digits(stock_code: str) -> None:
    with pytest.raises(InvalidStockCodeError, match="6자리 숫자"):
        KoreanStock(
            stock_code=stock_code,
            stock_name="삼성전자",
            market=StockMarket.KOSPI,
        )


@pytest.mark.parametrize("market", ("kospi", "KOSPI ", "KONEX", "", 1, None))
def test_market_parser_accepts_only_exact_supported_markets(market: object) -> None:
    with pytest.raises(InvalidMarketError, match=r"KOSPI.*KOSDAQ"):
        StockMarket.parse(market)


def test_stock_name_must_not_be_blank() -> None:
    with pytest.raises(InvalidStockNameError, match="종목명"):
        KoreanStock(
            stock_code="005930",
            stock_name="   ",
            market=StockMarket.KOSPI,
        )


def test_service_runs_complete_add_toggle_remove_lifecycle(tmp_path: Path) -> None:
    service = _service(tmp_path)

    added = service.add_stock(
        "005930",
        "삼성전자",
        "KOSPI",
        note="반도체 대형주",
    )
    disabled = service.disable_stock("005930")
    disabled_again = service.disable_stock("005930")
    enabled = service.enable_stock("005930")
    removed = service.remove_stock("005930")

    assert added.enabled is True
    assert disabled.enabled is False
    assert disabled_again == disabled
    assert enabled.enabled is True
    assert removed == enabled
    assert service.list_stocks() == ()


def test_service_preserves_human_registration_order(tmp_path: Path) -> None:
    service = _service(tmp_path)

    service.add_stock("035720", "카카오", StockMarket.KOSDAQ)
    service.add_stock("005930", "삼성전자", StockMarket.KOSPI)

    assert tuple(stock.stock_code for stock in service.list_stocks()) == (
        "035720",
        "005930",
    )


def test_service_rejects_duplicate_stock_code(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.add_stock("005930", "삼성전자", "KOSPI")

    with pytest.raises(DuplicateStockError, match=r"이미.*등록"):
        service.add_stock("005930", "다른 이름", "KOSDAQ")


@pytest.mark.parametrize("operation", ("enable_stock", "disable_stock", "remove_stock"))
def test_service_reports_missing_stock_with_dedicated_error(
    tmp_path: Path,
    operation: str,
) -> None:
    service = _service(tmp_path)

    with pytest.raises(StockNotFoundError, match="등록되어 있지 않습니다"):
        getattr(service, operation)("005930")


def test_service_validates_code_before_repository_mutation(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(InvalidStockCodeError, match="6자리 숫자"):
        service.enable_stock("5930")

    assert not (tmp_path / "universe").exists()


def test_universe_layers_have_no_kis_or_network_surface() -> None:
    sources = [ROOT / "src" / "phalanx" / "domain" / "universe.py"]
    sources.extend((ROOT / "src" / "phalanx" / "universe").rglob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    for forbidden in ("httpx", "requests", "phalanx.kis", "openapi.koreainvestment.com"):
        assert forbidden not in combined

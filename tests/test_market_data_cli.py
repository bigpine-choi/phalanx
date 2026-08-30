from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import DailyBar, KoreanStock, StockMarket
from phalanx.kis.errors import KisMarketDataProtocolError
from phalanx.kis.market_data_client import (
    KisRateLimitCallback,
    KisRateLimitNotification,
)
from phalanx.market_data.errors import (
    InvalidMarketDataRangeError,
    UniverseStockMarketDataError,
)
from phalanx.market_data.service import StockDailyBars

START = date(2026, 8, 1)
END = date(2026, 8, 31)


def _bar(stock_code: str, trade_date: date, close_price: str) -> DailyBar:
    close = Decimal(close_price)
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=close,
        high_price=close + Decimal("10"),
        low_price=close - Decimal("10"),
        close_price=close,
        volume=1000,
    )


def test_daily_command_prints_required_range_and_close_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, date, date]] = []
    bars = (
        _bar("005930", date(2026, 8, 3), "70000.25"),
        _bar("005930", date(2026, 8, 28), "72000.75"),
    )

    def fake_runner(
        stock_code: str,
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[DailyBar, ...]:
        assert rate_limit_callback is not None
        calls.append((stock_code, start, end))
        return bars

    monkeypatch.setattr(cli, "run_production_daily_market_data", fake_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "daily",
            "005930",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert calls == [("005930", START, END)]
    for expected in (
        "KIS 국내주식 일별 시세 조회 시작 · READ ONLY",
        "조회 종목: 005930",
        "시작일: 2026-08-01",
        "종료일: 2026-08-31",
        "조회 건수",
        "2건",
        "최초 거래일",
        "2026-08-03",
        "최종 거래일",
        "2026-08-28",
        "최초 종가",
        "70,000.25",
        "최종 종가",
        "72,000.75",
    ):
        assert expected in result.stdout
    assert result.stderr == ""


def test_daily_command_renders_an_empty_response_without_fabricating_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_production_daily_market_data",
        lambda stock_code, start, end, *, rate_limit_callback=None: (),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "daily",
            "005930",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert "조회 건수" in result.stdout
    assert "0건" in result.stdout
    assert "없음" in result.stdout


@pytest.mark.parametrize(
    ("command", "runner_name"),
    (
        (["market-data", "daily", "005930"], "run_production_daily_market_data"),
        (["market-data", "universe"], "run_production_universe_market_data"),
    ),
)
def test_market_data_commands_announce_before_calling_network_runner(
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    runner_name: str,
) -> None:
    events: list[str] = []
    original_renderer = cli.render_market_data_start

    def recording_renderer(
        target: str,
        start: str,
        end: str,
        console: Console,
    ) -> None:
        events.append("start")
        original_renderer(target, start, end, console)

    def fake_runner(
        *args: object,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[object, ...]:
        assert rate_limit_callback is not None
        events.append("runner")
        return ()

    monkeypatch.setattr(cli, "render_market_data_start", recording_renderer)
    monkeypatch.setattr(cli, runner_name, fake_runner)

    result = CliRunner().invoke(
        cli.app,
        [*command, "--start", "2026-08-01", "--end", "2026-08-31"],
        color=False,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert result.stdout.startswith("KIS 국내주식 일별 시세 조회 시작 · READ ONLY")


def test_cli_renders_secret_free_rate_limit_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = (
        "synthetic-app-key",
        "synthetic-app-secret",
        "synthetic-access-token",
        "12345678-01",
    )

    def fake_runner(
        stock_code: str,
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[DailyBar, ...]:
        assert stock_code == "000660"
        assert (start, end) == (START, END)
        assert rate_limit_callback is not None
        rate_limit_callback(
            KisRateLimitNotification(
                stock_code=stock_code,
                attempt_number=1,
                max_attempts=3,
                wait_seconds=61.0,
            )
        )
        return ()

    monkeypatch.setattr(cli, "run_production_daily_market_data", fake_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "daily",
            "000660",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert "KIS 호출 제한: 000660 · 61초 후 재시도 (1/3)" in result.stdout
    combined_output = result.stdout + result.stderr
    assert all(secret not in combined_output for secret in secrets)


def test_universe_command_prints_one_summary_row_per_active_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samsung = KoreanStock("005930", "삼성전자", StockMarket.KOSPI)
    jyp = KoreanStock("035900", "JYP Ent.", StockMarket.KOSDAQ)
    expected = (
        StockDailyBars(
            samsung,
            (
                _bar("005930", date(2026, 8, 3), "70000"),
                _bar("005930", date(2026, 8, 28), "72000"),
            ),
        ),
        StockDailyBars(jyp, ()),
    )
    calls: list[tuple[date, date]] = []

    def fake_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[StockDailyBars, ...]:
        assert rate_limit_callback is not None
        calls.append((start, end))
        return expected

    monkeypatch.setattr(cli, "run_production_universe_market_data", fake_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "universe",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert calls == [(START, END)]
    for expected_text in (
        "KIS 국내주식 일별 시세 조회 시작 · READ ONLY",
        "조회 대상: 활성 유니버스",
        "시작일: 2026-08-01",
        "종료일: 2026-08-31",
        "활성 유니버스 일별 시세",
        "005930",
        "삼성전자",
        "2건",
        "2026-08-03",
        "2026-08-28",
        "035900",
        "JYP Ent.",
        "0건",
    ):
        assert expected_text in result.stdout


def test_universe_command_reports_no_active_stocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_production_universe_market_data",
        lambda start, end, *, rate_limit_callback=None: (),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "universe",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert "활성 투자 후보가 없습니다" in result.stdout


def test_universe_command_identifies_the_stock_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[StockDailyBars, ...]:
        raise UniverseStockMarketDataError("035900", "JYP Ent.")

    monkeypatch.setattr(cli, "run_production_universe_market_data", failing_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "universe",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA
    assert "조회 대상: 활성 유니버스" in result.stdout
    assert "시세 조회 오류" in result.stderr
    assert "035900" in result.stderr
    assert "JYP Ent." in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "error",
    (
        InvalidMarketDataRangeError("시작일은 종료일보다 늦을 수 없습니다."),
        KisMarketDataProtocolError("synthetic pagination failure"),
    ),
)
def test_daily_command_reports_expected_errors_with_stable_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def failing_runner(
        stock_code: str,
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[DailyBar, ...]:
        raise error

    monkeypatch.setattr(cli, "run_production_daily_market_data", failing_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "daily",
            "005930",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA
    assert "시세 조회 오류" in result.stderr
    assert str(error) in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("start", "end", "expected_message"),
    (
        ("2026-02-30", "2026-08-31", "실제 날짜"),
        ("20260801", "2026-08-31", "YYYY-MM-DD"),
        ("2026-08-31", "2026-08-01", "늦을 수 없습니다"),
    ),
)
def test_daily_command_rejects_invalid_dates_before_production_assembly(
    monkeypatch: pytest.MonkeyPatch,
    start: str,
    end: str,
    expected_message: str,
) -> None:
    def unexpected(
        stock_code: str,
        parsed_start: date,
        parsed_end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> tuple[DailyBar, ...]:
        raise AssertionError(
            f"unexpected production call: {stock_code} {parsed_start} {parsed_end}"
        )

    monkeypatch.setattr(cli, "run_production_daily_market_data", unexpected)

    result = CliRunner().invoke(
        cli.app,
        [
            "market-data",
            "daily",
            "005930",
            "--start",
            start,
            "--end",
            end,
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA
    assert expected_message in result.stderr
    assert "Traceback" not in result.stderr


def test_market_data_help_exposes_only_read_only_daily_workflows() -> None:
    result = CliRunner().invoke(cli.app, ["market-data", "--help"], color=False)

    assert result.exit_code == 0
    assert "READ ONLY" in result.stdout
    assert "daily" in result.stdout
    assert "universe" in result.stdout
    for forbidden in ("order", "buy", "sell", "optimize", "persist"):
        assert forbidden not in result.stdout.lower()


def test_daily_help_requires_iso_date_options_without_environment_switch() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["market-data", "daily", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "YYYY-MM-DD" in result.stdout
    for forbidden in ("--environment", "--paper", "--demo", "--real"):
        assert forbidden not in result.stdout

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import AlignedReturnMatrix
from phalanx.kis.market_data_client import (
    KisRateLimitCallback,
    KisRateLimitNotification,
)
from phalanx.portfolio.errors import (
    EmptyReturnUniverseError,
    EmptyStockHistoryError,
    InsufficientCommonObservationsError,
)

START = date(2026, 8, 1)
END = date(2026, 8, 31)


def _matrix() -> AlignedReturnMatrix:
    return AlignedReturnMatrix(
        stock_codes=("000660", "005930"),
        dates=(date(2026, 8, 4), date(2026, 8, 5)),
        values=(
            (Decimal("0.1"), Decimal("-0.2")),
            (Decimal("0.05"), Decimal("0.3")),
        ),
    )


def test_returns_command_announces_before_network_and_renders_matrix_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    calls: list[tuple[date, date]] = []
    original_renderer = cli.render_portfolio_returns_start

    def recording_renderer(start: str, end: str, console: Console) -> None:
        events.append("start")
        original_renderer(start, end, console)

    def fake_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AlignedReturnMatrix:
        events.append("runner")
        calls.append((start, end))
        assert rate_limit_callback is not None
        rate_limit_callback(
            KisRateLimitNotification(
                stock_code="000660",
                attempt_number=1,
                max_attempts=3,
                wait_seconds=61.0,
            )
        )
        return _matrix()

    monkeypatch.setattr(cli, "render_portfolio_returns_start", recording_renderer)
    monkeypatch.setattr(cli, "run_production_aligned_returns", fake_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "portfolio",
            "returns",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END)]
    for expected in (
        "KIS 국내주식 수익률 행렬 조회 시작 · READ ONLY",
        "조회 대상: 활성 유니버스",
        "시작일: 2026-08-01",
        "종료일: 2026-08-31",
        "KIS 호출 제한: 000660 · 61초 후 재시도 (1/3)",
        "공통 거래일 일별 단순수익률 · READ ONLY",
        "종목 수",
        "2개",
        "공통 종가 관측치 수",
        "3개",
        "수익률 관측치 수",
        "최초 수익률 기준일",
        "2026-08-04",
        "최종 수익률 기준일",
        "2026-08-05",
        "종목코드 순서",
        "000660, 005930",
        "결측치 보정",
        "없음 (forward fill·보간하지 않음)",
    ):
        assert expected in result.stdout
    assert result.stderr == ""


def test_returns_command_reports_an_empty_universe_as_analysis_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AlignedReturnMatrix:
        raise EmptyReturnUniverseError("활성 투자 후보 유니버스가 비어 있습니다.")

    monkeypatch.setattr(cli, "run_production_aligned_returns", failing_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "portfolio",
            "returns",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS
    assert "조회 시작 · READ ONLY" in result.stdout
    assert "수익률 분석 오류" in result.stderr
    assert "비어" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "error",
    (
        EmptyStockHistoryError("005930"),
        InsufficientCommonObservationsError(1, 2),
    ),
)
def test_returns_command_uses_stable_code_for_expected_analysis_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def failing_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AlignedReturnMatrix:
        raise error

    monkeypatch.setattr(cli, "run_production_aligned_returns", failing_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "portfolio",
            "returns",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert " ".join(str(error).split()) in " ".join(result.stderr.split())
    assert "Traceback" not in result.stderr


def test_returns_command_hides_unexpected_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "synthetic-secret-response-body"

    def failing_runner(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AlignedReturnMatrix:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_aligned_returns", failing_runner)

    result = CliRunner().invoke(
        cli.app,
        [
            "portfolio",
            "returns",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
        ],
        color=False,
    )

    combined_output = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED
    assert secret not in combined_output
    assert "Traceback" not in combined_output


def test_returns_command_rejects_invalid_dates_before_production_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(
        start: date,
        end: date,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AlignedReturnMatrix:
        raise AssertionError(f"unexpected production call: {start} {end}")

    monkeypatch.setattr(cli, "run_production_aligned_returns", unexpected)

    result = CliRunner().invoke(
        cli.app,
        [
            "portfolio",
            "returns",
            "--start",
            "2026-08-31",
            "--end",
            "2026-08-01",
        ],
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA
    assert "늦을 수 없습니다" in result.stderr
    assert "Traceback" not in result.stderr


def test_portfolio_help_exposes_returns_without_optimization_or_orders() -> None:
    portfolio_help = CliRunner().invoke(cli.app, ["portfolio", "--help"], color=False)
    returns_help = CliRunner().invoke(
        cli.app,
        ["portfolio", "returns", "--help"],
        color=False,
    )

    assert portfolio_help.exit_code == 0
    assert returns_help.exit_code == 0
    assert "READ ONLY" in portfolio_help.stdout
    assert "returns" in portfolio_help.stdout
    assert "--start" in returns_help.stdout
    assert "--end" in returns_help.stdout
    assert "YYYY-MM-DD" in returns_help.stdout
    combined_output = portfolio_help.stdout + returns_help.stdout
    for forbidden in ("optimize", "order", "buy", "sell", "weight"):
        assert forbidden not in combined_output.lower()

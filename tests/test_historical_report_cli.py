from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import AlignedReturnMatrix, KoreanStock, StockMarket
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRateLimitNotification
from phalanx.portfolio.application import HistoricalReportResult
from phalanx.portfolio.errors import (
    HistoricalReportStorageError,
    InsufficientPerformanceObservationsError,
)
from phalanx.portfolio.performance import analyze_historical_universe

START = date(2026, 1, 1)
END = date(2026, 1, 31)


def _result(output: Path) -> HistoricalReportResult:
    analysis = analyze_historical_universe(
        AlignedReturnMatrix(
            stock_codes=("005930",),
            dates=(date(2026, 1, 2), date(2026, 1, 3)),
            values=((Decimal("0.1"),), (Decimal("-0.05"),)),
        )
    )
    return HistoricalReportResult(
        analysis=analysis,
        stocks=(KoreanStock("005930", "삼성전자", StockMarket.KOSPI),),
        saved_path=output,
    )


def _command(output: Path) -> list[str]:
    return [
        "portfolio",
        "historical-report",
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-31",
        "--output",
        str(output),
    ]


def test_historical_report_announces_before_runner_and_prints_completed_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "report.html"
    events: list[str] = []
    calls: list[tuple[date, date, Path]] = []
    original_start = cli.render_historical_report_start

    def recording_start(start: str, end: str, path: Path, console: Console) -> None:
        events.append("start")
        original_start(start, end, path, console)

    def fake_runner(
        start: date,
        end: date,
        output_path: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> HistoricalReportResult:
        events.append("runner")
        calls.append((start, end, output_path))
        assert rate_limit_callback is not None
        rate_limit_callback(KisRateLimitNotification("005930", 1, 3, 61.0))
        return _result(output_path)

    monkeypatch.setattr(cli, "render_historical_report_start", recording_start)
    monkeypatch.setattr(cli, "run_production_historical_report", fake_runner)

    result = CliRunner().invoke(cli.app, _command(output), color=False)

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END, output)]
    for expected in (
        "과거 유니버스 성과 리포트 생성 시작 · KIS READ ONLY",
        "조회 대상: 활성 유니버스",
        "시작일: 2026-01-01",
        "종료일: 2026-01-31",
        "저장 대상:",
        "KIS 호출 제한: 005930 · 61초 후 재시도 (1/3)",
        "분석 시작일",
        "2026-01-02",
        "분석 종료일",
        "2026-01-03",
        "종목 수",
        "1개",
        "수익률 관측치 수",
        "2개",
        "기준선 총수익률",
        "저장 경로",
        str(output),
        "실제 계좌 성과나 Phalanx 전략 성과가 아닙니다",
        "KIS READ ONLY · 주문 미전송",
    ):
        assert expected in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("error", "expected_code", "message"),
    (
        (
            InsufficientPerformanceObservationsError(1),
            cli.ExitCode.PORTFOLIO_ANALYSIS,
            "성과 분석 오류",
        ),
        (
            HistoricalReportStorageError("합성 저장 실패"),
            cli.ExitCode.HISTORICAL_REPORT,
            "리포트 생성·저장 오류",
        ),
    ),
)
def test_historical_report_uses_stable_codes_for_expected_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
    expected_code: cli.ExitCode,
    message: str,
) -> None:
    def failing_runner(
        start: date,
        end: date,
        output_path: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> HistoricalReportResult:
        raise error

    monkeypatch.setattr(cli, "run_production_historical_report", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "report.html"), color=False)

    assert result.exit_code == expected_code
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_historical_report_handles_keyboard_interrupt_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def interrupted_runner(
        start: date,
        end: date,
        output_path: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> HistoricalReportResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_production_historical_report", interrupted_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "report.html"), color=False)

    assert result.exit_code == cli.ExitCode.INTERRUPTED
    assert "안전하게 종료" in result.stderr
    assert "Traceback" not in result.stderr


def test_historical_report_hides_unexpected_secrets_and_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-http-response"

    def failing_runner(
        start: date,
        end: date,
        output_path: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> HistoricalReportResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_historical_report", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "report.html"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED
    assert secret not in combined
    assert "Traceback" not in combined


def test_historical_report_help_requires_dates_and_output() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["portfolio", "historical-report", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "--output" in result.stdout
    assert "HTML" in result.stdout
    assert "YYYY-MM-DD" in result.stdout
    for forbidden in ("order", "buy", "sell", "optimize", "kospi-benchmark"):
        assert forbidden not in result.stdout.lower()

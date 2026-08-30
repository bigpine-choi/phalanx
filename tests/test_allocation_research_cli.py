from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import (
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationPolicyFailure,
    AllocationPolicyOutcome,
    AllocationPolicyOutcomeStatus,
    AllocationRebalanceRecord,
    AllocationResearchTrial,
    AllocationTarget,
    AllocationTrialStatus,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRateLimitNotification
from phalanx.portfolio.application import AllocationResearchApplicationResult
from phalanx.portfolio.errors import AllocationTrialStorageError

START = date(2024, 1, 1)
END = date(2026, 1, 31)
SIGNAL_DATE = date(2026, 1, 2)
EXECUTION_DATE = date(2026, 1, 5)
FINAL_DATE = date(2026, 1, 30)
POLICY_IDS = (
    "weekly_equal_weight",
    "weekly_inverse_volatility",
    "equal_weight_buy_and_hold",
)


def _backtest_result(policy_id: str) -> AllocationBacktestResult:
    target = AllocationTarget(
        signal_date=SIGNAL_DATE,
        stock_codes=("005930",),
        target_weights=(Decimal("0.995"),),
        policy_id=policy_id,
        target_equity_weight=Decimal("0.995"),
    )
    rebalance = AllocationRebalanceRecord(
        target=target,
        execution_date=EXECUTION_DATE,
        realized_weights=(Decimal("0.995"),),
        realized_cash_weight=Decimal("0.005"),
        buy_gross_turnover=Decimal("0.995"),
        sell_gross_turnover=Decimal("0"),
        transaction_cost=Decimal("0.001"),
        transaction_cost_rate=Decimal("0.001"),
        pre_trade_nav=Decimal("1"),
        post_trade_nav=Decimal("0.999"),
        cash_after=Decimal("0.004995"),
    )
    return AllocationBacktestResult(
        policy_id=policy_id,
        stock_codes=("005930",),
        dates=(EXECUTION_DATE, FINAL_DATE),
        net_asset_values=(Decimal("0.999"), Decimal("1.01")),
        realized_weights=((Decimal("0.995"),), (Decimal("0.996"),)),
        realized_cash_weights=(Decimal("0.005"), Decimal("0.004")),
        rebalances=(rebalance,),
        buy_gross_turnover=Decimal("0.995"),
        sell_gross_turnover=Decimal("0"),
        cumulative_transaction_cost=Decimal("0.001"),
        cumulative_cost_rate=Decimal("0.001"),
        total_return=Decimal("0.01"),
        annualized_return=Decimal("0.20"),
        annualized_volatility=Decimal("0.12"),
        max_drawdown=Decimal("-0.03"),
    )


def _trial(*, succeeded: bool) -> AllocationResearchTrial:
    if succeeded:
        outcomes = tuple(
            AllocationPolicyOutcome(
                policy_id=policy_id,
                status=AllocationPolicyOutcomeStatus.SUCCEEDED,
                result=_backtest_result(policy_id),
            )
            for policy_id in POLICY_IDS
        )
        status = AllocationTrialStatus.SUCCEEDED
        actual_start: date | None = EXECUTION_DATE
        actual_end: date | None = FINAL_DATE
    else:
        outcomes = tuple(
            AllocationPolicyOutcome(
                policy_id=policy_id,
                status=AllocationPolicyOutcomeStatus.FAILED,
                failure=AllocationPolicyFailure(
                    code="allocation_policy_error",
                    message="정제된 합성 정책 실패",
                ),
            )
            for policy_id in POLICY_IDS
        )
        status = AllocationTrialStatus.FAILED
        actual_start = None
        actual_end = None
    return AllocationResearchTrial(
        trial_id="cli-trial-001",
        status=status,
        executed_at=datetime(2026, 2, 1, 12, 30, tzinfo=UTC),
        requested_start=START,
        requested_end=END,
        actual_evaluation_start=actual_start,
        actual_evaluation_end=actual_end,
        stock_codes=("005930",),
        config=AllocationBacktestConfig(),
        policy_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        market_data_fingerprint="c" * 64,
        policy_outcomes=outcomes,
        code_model_version="allocation-research-v1",
    )


def _application_result(
    output_dir: Path,
    *,
    succeeded: bool,
) -> AllocationResearchApplicationResult:
    return AllocationResearchApplicationResult(
        trial=_trial(succeeded=succeeded),
        saved_path=output_dir / "allocation_research_trial_cli-trial-001.json",
    )


def _command(output_dir: Path) -> list[str]:
    return [
        "portfolio",
        "allocation-research",
        "--start",
        START.isoformat(),
        "--end",
        END.isoformat(),
        "--output-dir",
        str(output_dir),
    ]


def test_allocation_research_announces_before_runner_and_renders_policy_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("trials")
    events: list[str] = []
    calls: list[tuple[date, date, Path]] = []
    original_start = cli.render_allocation_research_start

    def recording_start(
        start: str,
        end: str,
        path: Path,
        console: Console,
    ) -> None:
        events.append("start")
        original_start(start, end, path, console)

    def fake_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AllocationResearchApplicationResult:
        events.append("runner")
        calls.append((start, end, output_dir))
        assert rate_limit_callback is not None
        rate_limit_callback(KisRateLimitNotification("005930", 1, 3, 61.0))
        return _application_result(output_dir, succeeded=True)

    def wide_console(*, stderr: bool = False) -> Console:
        return Console(
            stderr=stderr,
            markup=False,
            highlight=False,
            width=320,
        )

    monkeypatch.setattr(cli, "render_allocation_research_start", recording_start)
    monkeypatch.setattr(cli, "run_production_allocation_research", fake_runner)
    monkeypatch.setattr(cli, "_console", wide_console)

    result = CliRunner().invoke(
        cli.app,
        _command(output_dir),
        color=False,
        terminal_width=320,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END, output_dir)]
    for expected in (
        "자산배분 연구 시작 · KIS READ ONLY",
        "조회 대상: 활성 유니버스",
        f"시작일: {START.isoformat()}",
        f"종료일: {END.isoformat()}",
        f"출력 디렉터리: {output_dir}",
        "현재 유니버스 조건부 allocation-only 연구",
        "KIS 호출 제한: 005930 · 61초 후 재시도 (1/3)",
        "자산배분 정책 비교 · allocation-only · READ ONLY",
        "실제 평가기간",
        "리밸런싱",
        "총수익률",
        "연환산수익률",
        "연환산변동성",
        "최대 Drawdown",
        "매수 gross turnover",
        "매도 gross turnover",
        "누적 비용률",
        "weekly_equal_weight",
        "weekly_inverse_volatility",
        "equal_weight_buy_and_hold",
        f"{EXECUTION_DATE.isoformat()}~{FINAL_DATE.isoformat()}",
        "trial 상태: succeeded",
        "trial JSON 저장 경로:",
        str(_application_result(output_dir, succeeded=True).saved_path),
        "KIS READ ONLY · 주문 미전송",
    ):
        assert expected in result.stdout
    assert result.stderr == ""


def test_failed_allocation_trial_is_persisted_and_exits_with_analysis_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("trials")
    expected = _application_result(output_dir, succeeded=False)
    monkeypatch.setattr(
        cli,
        "run_production_allocation_research",
        lambda start, end, output_dir, *, rate_limit_callback=None: expected,
    )

    result = CliRunner().invoke(
        cli.app,
        _command(output_dir),
        color=False,
        terminal_width=320,
    )

    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "trial 상태: failed" in result.stdout
    assert str(expected.saved_path) in result.stdout
    assert "자산배분 연구 오류" in result.stderr
    assert "Traceback" not in result.stderr


def test_allocation_trial_storage_error_uses_portfolio_storage_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-storage-path"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AllocationResearchApplicationResult:
        raise AllocationTrialStorageError(secret)

    monkeypatch.setattr(cli, "run_production_allocation_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_STORAGE == 66
    assert "연구 trial 저장 오류" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_allocation_research_handles_keyboard_interrupt_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def interrupted_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AllocationResearchApplicationResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_production_allocation_research", interrupted_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    assert result.exit_code == cli.ExitCode.INTERRUPTED == 130
    assert "안전하게 종료" in result.stderr
    assert "Traceback" not in result.stderr


def test_allocation_research_hides_unexpected_secret_and_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-app-secret-access-token-account-number"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> AllocationResearchApplicationResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_allocation_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED
    assert secret not in combined
    assert "Traceback" not in combined


def test_allocation_research_help_requires_dates_and_output_directory() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["portfolio", "allocation-research", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "--output-dir" in result.stdout
    assert "YYYY-MM-DD" in result.stdout
    assert "allocation-only" in result.stdout

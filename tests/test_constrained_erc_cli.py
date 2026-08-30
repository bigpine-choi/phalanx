from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    AllocationBacktestConfig,
    ConstrainedErcFailure,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcResearchStatus,
    ConstrainedErcResearchTrial,
    DailyBar,
    DynamicRiskModelConfig,
    KoreanStock,
    StockMarket,
)
from phalanx.kis.market_data_client import (
    KisRateLimitCallback,
    KisRateLimitNotification,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.application import ConstrainedErcResearchApplicationResult
from phalanx.portfolio.constrained_erc_research import conduct_constrained_erc_research
from phalanx.portfolio.errors import (
    ConstrainedErcResearchError,
    ConstrainedErcTrialStorageError,
)

START = date(2025, 1, 1)
END = START + timedelta(days=26)
EXECUTED_AT = datetime(2026, 2, 1, 12, 30, tzinfo=UTC)


def _allocation_config() -> AllocationBacktestConfig:
    return AllocationBacktestConfig(
        minimum_training_returns=20,
        maximum_training_returns=22,
        rebalance_interval=2,
        target_equity_weight=Decimal(1),
    )


def _risk_config() -> DynamicRiskModelConfig:
    return DynamicRiskModelConfig(
        minimum_observations=20,
        maximum_observations=22,
        rebalance_interval=2,
        fast_volatility_half_life=2,
        fast_correlation_half_life=4,
        slow_volatility_half_life=3,
        slow_correlation_half_life=6,
        minimum_volatility_seed_observations=2,
        minimum_correlation_observations=3,
        downside_fraction=Decimal("0.50"),
        minimum_downside_observations=3,
    )


def _histories() -> tuple[StockDailyBars, ...]:
    histories: list[StockDailyBars] = []
    for column, stock_code in enumerate(("000001", "000002", "000003", "000004", "000005")):
        bars: list[DailyBar] = []
        for index in range(27):
            trade_date = START + timedelta(days=index)
            trend = Decimal(index * (column + 1))
            cycle = Decimal(((index + column) % 4) - 2) / Decimal(3)
            close = Decimal(100 + column * 20) + trend + cycle
            overnight = Decimal((index + column) % 3 - 1) / Decimal(5)
            open_price = close - overnight
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=open_price,
                    high_price=max(open_price, close) + Decimal(1),
                    low_price=min(open_price, close) - Decimal(1),
                    close_price=close,
                    volume=1_000 + index,
                )
            )
        histories.append(
            StockDailyBars(
                stock=KoreanStock(
                    stock_code,
                    f"종목-{column + 1}",
                    StockMarket.KOSPI,
                ),
                bars=tuple(bars),
            )
        )
    return tuple(histories)


@lru_cache(maxsize=1)
def _successful_trial() -> ConstrainedErcResearchTrial:
    trial = conduct_constrained_erc_research(
        _histories(),
        START,
        END,
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "constrained-erc-cli",
        clock=lambda: EXECUTED_AT,
    )
    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    return trial


def _failed_trial() -> ConstrainedErcResearchTrial:
    trial = _successful_trial()
    failure = ConstrainedErcFailure(
        code="constrained_erc_calculation_error",
        message="synthetic-secret-access-token-account-number",
    )
    failed_outcome = replace(
        trial.policy_outcomes[0],
        status=ConstrainedErcOutcomeStatus.FAILED,
        erc_targets=(),
        result=None,
        failure=failure,
    )
    return replace(
        trial,
        status=ConstrainedErcResearchStatus.FAILED,
        policy_outcomes=(failed_outcome, *trial.policy_outcomes[1:]),
    )


def _application_result(
    output_dir: Path,
    *,
    succeeded: bool,
) -> ConstrainedErcResearchApplicationResult:
    trial = _successful_trial() if succeeded else _failed_trial()
    return ConstrainedErcResearchApplicationResult(
        trial=trial,
        saved_path=(output_dir / f"constrained_erc_research_trial_{trial.trial_id}.json"),
    )


def _command(output_dir: Path, *, start: str | None = None) -> list[str]:
    return [
        "portfolio",
        "constrained-erc-research",
        "--start",
        START.isoformat() if start is None else start,
        "--end",
        END.isoformat(),
        "--output-dir",
        str(output_dir),
    ]


def _wide_console(*, stderr: bool = False) -> Console:
    return Console(
        stderr=stderr,
        markup=False,
        highlight=False,
        width=360,
    )


def test_constrained_erc_announces_before_runner_and_renders_seven_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("constrained-erc-trials")
    events: list[str] = []
    calls: list[tuple[date, date, Path]] = []
    original_start = cli.render_constrained_erc_research_start

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
    ) -> ConstrainedErcResearchApplicationResult:
        events.append("runner")
        calls.append((start, end, output_dir))
        assert rate_limit_callback is not None
        rate_limit_callback(KisRateLimitNotification("005930", 2, 3, 61.0))
        return _application_result(output_dir, succeeded=True)

    monkeypatch.setattr(cli, "render_constrained_erc_research_start", recording_start)
    monkeypatch.setattr(cli, "run_production_constrained_erc_research", fake_runner)
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(
        cli.app,
        _command(output_dir),
        color=False,
        terminal_width=360,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END, output_dir)]
    assert result.stdout.splitlines()[:7] == [
        "Constrained ERC 연구 시작 · KIS READ ONLY",
        "조회 대상: 활성 유니버스",
        f"시작일: {START.isoformat()}",
        f"종료일: {END.isoformat()}",
        f"출력 디렉터리: {output_dir}",
        "current-universe conditional allocation-only",
        "주문 미전송",
    ]
    for expected in (
        "KIS 호출 제한: 005930 · 61초 후 재시도 (2/3)",
        "Constrained ERC 독립 scenario 및 control 비교 · READ ONLY",
        "상태",
        "실제 평가기간",
        "리밸런싱 횟수",
        "총수익률",
        "연환산수익률",
        "연환산변동성",
        "최대 Drawdown",
        "매수 gross turnover",
        "매도 gross turnover",
        "누적 비용률",
        "최대 목표비중",
        "target cap 도달 snapshot 수",
        "realized drift cap 초과 일수",
        "median free-asset RC dispersion",
        "max free-asset RC dispersion",
        "maximum normalized KKT residual",
        "목표 현금비중",
        "trial 상태: succeeded",
        "trial JSON 저장 경로:",
        str(_application_result(output_dir, succeeded=True).saved_path),
        "KIS READ ONLY · 주문 미전송",
    ):
        assert expected in result.stdout
    policy_positions = [
        result.stdout.index(policy_id) for policy_id in CONSTRAINED_ERC_POLICY_ORDER
    ]
    assert policy_positions == sorted(policy_positions)
    for forbidden in ("우승", "winner", "추천 정책", "자동 선택"):
        assert forbidden not in result.stdout.lower()
    assert result.stderr == ""


def test_failed_constrained_erc_trial_prints_path_and_uses_analysis_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("constrained-erc-trials")
    expected = _application_result(output_dir, succeeded=False)
    monkeypatch.setattr(
        cli,
        "run_production_constrained_erc_research",
        lambda start, end, output_dir, *, rate_limit_callback=None: expected,
    )
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(cli.app, _command(output_dir), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "trial 상태: failed" in result.stdout
    assert "실패 코드" in result.stdout
    assert "constrained_erc_calculation_error" in result.stdout
    assert "실패 사유" in result.stdout
    assert "Constrained ERC 정책 계산을 완료하지 못했습니다." in result.stdout
    assert str(expected.saved_path) in result.stdout
    assert "Constrained ERC 연구 오류" in result.stderr
    assert "synthetic-secret-access-token-account-number" not in combined
    assert "Traceback" not in combined


def test_empty_active_universe_is_saved_and_reported_as_analysis_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "trials"
    trial = conduct_constrained_erc_research(
        (),
        START,
        END,
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "empty-active-universe",
        clock=lambda: EXECUTED_AT,
    )
    expected = ConstrainedErcResearchApplicationResult(
        trial=trial,
        saved_path=output_dir / "constrained_erc_research_trial_empty-active-universe.json",
    )
    monkeypatch.setattr(
        cli,
        "run_production_constrained_erc_research",
        lambda start, end, output_dir, *, rate_limit_callback=None: expected,
    )
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(cli.app, _command(output_dir), color=False)

    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "공통 실패 단계: input_preparation" in result.stdout
    assert "공통 실패 코드: constrained_erc_input_error" in result.stdout
    assert (
        "공통 실패 사유: Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다."
        in result.stdout
    )
    assert "constrained_erc_not_run_common_failure" in result.stdout
    assert "trial 상태: failed" in result.stdout
    assert expected.saved_path.name in result.stdout.replace("\n", "")
    assert "Traceback" not in result.stdout + result.stderr


def test_constrained_erc_analysis_error_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-analysis-token"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ConstrainedErcResearchApplicationResult:
        raise ConstrainedErcResearchError(secret)

    monkeypatch.setattr(cli, "run_production_constrained_erc_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "분석·수치 품질 검사" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_constrained_erc_storage_error_uses_storage_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-storage-response"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ConstrainedErcResearchApplicationResult:
        raise ConstrainedErcTrialStorageError(secret)

    monkeypatch.setattr(cli, "run_production_constrained_erc_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_STORAGE == 66
    assert "Constrained ERC trial 저장 오류" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_constrained_erc_handles_keyboard_interrupt_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def interrupted_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ConstrainedErcResearchApplicationResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_production_constrained_erc_research", interrupted_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    assert result.exit_code == cli.ExitCode.INTERRUPTED == 130
    assert "안전하게 종료" in result.stderr
    assert "Traceback" not in result.stderr


def test_invalid_date_fails_before_production_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner_calls = 0

    def forbidden_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ConstrainedErcResearchApplicationResult:
        nonlocal runner_calls
        runner_calls += 1
        pytest.fail("production runner must not run for an invalid date")

    monkeypatch.setattr(cli, "run_production_constrained_erc_research", forbidden_runner)

    result = CliRunner().invoke(
        cli.app,
        _command(tmp_path / "trials", start="2025-02-30"),
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA == 60
    assert runner_calls == 0
    assert result.stdout.splitlines()[0] == "Constrained ERC 연구 시작 · KIS READ ONLY"
    assert "시세 조회 오류" in result.stderr
    assert "Traceback" not in result.stderr


def test_constrained_erc_hides_unexpected_secret_and_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-app-key-secret-token-account-number"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ConstrainedErcResearchApplicationResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_constrained_erc_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED == 70
    assert secret not in combined
    assert "Traceback" not in combined


def test_constrained_erc_help_requires_only_fixed_options() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["portfolio", "constrained-erc-research", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "--output-dir" in result.stdout
    assert result.stdout.count("[required]") == 3
    for forbidden_option in (
        "--solver",
        "--cap",
        "--upper-bound",
        "--lower-bound",
        "--tolerance",
        "--ccd",
        "--bisection",
        "--lambda",
        "--quantum",
    ):
        assert forbidden_option not in result.stdout

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import (
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    AllocationBacktestResult,
    AllocationRebalanceRecord,
    AllocationTarget,
    VolatilityOverlayOutcomeStatus,
    VolatilityOverlayResearchStatus,
    VolatilityOverlayResearchTrial,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRateLimitNotification
from phalanx.portfolio.application import VolatilityOverlayResearchApplicationResult
from phalanx.portfolio.errors import (
    PortfolioAnalysisError,
    VolatilityOverlayTrialStorageError,
)

START = date(2023, 1, 1)
END = date(2026, 1, 31)
SIGNAL_DATE = date(2026, 1, 2)
EXECUTION_DATE = date(2026, 1, 5)
FINAL_DATE = date(2026, 1, 30)
TARGET_ANNUAL_VOLATILITY = Decimal("0.12")
ANNUAL_CASH_YIELD = Decimal("0.03")


def _backtest_result(policy_id: str) -> AllocationBacktestResult:
    target = AllocationTarget(
        signal_date=SIGNAL_DATE,
        stock_codes=("005930",),
        target_weights=(Decimal("0.60"),),
        policy_id=policy_id,
        target_equity_weight=Decimal("0.60"),
    )
    rebalance = AllocationRebalanceRecord(
        target=target,
        execution_date=EXECUTION_DATE,
        realized_weights=(Decimal("0.60"),),
        realized_cash_weight=Decimal("0.40"),
        buy_gross_turnover=Decimal("0.60"),
        sell_gross_turnover=Decimal("0"),
        transaction_cost=Decimal("0.001"),
        transaction_cost_rate=Decimal("0.001"),
        pre_trade_nav=Decimal("1"),
        post_trade_nav=Decimal("0.999"),
        cash_after=Decimal("0.3996"),
    )
    return AllocationBacktestResult(
        policy_id=policy_id,
        stock_codes=("005930",),
        dates=(EXECUTION_DATE, FINAL_DATE),
        net_asset_values=(Decimal("0.999"), Decimal("1.01")),
        realized_weights=((Decimal("0.60"),), (Decimal("0.61"),)),
        realized_cash_weights=(Decimal("0.40"), Decimal("0.39")),
        rebalances=(rebalance,),
        buy_gross_turnover=Decimal("0.60"),
        sell_gross_turnover=Decimal("0"),
        cumulative_transaction_cost=Decimal("0.001"),
        cumulative_cost_rate=Decimal("0.001"),
        total_return=Decimal("0.01"),
        annualized_return=Decimal("0.10"),
        annualized_volatility=TARGET_ANNUAL_VOLATILITY,
        max_drawdown=Decimal("-0.02"),
    )


def _trial(*, succeeded: bool) -> VolatilityOverlayResearchTrial:
    outcomes = []
    for policy_id in VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS:
        if succeeded:
            outcomes.append(
                SimpleNamespace(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.SUCCEEDED,
                    overlay_targets=(
                        SimpleNamespace(
                            scalar=Decimal("0.60"),
                            target_equity_weight=Decimal("0.60"),
                            cash_residual=Decimal("0.40"),
                            forecast_annual_volatility=Decimal("0.20"),
                            target_annual_volatility=TARGET_ANNUAL_VOLATILITY,
                        ),
                    ),
                    result=_backtest_result(policy_id),
                    failure=None,
                )
            )
        else:
            outcomes.append(
                SimpleNamespace(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.FAILED,
                    overlay_targets=(),
                    result=None,
                    failure=SimpleNamespace(
                        code="volatility_overlay_calculation_error",
                        message="변동성 overlay 정책 계산을 완료하지 못했습니다.",
                    ),
                )
            )
    trial = SimpleNamespace(
        trial_id="overlay-cli-001",
        status=(
            VolatilityOverlayResearchStatus.SUCCEEDED
            if succeeded
            else VolatilityOverlayResearchStatus.FAILED
        ),
        executed_at=datetime(2026, 2, 1, 12, 30, tzinfo=UTC),
        overlay_config=SimpleNamespace(
            target_annual_volatility=TARGET_ANNUAL_VOLATILITY,
            annual_cash_yield=ANNUAL_CASH_YIELD,
        ),
        policy_outcomes=tuple(outcomes),
    )
    return cast(VolatilityOverlayResearchTrial, trial)


def _application_result(
    output_dir: Path,
    *,
    succeeded: bool,
) -> VolatilityOverlayResearchApplicationResult:
    return VolatilityOverlayResearchApplicationResult(
        trial=_trial(succeeded=succeeded),
        saved_path=output_dir / "volatility_overlay_research_trial_overlay-cli-001.json",
    )


def _command(
    output_dir: Path,
    *,
    start: str | None = None,
    include_cash_yield: bool = True,
) -> list[str]:
    command = [
        "portfolio",
        "volatility-overlay-research",
        "--start",
        START.isoformat() if start is None else start,
        "--end",
        END.isoformat(),
        "--target-annual-volatility",
        str(TARGET_ANNUAL_VOLATILITY),
        "--output-dir",
        str(output_dir),
    ]
    if include_cash_yield:
        command.extend(("--annual-cash-yield", str(ANNUAL_CASH_YIELD)))
    return command


def _wide_console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, markup=False, highlight=False, width=360)


def test_overlay_announces_inputs_forwards_them_and_renders_four_fixed_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("volatility-overlay-trials")
    events: list[str] = []
    calls: list[tuple[date, date, Decimal, Decimal, Path]] = []
    original_start = cli.render_volatility_overlay_research_start

    def recording_start(
        start: str,
        end: str,
        path: Path,
        target: Decimal,
        cash_yield: Decimal,
        console: Console,
    ) -> None:
        events.append("start")
        original_start(start, end, path, target, cash_yield, console)

    def fake_runner(
        start: date,
        end: date,
        target_annual_volatility: Decimal,
        annual_cash_yield: Decimal = Decimal("0"),
        *,
        output_dir: Path,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> VolatilityOverlayResearchApplicationResult:
        events.append("runner")
        calls.append((start, end, target_annual_volatility, annual_cash_yield, output_dir))
        assert rate_limit_callback is not None
        rate_limit_callback(KisRateLimitNotification("005930", 2, 3, 61.0))
        return _application_result(output_dir, succeeded=True)

    monkeypatch.setattr(cli, "render_volatility_overlay_research_start", recording_start)
    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", fake_runner)
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(
        cli.app,
        _command(output_dir),
        color=False,
        terminal_width=360,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END, TARGET_ANNUAL_VOLATILITY, ANNUAL_CASH_YIELD, output_dir)]
    assert result.stdout.splitlines()[:9] == [
        "변동성 목표 overlay 연구 시작 · KIS READ ONLY",
        "조회 대상: 활성 유니버스",
        f"시작일: {START.isoformat()}",
        f"종료일: {END.isoformat()}",
        "목표 연환산변동성: 12.00%",
        "연 현금수익률: 3.00%",
        f"출력 디렉터리: {output_dir}",
        "네 covariance scenario 독립 overlay",
        "주문 미전송",
    ]
    for expected in (
        "KIS 호출 제한: 005930 · 61초 후 재시도 (2/3)",
        "변동성 목표 및 현금 residual overlay · READ ONLY",
        "실제 평가기간",
        "리밸런싱 횟수",
        "연환산변동성",
        "마지막 forecast 연환산변동성",
        "마지막 risky scalar",
        "마지막 목표 주식비중",
        "마지막 현금 residual",
        "입력 목표 연환산변동성: 12.00%",
        "연 현금수익률: 3.00%",
        "trial 상태: succeeded",
        str(_application_result(output_dir, succeeded=True).saved_path),
        "KIS READ ONLY · 주문 미전송",
    ):
        assert expected in result.stdout
    positions = [
        result.stdout.index(policy_id) for policy_id in VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS
    ]
    assert positions == sorted(positions)
    for forbidden in ("winner", "fallback", "우승", "추천 정책", "자동 선택"):
        assert forbidden not in result.stdout.lower()
    assert result.stderr == ""


def test_overlay_uses_zero_cash_yield_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    received: list[Decimal] = []

    def fake_runner(
        start: date,
        end: date,
        target_annual_volatility: Decimal,
        annual_cash_yield: Decimal = Decimal("0"),
        *,
        output_dir: Path,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> VolatilityOverlayResearchApplicationResult:
        received.append(annual_cash_yield)
        result = _application_result(output_dir, succeeded=True)
        result.trial.overlay_config.annual_cash_yield = annual_cash_yield
        return result

    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", fake_runner)
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(
        cli.app,
        _command(tmp_path / "trials", include_cash_yield=False),
        color=False,
    )

    assert result.exit_code == 0
    assert received == [Decimal("0")]
    assert "연 현금수익률: 0.00%" in result.stdout


def test_failed_overlay_trial_prints_safe_failure_and_uses_analysis_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "trials"
    expected = _application_result(output_dir, succeeded=False)
    monkeypatch.setattr(
        cli,
        "run_production_volatility_overlay_research",
        lambda start, end, target, cash=Decimal("0"), *, output_dir, rate_limit_callback=None: (
            expected
        ),
    )

    result = CliRunner().invoke(cli.app, _command(output_dir), color=False)

    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "trial 상태: failed" in result.stdout
    assert "volatility_overlay_calculation_error" in result.stdout
    assert "volatility overlay 정책 계산을 완료하지 못했습니다." in result.stdout
    assert str(expected.saved_path) in result.stdout.replace("\n", "")
    assert "overlay 연구 오류" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_overlay_analysis_error_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-analysis-token"

    def failing_runner(
        *args: object,
        **kwargs: object,
    ) -> VolatilityOverlayResearchApplicationResult:
        raise PortfolioAnalysisError(secret)

    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "분석·수치 품질 검사" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_overlay_storage_error_is_secret_safe_and_uses_storage_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-storage-response"

    def failing_runner(
        *args: object,
        **kwargs: object,
    ) -> VolatilityOverlayResearchApplicationResult:
        raise VolatilityOverlayTrialStorageError(secret)

    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_STORAGE == 66
    assert "overlay trial 저장 오류" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_overlay_invalid_date_fails_before_production_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner_calls = 0

    def forbidden_runner(
        *args: object,
        **kwargs: object,
    ) -> VolatilityOverlayResearchApplicationResult:
        nonlocal runner_calls
        runner_calls += 1
        pytest.fail("production runner must not run for an invalid date")

    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", forbidden_runner)

    result = CliRunner().invoke(
        cli.app,
        _command(tmp_path / "trials", start="2025-02-30"),
        color=False,
    )

    assert result.exit_code == cli.ExitCode.MARKET_DATA == 60
    assert runner_calls == 0
    assert result.stdout.splitlines()[0] == "변동성 목표 overlay 연구 시작 · KIS READ ONLY"
    assert "시세 조회 오류" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("option_name", "invalid_value"),
    (
        ("--target-annual-volatility", "0"),
        ("--target-annual-volatility", "NaN"),
        ("--target-annual-volatility", "Infinity"),
        ("--target-annual-volatility", "1E+10000"),
        ("--target-annual-volatility", "1E-10000"),
        ("--target-annual-volatility", "0.1234567890123"),
        ("--target-annual-volatility", "1.000000000001"),
        ("--annual-cash-yield", "-0.01"),
        ("--annual-cash-yield", "1.000000000001"),
        ("--annual-cash-yield", "1E+10000"),
        ("--annual-cash-yield", "0.1234567890123"),
        ("--annual-cash-yield", "not-a-decimal"),
    ),
)
def test_overlay_rejects_invalid_decimal_options_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    option_name: str,
    invalid_value: str,
) -> None:
    runner_calls = 0
    renderer_calls = 0

    def forbidden_runner(
        *args: object,
        **kwargs: object,
    ) -> VolatilityOverlayResearchApplicationResult:
        nonlocal runner_calls
        runner_calls += 1
        pytest.fail("production runner must not run for an invalid Decimal input")

    def forbidden_renderer(*args: object, **kwargs: object) -> None:
        nonlocal renderer_calls
        renderer_calls += 1
        pytest.fail("input rendering must not run for an invalid Decimal input")

    command = _command(tmp_path / "trials")
    command[command.index(option_name) + 1] = invalid_value
    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", forbidden_runner)
    monkeypatch.setattr(cli, "render_volatility_overlay_research_start", forbidden_renderer)

    result = CliRunner().invoke(cli.app, command, color=False)

    assert result.exit_code == 2
    assert runner_calls == 0
    assert renderer_calls == 0
    assert "Invalid value" in result.stderr
    assert "Traceback" not in result.stderr
    assert len(result.stdout + result.stderr) < 2_000


def test_overlay_canonicalizes_equivalent_cli_inputs_before_render_and_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rendered: list[tuple[Decimal, Decimal]] = []
    received: list[tuple[Decimal, Decimal]] = []

    def fake_renderer(
        start: str,
        end: str,
        output_dir: Path,
        target: Decimal,
        cash_yield: Decimal,
        console: Console,
    ) -> None:
        rendered.append((target, cash_yield))

    def fake_runner(
        start: date,
        end: date,
        target: Decimal,
        cash_yield: Decimal = Decimal("0"),
        *,
        output_dir: Path,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> VolatilityOverlayResearchApplicationResult:
        received.append((target, cash_yield))
        return _application_result(output_dir, succeeded=True)

    command = _command(tmp_path / "trials")
    command[command.index("--target-annual-volatility") + 1] = "0.120000000000000000"
    command[command.index("--annual-cash-yield") + 1] = "0E-10000"
    monkeypatch.setattr(cli, "render_volatility_overlay_research_start", fake_renderer)
    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", fake_runner)

    result = CliRunner().invoke(cli.app, command, color=False)

    assert result.exit_code == 0
    assert rendered == [(Decimal("0.12"), Decimal("0"))]
    assert received == [(Decimal("0.12"), Decimal("0"))]
    for value in (*rendered[0], *received[0]):
        assert value.as_tuple() in (Decimal("0.12").as_tuple(), Decimal("0").as_tuple())


def test_overlay_hides_unexpected_secret_and_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-app-key-secret-token-account-number"

    def failing_runner(
        *args: object,
        **kwargs: object,
    ) -> VolatilityOverlayResearchApplicationResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_volatility_overlay_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED == 70
    assert secret not in combined
    assert "Traceback" not in combined


def test_overlay_help_requires_explicit_target_and_documents_zero_cash_default() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["portfolio", "volatility-overlay-research", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    for option in (
        "--start",
        "--end",
        "--target-annual-volatility",
        "--annual-cash-yield",
        "--output-dir",
    ):
        assert option in result.stdout
    assert result.stdout.count("[required]") == 4
    assert "[default: 0]" in result.stdout
    for forbidden_option in (
        "--winner",
        "--fallback",
        "--leverage",
        "--order",
        "--quantity",
    ):
        assert forbidden_option not in result.stdout

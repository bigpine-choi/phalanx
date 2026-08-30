from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    AlignedReturnMatrix,
    CovarianceScenario,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelResearchResult,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
    RiskModelFailure,
    RiskModelLibraryProvenance,
    RiskModelResearchStatus,
    RiskModelResearchTrial,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRateLimitNotification
from phalanx.market_data.errors import InvalidMarketDataRangeError
from phalanx.portfolio.application import RiskModelResearchApplicationResult
from phalanx.portfolio.errors import RiskModelNumericalError, RiskModelTrialStorageError

START = date(2024, 1, 1)
END = date(2026, 1, 31)
FIRST_AS_OF = date(2026, 1, 8)
LAST_AS_OF = date(2026, 1, 15)
STOCK_CODES = ("005930", "000660")


def _diagnostics(
    *,
    repaired: bool = False,
    condition_number: float | None = 3.0,
) -> PsdDiagnostics:
    return PsdDiagnostics(
        minimum_eigenvalue_before=-1e-12 if repaired else 0.01,
        minimum_eigenvalue_after=0.0 if repaired else 0.01,
        maximum_eigenvalue_after=0.09,
        numerical_tolerance=1e-10,
        rank=1 if condition_number is None else 2,
        condition_number=condition_number,
        frobenius_repair_norm=1e-12 if repaired else 0.0,
        relative_repair_norm=1e-9 if repaired else 0.0,
        repaired=repaired,
    )


def _scenario(
    kind: CovarianceScenarioKind,
    observation_dates: tuple[date, ...],
    *,
    last: bool,
) -> CovarianceScenario:
    if kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF:
        metadata = LedoitWolfMetadata(shrinkage=0.25)
        diagnostics = _diagnostics(repaired=last, condition_number=None)
    elif kind in (
        CovarianceScenarioKind.FAST_IEWMA,
        CovarianceScenarioKind.SLOW_IEWMA,
    ):
        is_fast = kind is CovarianceScenarioKind.FAST_IEWMA
        metadata = IewmaMetadata(
            volatility_half_life=21 if is_fast else 63,
            correlation_half_life=63 if is_fast else 125,
            volatility_seed_count=20,
            correlation_observation_count=60,
            volatility_effective_sample_size=40.5 if is_fast else 80.5,
            correlation_effective_sample_size=90.5 if is_fast else 150.5,
            clip_threshold=4.2,
            clipped_scalar_count=2,
            correlation_psd_diagnostics=_diagnostics(),
        )
        diagnostics = _diagnostics()
    else:
        metadata = DownsideStressMetadata(
            downside_fraction=Decimal("0.20"),
            selected_count=len(observation_dates),
            cutoff_equal_weight_return=Decimal("-0.01"),
            selected_dates=observation_dates,
            selected_dates_fingerprint="d" * 64,
            shrinkage=0.35,
        )
        diagnostics = _diagnostics()
    return CovarianceScenario(
        kind=kind,
        stock_codes=STOCK_CODES,
        observation_dates=observation_dates,
        annualized_covariance=((0.04, 0.015), (0.015, 0.09)),
        annualized_volatilities=(0.2, 0.3),
        correlation_matrix=((1.0, 0.25), (0.25, 1.0)),
        metadata=metadata,
        psd_diagnostics=diagnostics,
    )


def _snapshot(as_of_date: date, *, last: bool) -> DynamicRiskModelSnapshot:
    observation_dates = (
        (date(2026, 1, 2), FIRST_AS_OF, LAST_AS_OF) if last else (date(2026, 1, 2), FIRST_AS_OF)
    )
    return DynamicRiskModelSnapshot(
        as_of_date=as_of_date,
        consumed_start_date=observation_dates[0],
        consumed_end_date=observation_dates[-1],
        consumed_observation_count=len(observation_dates),
        stock_codes=STOCK_CODES,
        consumed_dates=observation_dates,
        scenarios=tuple(
            _scenario(kind, observation_dates, last=last) for kind in SCENARIO_KIND_ORDER
        ),
        consumed_input_fingerprint=("e" if last else "f") * 64,
    )


def _trial(*, succeeded: bool) -> RiskModelResearchTrial:
    config = DynamicRiskModelConfig()
    provenance = RiskModelLibraryProvenance(
        python_version="3.12.3",
        numpy_version="2.0.0",
        scikit_learn_version="1.5.0",
    )
    if succeeded:
        matrix = AlignedReturnMatrix(
            stock_codes=STOCK_CODES,
            dates=(date(2026, 1, 2), FIRST_AS_OF, LAST_AS_OF),
            values=(
                (Decimal("0.01"), Decimal("-0.01")),
                (Decimal("0.02"), Decimal("0.01")),
                (Decimal("-0.01"), Decimal("0.02")),
            ),
        )
        snapshots = (
            _snapshot(FIRST_AS_OF, last=False),
            _snapshot(LAST_AS_OF, last=True),
        )
        result = DynamicRiskModelResearchResult(
            status=RiskModelResearchStatus.SUCCEEDED,
            stock_codes=STOCK_CODES,
            scheduled_as_of_dates=(FIRST_AS_OF, LAST_AS_OF),
            snapshots=snapshots,
        )
        status = RiskModelResearchStatus.SUCCEEDED
        failure = None
    else:
        matrix = None
        result = None
        status = RiskModelResearchStatus.FAILED
        failure = RiskModelFailure(
            code="risk_model_numerical_error",
            message="synthetic-secret-access-token",
            as_of_date=FIRST_AS_OF,
        )
    return RiskModelResearchTrial(
        trial_id="risk-cli-trial-001",
        status=status,
        executed_at=datetime(2026, 2, 1, 12, 30, tzinfo=UTC),
        requested_start=START,
        requested_end=END,
        stock_codes=STOCK_CODES,
        aligned_returns=matrix,
        config=config,
        config_fingerprint="a" * 64,
        input_fingerprint="b" * 64,
        trial_fingerprint="c" * 64,
        provenance=provenance,
        result=result,
        failure=failure,
    )


def _application_result(
    output_dir: Path,
    *,
    succeeded: bool,
) -> RiskModelResearchApplicationResult:
    return RiskModelResearchApplicationResult(
        trial=_trial(succeeded=succeeded),
        saved_path=output_dir / "risk_model_research_trial_risk-cli-trial-001.json",
    )


def _command(output_dir: Path) -> list[str]:
    return [
        "portfolio",
        "risk-model-research",
        "--start",
        START.isoformat(),
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
        width=240,
    )


def test_risk_model_research_announces_before_runner_and_renders_fixed_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("risk-trials")
    events: list[str] = []
    calls: list[tuple[date, date, Path]] = []
    original_start = cli.render_risk_model_research_start

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
    ) -> RiskModelResearchApplicationResult:
        events.append("runner")
        calls.append((start, end, output_dir))
        assert rate_limit_callback is not None
        rate_limit_callback(KisRateLimitNotification("005930", 1, 3, 61.0))
        return _application_result(output_dir, succeeded=True)

    monkeypatch.setattr(cli, "render_risk_model_research_start", recording_start)
    monkeypatch.setattr(cli, "run_production_risk_model_research", fake_runner)
    monkeypatch.setattr(cli, "_console", _wide_console)

    result = CliRunner().invoke(
        cli.app,
        _command(output_dir),
        color=False,
        terminal_width=240,
    )

    assert result.exit_code == 0
    assert events == ["start", "runner"]
    assert calls == [(START, END, output_dir)]
    assert result.stdout.splitlines()[:5] == [
        "동적 위험모형 연구 시작 · KIS READ ONLY",
        "조회 대상: 활성 유니버스",
        f"시작일: {START.isoformat()}",
        f"종료일: {END.isoformat()}",
        f"출력 디렉터리: {output_dir}",
    ]
    for expected in (
        "KIS 호출 제한: 005930 · 61초 후 재시도 (1/3)",
        "동적 위험모형 독립 scenario · READ ONLY",
        "snapshot 수",
        "2개",
        "최초 as-of",
        FIRST_AS_OF.isoformat(),
        "최종 as-of",
        LAST_AS_OF.isoformat(),
        "estimator 또는 반감기",
        "20.00% / 25.00% / 30.00%",
        "0.250000",
        "N/A",
        "PSD 보정 snapshot 수",
        "최대 상대 PSD 보정",
        "shrinkage 0.250000",
        "하방 선택 3개",
        "변동성 HL 21",
        "상관관계 HL 63",
        "변동성 ESS 40.50",
        "상관관계 ESS 90.50",
        "trial 상태: succeeded",
        "trial JSON 저장 경로:",
        str(_application_result(output_dir, succeeded=True).saved_path),
        "현재 유니버스 조건부 위험모형 연구",
        "KIS READ ONLY · 주문 미전송",
    ):
        assert expected in result.stdout
    scenario_positions = [result.stdout.index(kind.value) for kind in SCENARIO_KIND_ORDER]
    assert scenario_positions == sorted(scenario_positions)
    forbidden = (
        "최적",
        "우승",
        "추천",
        "목표비중",
        "매수",
        "매도",
        "예상수익",
        "optimizer",
        "weight",
        "recommendation",
    )
    assert all(value not in result.stdout.lower() for value in forbidden)
    assert result.stderr == ""


def test_failed_risk_model_trial_prints_state_and_path_before_analysis_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = Path("risk-trials")
    expected = _application_result(output_dir, succeeded=False)
    monkeypatch.setattr(
        cli,
        "run_production_risk_model_research",
        lambda start, end, output_dir, *, rate_limit_callback=None: expected,
    )

    result = CliRunner().invoke(cli.app, _command(output_dir), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "trial 상태: failed" in result.stdout
    assert str(expected.saved_path) in result.stdout
    assert "현재 유니버스 조건부 위험모형 연구" in result.stdout
    assert "동적 위험모형 연구 오류" in result.stderr
    assert "synthetic-secret-access-token" not in combined
    assert "Traceback" not in combined


def test_risk_model_analysis_error_uses_safe_analysis_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret-numerical-state"

    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> RiskModelResearchApplicationResult:
        raise RiskModelNumericalError(secret)

    monkeypatch.setattr(cli, "run_production_risk_model_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_ANALYSIS == 65
    assert "분석·수치 품질 검사" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_risk_model_trial_storage_error_uses_storage_exit(
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
    ) -> RiskModelResearchApplicationResult:
        raise RiskModelTrialStorageError(secret)

    monkeypatch.setattr(cli, "run_production_risk_model_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.PORTFOLIO_STORAGE == 66
    assert "위험모형 trial 저장 오류" in result.stderr
    assert secret not in combined
    assert "Traceback" not in combined


def test_risk_model_market_data_error_keeps_market_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def failing_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> RiskModelResearchApplicationResult:
        raise InvalidMarketDataRangeError("합성 시세 범위 오류")

    monkeypatch.setattr(cli, "run_production_risk_model_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    assert result.exit_code == cli.ExitCode.MARKET_DATA == 60
    assert "시세 조회 오류" in result.stderr
    assert "Traceback" not in result.stderr


def test_risk_model_research_handles_keyboard_interrupt_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def interrupted_runner(
        start: date,
        end: date,
        output_dir: Path,
        *,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> RiskModelResearchApplicationResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_production_risk_model_research", interrupted_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    assert result.exit_code == cli.ExitCode.INTERRUPTED == 130
    assert "안전하게 종료" in result.stderr
    assert "Traceback" not in result.stderr


def test_risk_model_research_hides_unexpected_secret_and_traceback(
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
    ) -> RiskModelResearchApplicationResult:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "run_production_risk_model_research", failing_runner)

    result = CliRunner().invoke(cli.app, _command(tmp_path / "trials"), color=False)

    combined = result.stdout + result.stderr
    assert result.exit_code == cli.ExitCode.UNEXPECTED
    assert secret not in combined
    assert "Traceback" not in combined


def test_risk_model_research_help_requires_only_fixed_v1_options() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["portfolio", "risk-model-research", "--help"],
        color=False,
    )

    assert result.exit_code == 0
    assert "--start" in result.stdout
    assert "--end" in result.stdout
    assert "--output-dir" in result.stdout
    assert "YYYY-MM-DD" in result.stdout
    for forbidden_option in (
        "--half-life",
        "--fast",
        "--slow",
        "--clip",
        "--downside",
        "--quantile",
        "--psd",
        "--repair",
    ):
        assert forbidden_option not in result.stdout

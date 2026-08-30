from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import phalanx.portfolio.application as portfolio_application
from phalanx.domain import (
    AlignedReturnMatrix,
    DailyBar,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    KoreanStock,
    RiskModelResearchStatus,
    RiskModelResearchTrial,
    StockMarket,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.risk_model_research import RiskModelEstimator

START = date(2020, 1, 1)
END = date(2026, 1, 31)
EXECUTED_AT = datetime(2026, 2, 1, 12, 30, tzinfo=UTC)


def _bar(stock_code: str, trade_date: date, price: str) -> DailyBar:
    value = Decimal(price)
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=value,
        high_price=value,
        low_price=value,
        close_price=value,
        volume=1_000,
    )


def _histories_with_one_noncommon_date() -> tuple[StockDailyBars, ...]:
    first = date(2020, 1, 1)
    missing_from_second = date(2020, 1, 2)
    third = date(2020, 1, 3)
    fourth = date(2020, 1, 4)
    return (
        StockDailyBars(
            stock=KoreanStock("000660", "SK하이닉스", StockMarket.KOSPI),
            bars=(
                _bar("000660", first, "100"),
                _bar("000660", missing_from_second, "999"),
                _bar("000660", third, "120"),
                _bar("000660", fourth, "132"),
            ),
        ),
        StockDailyBars(
            stock=KoreanStock("005930", "삼성전자", StockMarket.KOSPI),
            bars=(
                _bar("005930", first, "200"),
                _bar("005930", third, "220"),
                _bar("005930", fourth, "242"),
            ),
        ),
    )


def _long_matrix(count: int = 510) -> AlignedReturnMatrix:
    return AlignedReturnMatrix(
        stock_codes=("000660", "005930"),
        dates=tuple(START + timedelta(days=index) for index in range(count)),
        values=tuple(
            (
                Decimal((index % 7) - 3) / Decimal(1000),
                Decimal(((index * 2) % 9) - 4) / Decimal(1000),
            )
            for index in range(count)
        ),
    )


class ImmediatelyFailingEstimator:
    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.calls = 0

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot:
        self.calls += 1
        raise RuntimeError(self.secret)


def test_production_risk_research_fetches_builds_researches_and_saves_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = _histories_with_one_noncommon_date()
    expected_matrix = portfolio_application.build_aligned_return_matrix(histories)
    config = DynamicRiskModelConfig()
    output_dir = tmp_path / "risk-trials"
    credentials_path = tmp_path / "credentials.env"
    token_cache_path = tmp_path / "token.json"
    universe_path = tmp_path / "universe.json"
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"unexpected HTTP request: {request.url}")
    )
    pacer = KisRequestPacer(monotonic=lambda: 0.0, sleep=lambda seconds: None)

    def callback(notification: object) -> None:
        pass

    def trial_id_factory() -> str:
        return "application-risk-trial"

    def clock() -> datetime:
        return EXECUTED_AT

    expected_trial = portfolio_application.create_failed_risk_model_trial(
        expected_matrix.stock_codes,
        START,
        END,
        RuntimeError("synthetic placeholder"),
        config=config,
        trial_id_factory=trial_id_factory,
        clock=clock,
    )
    saved_path = output_dir / "risk_model_research_trial_application-risk-trial.json"
    universe_calls: list[tuple[date, date]] = []
    builder_calls: list[Sequence[StockDailyBars]] = []
    research_calls: list[AlignedReturnMatrix] = []
    registry_dirs: list[Path] = []
    saved_trials: list[RiskModelResearchTrial] = []
    original_builder = portfolio_application.build_aligned_return_matrix

    def fake_universe_runner(
        start: date,
        end: date,
        *,
        credentials_path: Path | None = None,
        token_cache_path: Path | None = None,
        universe_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        rate_limit_callback: KisRateLimitCallback | None = None,
        request_pacer: KisRequestPacer | None = None,
    ) -> tuple[StockDailyBars, ...]:
        universe_calls.append((start, end))
        assert credentials_path == expected_credentials_path
        assert token_cache_path == expected_token_cache_path
        assert universe_path == expected_universe_path
        assert transport is expected_transport
        assert rate_limit_callback is callback
        assert request_pacer is pacer
        return histories

    def recording_builder(received: Sequence[StockDailyBars]) -> AlignedReturnMatrix:
        builder_calls.append(received)
        return original_builder(received)

    def fake_research(
        matrix: AlignedReturnMatrix,
        requested_start: date,
        requested_end: date,
        *,
        config: DynamicRiskModelConfig | None = None,
        estimator: RiskModelEstimator | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> RiskModelResearchTrial:
        research_calls.append(matrix)
        assert matrix == expected_matrix
        assert matrix.stock_codes == ("000660", "005930")
        assert matrix.dates == (date(2020, 1, 3), date(2020, 1, 4))
        assert matrix.values == (
            (Decimal("0.2"), Decimal("0.1")),
            (Decimal("0.1"), Decimal("0.1")),
        )
        assert (requested_start, requested_end) == (START, END)
        assert config is expected_config
        assert estimator is None
        assert trial_id_factory is expected_trial_id_factory
        assert clock is expected_clock
        return expected_trial

    class FakeRegistry:
        def __init__(self, received_output_dir: Path) -> None:
            registry_dirs.append(received_output_dir)

        def save(self, trial: RiskModelResearchTrial) -> Path:
            saved_trials.append(trial)
            return saved_path

    expected_credentials_path = credentials_path
    expected_token_cache_path = token_cache_path
    expected_universe_path = universe_path
    expected_transport = transport
    expected_config = config
    expected_trial_id_factory = trial_id_factory
    expected_clock = clock
    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        fake_universe_runner,
    )
    monkeypatch.setattr(portfolio_application, "build_aligned_return_matrix", recording_builder)
    monkeypatch.setattr(portfolio_application, "create_risk_model_research_trial", fake_research)
    monkeypatch.setattr(portfolio_application, "JsonRiskModelTrialRegistry", FakeRegistry)

    result = portfolio_application.run_production_risk_model_research(
        START,
        END,
        output_dir,
        config=config,
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        universe_path=universe_path,
        transport=transport,
        rate_limit_callback=callback,
        request_pacer=pacer,
        trial_id_factory=trial_id_factory,
        clock=clock,
    )

    assert universe_calls == [(START, END)]
    assert builder_calls == [histories]
    assert research_calls == [expected_matrix]
    assert registry_dirs == [output_dir]
    assert saved_trials == [expected_trial]
    assert result.trial is expected_trial
    assert result.saved_path == saved_path


def test_builder_failure_is_projected_to_a_failed_trial_and_saved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = _histories_with_one_noncommon_date()
    config = DynamicRiskModelConfig()
    secret = "synthetic-builder-secret-token"
    output_dir = tmp_path / "risk-trials"
    saved_path = output_dir / "risk_model_research_trial_builder-failed.json"
    failed_trial_calls: list[Exception] = []
    saved_trials: list[RiskModelResearchTrial] = []
    original_failed_trial = portfolio_application.create_failed_risk_model_trial

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        lambda start, end, **kwargs: histories,
    )

    def failing_builder(received: Sequence[StockDailyBars]) -> AlignedReturnMatrix:
        assert received is histories
        raise RuntimeError(secret)

    def recording_failed_trial(
        stock_codes: tuple[str, ...],
        requested_start: date,
        requested_end: date,
        error: Exception,
        *,
        config: DynamicRiskModelConfig | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> RiskModelResearchTrial:
        failed_trial_calls.append(error)
        return original_failed_trial(
            stock_codes,
            requested_start,
            requested_end,
            error,
            config=config,
            trial_id_factory=trial_id_factory,
            clock=clock,
        )

    class FakeRegistry:
        def __init__(self, received_output_dir: Path) -> None:
            assert received_output_dir == output_dir

        def save(self, trial: RiskModelResearchTrial) -> Path:
            saved_trials.append(trial)
            return saved_path

    monkeypatch.setattr(portfolio_application, "build_aligned_return_matrix", failing_builder)
    monkeypatch.setattr(
        portfolio_application,
        "create_failed_risk_model_trial",
        recording_failed_trial,
    )
    monkeypatch.setattr(
        portfolio_application,
        "create_risk_model_research_trial",
        lambda *args, **kwargs: pytest.fail("successful research must not run"),
    )
    monkeypatch.setattr(portfolio_application, "JsonRiskModelTrialRegistry", FakeRegistry)

    result = portfolio_application.run_production_risk_model_research(
        START,
        END,
        output_dir,
        config=config,
        trial_id_factory=lambda: "builder-failed",
        clock=lambda: EXECUTED_AT,
    )

    assert len(failed_trial_calls) == 1
    assert len(saved_trials) == 1
    assert result.trial is saved_trials[0]
    assert result.trial.status is RiskModelResearchStatus.FAILED
    assert result.trial.aligned_returns is None
    assert result.trial.failure is not None
    assert result.trial.failure.code == "risk_model_input_error"
    assert secret not in result.trial.failure.message
    assert result.saved_path == saved_path


def test_estimator_failure_is_retained_in_a_failed_trial_and_saved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = _histories_with_one_noncommon_date()
    matrix = _long_matrix()
    config = DynamicRiskModelConfig()
    secret = "synthetic-estimator-app-secret"
    estimator = ImmediatelyFailingEstimator(secret)
    output_dir = tmp_path / "risk-trials"
    saved_path = output_dir / "risk_model_research_trial_estimator-failed.json"
    builder_calls: list[Sequence[StockDailyBars]] = []
    research_calls: list[AlignedReturnMatrix] = []
    saved_trials: list[RiskModelResearchTrial] = []
    original_research = portfolio_application.create_risk_model_research_trial

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        lambda start, end, **kwargs: histories,
    )

    def fake_builder(received: Sequence[StockDailyBars]) -> AlignedReturnMatrix:
        builder_calls.append(received)
        return matrix

    def recording_research(
        received_matrix: AlignedReturnMatrix,
        requested_start: date,
        requested_end: date,
        *,
        config: DynamicRiskModelConfig | None = None,
        estimator: RiskModelEstimator | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> RiskModelResearchTrial:
        research_calls.append(received_matrix)
        return original_research(
            received_matrix,
            requested_start,
            requested_end,
            config=config,
            estimator=estimator,
            trial_id_factory=trial_id_factory,
            clock=clock,
        )

    class FakeRegistry:
        def __init__(self, received_output_dir: Path) -> None:
            assert received_output_dir == output_dir

        def save(self, trial: RiskModelResearchTrial) -> Path:
            saved_trials.append(trial)
            return saved_path

    monkeypatch.setattr(portfolio_application, "build_aligned_return_matrix", fake_builder)
    monkeypatch.setattr(
        portfolio_application, "create_risk_model_research_trial", recording_research
    )
    monkeypatch.setattr(
        portfolio_application,
        "create_failed_risk_model_trial",
        lambda *args, **kwargs: pytest.fail("builder failure path must not run"),
    )
    monkeypatch.setattr(portfolio_application, "JsonRiskModelTrialRegistry", FakeRegistry)

    result = portfolio_application.run_production_risk_model_research(
        START,
        END,
        output_dir,
        config=config,
        estimator=estimator,
        trial_id_factory=lambda: "estimator-failed",
        clock=lambda: EXECUTED_AT,
    )

    assert builder_calls == [histories]
    assert research_calls == [matrix]
    assert estimator.calls == 1
    assert saved_trials == [result.trial]
    assert result.trial.status is RiskModelResearchStatus.FAILED
    assert result.trial.result is not None
    assert result.trial.failure is not None
    assert result.trial.failure.code == "risk_model_numerical_error"
    assert result.trial.failure.as_of_date == matrix.dates[503]
    assert secret not in result.trial.failure.message
    assert result.saved_path == saved_path

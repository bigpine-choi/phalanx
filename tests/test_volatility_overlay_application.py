from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest

import phalanx.portfolio.application as portfolio_application
from phalanx.domain import (
    AllocationBacktestConfig,
    ConstrainedErcSolverConfig,
    DailyBar,
    DynamicRiskModelConfig,
    KoreanStock,
    StockMarket,
    VolatilityOverlayResearchTrial,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.constrained_erc_research import (
    ConstrainedErcRiskEstimator,
    ConstrainedErcScenarioSolver,
)
from phalanx.portfolio.errors import InvalidVolatilityOverlayDomainError

START = date(2023, 1, 1)
END = date(2026, 1, 31)
TARGET_ANNUAL_VOLATILITY = Decimal("0.12")
ANNUAL_CASH_YIELD = Decimal("0.03")
EXECUTED_AT = datetime(2026, 2, 1, 12, 30, tzinfo=UTC)


def _history() -> StockDailyBars:
    stock = KoreanStock("005930", "삼성전자", StockMarket.KOSPI)
    price = Decimal("100")
    return StockDailyBars(
        stock=stock,
        bars=(
            DailyBar(
                stock_code=stock.stock_code,
                trade_date=date(2026, 1, 2),
                open_price=price,
                high_price=price,
                low_price=price,
                close_price=price,
                volume=1_000,
            ),
        ),
    )


def test_production_volatility_overlay_fetches_once_forwards_inputs_and_saves_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = (_history(),)
    allocation_config = AllocationBacktestConfig(target_equity_weight=Decimal(1))
    risk_model_config = DynamicRiskModelConfig()
    solver_config = ConstrainedErcSolverConfig()
    estimator = cast(ConstrainedErcRiskEstimator, object())
    solver = cast(ConstrainedErcScenarioSolver, object())
    expected_trial = cast(VolatilityOverlayResearchTrial, object())
    output_dir = tmp_path / "volatility-overlay-trials"
    saved_path = output_dir / "volatility_overlay_research_trial_application-overlay.json"
    credentials_path = tmp_path / "credentials.env"
    token_cache_path = tmp_path / "token.json"
    universe_path = tmp_path / "universe.json"
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"unexpected HTTP request: {request.url}")
    )
    pacer = KisRequestPacer(monotonic=lambda: 0.0, sleep=lambda seconds: None)
    universe_calls: list[tuple[date, date]] = []
    research_inputs: list[Sequence[StockDailyBars]] = []
    registry_dirs: list[Path] = []
    saved_trials: list[VolatilityOverlayResearchTrial] = []

    def callback(notification: object) -> None:
        pass

    def trial_id_factory() -> str:
        return "application-overlay"

    def clock() -> datetime:
        return EXECUTED_AT

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

    def fake_conduct(
        received_histories: Sequence[StockDailyBars],
        requested_start: date,
        requested_end: date,
        *,
        target_annual_volatility: Decimal,
        annual_cash_yield: Decimal = Decimal("0"),
        allocation_config: AllocationBacktestConfig | None = None,
        risk_model_config: DynamicRiskModelConfig | None = None,
        solver_config: ConstrainedErcSolverConfig | None = None,
        estimator: ConstrainedErcRiskEstimator | None = None,
        solver: ConstrainedErcScenarioSolver | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> VolatilityOverlayResearchTrial:
        research_inputs.append(received_histories)
        assert received_histories is histories
        assert (requested_start, requested_end) == (START, END)
        assert target_annual_volatility is expected_target
        assert annual_cash_yield is expected_cash_yield
        assert allocation_config is expected_allocation_config
        assert risk_model_config is expected_risk_model_config
        assert solver_config is expected_solver_config
        assert estimator is expected_estimator
        assert solver is expected_solver
        assert trial_id_factory is expected_trial_id_factory
        assert clock is expected_clock
        return expected_trial

    class FakeRegistry:
        def __init__(self, received_output_dir: Path) -> None:
            registry_dirs.append(received_output_dir)

        def save(self, trial: VolatilityOverlayResearchTrial) -> Path:
            saved_trials.append(trial)
            return saved_path

    expected_credentials_path = credentials_path
    expected_token_cache_path = token_cache_path
    expected_universe_path = universe_path
    expected_transport = transport
    expected_target = TARGET_ANNUAL_VOLATILITY
    expected_cash_yield = ANNUAL_CASH_YIELD
    expected_allocation_config = allocation_config
    expected_risk_model_config = risk_model_config
    expected_solver_config = solver_config
    expected_estimator = estimator
    expected_solver = solver
    expected_trial_id_factory = trial_id_factory
    expected_clock = clock
    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        fake_universe_runner,
    )
    monkeypatch.setattr(
        portfolio_application,
        "conduct_volatility_overlay_research",
        fake_conduct,
    )
    monkeypatch.setattr(
        portfolio_application,
        "JsonVolatilityOverlayTrialRegistry",
        FakeRegistry,
    )

    result = portfolio_application.run_production_volatility_overlay_research(
        START,
        END,
        TARGET_ANNUAL_VOLATILITY,
        ANNUAL_CASH_YIELD,
        output_dir=output_dir,
        allocation_config=allocation_config,
        risk_model_config=risk_model_config,
        solver_config=solver_config,
        estimator=estimator,
        solver=solver,
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
    assert research_inputs == [histories]
    assert registry_dirs == [output_dir]
    assert saved_trials == [expected_trial]
    assert result.trial is expected_trial
    assert result.saved_path == saved_path


def test_production_volatility_overlay_defaults_cash_yield_to_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_trial = cast(VolatilityOverlayResearchTrial, object())
    received_cash_yields: list[Decimal] = []

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        lambda start, end, **kwargs: (_history(),),
    )

    def fake_conduct(
        histories: Sequence[StockDailyBars],
        start: date,
        end: date,
        *,
        target_annual_volatility: Decimal,
        annual_cash_yield: Decimal,
        allocation_config: AllocationBacktestConfig | None = None,
        risk_model_config: DynamicRiskModelConfig | None = None,
        solver_config: ConstrainedErcSolverConfig | None = None,
        estimator: ConstrainedErcRiskEstimator | None = None,
        solver: ConstrainedErcScenarioSolver | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> VolatilityOverlayResearchTrial:
        received_cash_yields.append(annual_cash_yield)
        return expected_trial

    class FakeRegistry:
        def __init__(self, output_dir: Path) -> None:
            pass

        def save(self, trial: VolatilityOverlayResearchTrial) -> Path:
            return tmp_path / "trial.json"

    monkeypatch.setattr(
        portfolio_application,
        "conduct_volatility_overlay_research",
        fake_conduct,
    )
    monkeypatch.setattr(
        portfolio_application,
        "JsonVolatilityOverlayTrialRegistry",
        FakeRegistry,
    )

    portfolio_application.run_production_volatility_overlay_research(
        START,
        END,
        TARGET_ANNUAL_VOLATILITY,
        output_dir=tmp_path,
    )

    assert received_cash_yields == [Decimal("0")]


@pytest.mark.parametrize(
    ("target", "cash_yield"),
    (
        (Decimal("1E+10000"), Decimal("0")),
        (Decimal("0.12"), Decimal("1E+10000")),
        (Decimal("1E-10000"), Decimal("0")),
        (Decimal("0.12"), Decimal("-0.01")),
    ),
)
def test_production_rejects_invalid_economic_inputs_before_network_or_research(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: Decimal,
    cash_yield: Decimal,
) -> None:
    network_calls = 0
    research_calls = 0

    def forbidden_network(*args: object, **kwargs: object) -> tuple[StockDailyBars, ...]:
        nonlocal network_calls
        network_calls += 1
        pytest.fail("market-data network assembly must not run for invalid inputs")

    def forbidden_research(*args: object, **kwargs: object) -> VolatilityOverlayResearchTrial:
        nonlocal research_calls
        research_calls += 1
        pytest.fail("research must not run for invalid inputs")

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        forbidden_network,
    )
    monkeypatch.setattr(
        portfolio_application,
        "conduct_volatility_overlay_research",
        forbidden_research,
    )

    with pytest.raises(InvalidVolatilityOverlayDomainError):
        portfolio_application.run_production_volatility_overlay_research(
            START,
            END,
            target,
            cash_yield,
            output_dir=tmp_path,
        )

    assert network_calls == 0
    assert research_calls == 0

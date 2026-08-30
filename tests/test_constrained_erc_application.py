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
    ConstrainedErcResearchTrial,
    ConstrainedErcSolverConfig,
    DailyBar,
    DynamicRiskModelConfig,
    KoreanStock,
    StockMarket,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.constrained_erc_research import (
    ConstrainedErcRiskEstimator,
    ConstrainedErcScenarioSolver,
    conduct_constrained_erc_research,
)

START = date(2024, 1, 1)
END = date(2026, 1, 31)
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


def test_production_constrained_erc_fetches_once_and_persists_one_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = (_history(),)
    allocation_config = AllocationBacktestConfig(target_equity_weight=Decimal(1))
    risk_model_config = DynamicRiskModelConfig()
    solver_config = ConstrainedErcSolverConfig()
    estimator = cast(ConstrainedErcRiskEstimator, object())
    solver = cast(ConstrainedErcScenarioSolver, object())
    output_dir = tmp_path / "constrained-erc-trials"
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
        return "application-constrained-erc"

    def clock() -> datetime:
        return EXECUTED_AT

    expected_trial = conduct_constrained_erc_research(
        (),
        START,
        END,
        allocation_config=allocation_config,
        risk_model_config=risk_model_config,
        solver_config=solver_config,
        trial_id_factory=trial_id_factory,
        clock=clock,
    )
    saved_path = output_dir / "constrained_erc_research_trial_application-constrained-erc.json"
    universe_calls: list[tuple[date, date]] = []
    research_inputs: list[Sequence[StockDailyBars]] = []
    registry_dirs: list[Path] = []
    saved_trials: list[ConstrainedErcResearchTrial] = []

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
        allocation_config: AllocationBacktestConfig | None = None,
        risk_model_config: DynamicRiskModelConfig | None = None,
        solver_config: ConstrainedErcSolverConfig | None = None,
        estimator: ConstrainedErcRiskEstimator | None = None,
        solver: ConstrainedErcScenarioSolver | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> ConstrainedErcResearchTrial:
        research_inputs.append(received_histories)
        assert received_histories is histories
        assert (requested_start, requested_end) == (START, END)
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

        def save(self, trial: ConstrainedErcResearchTrial) -> Path:
            saved_trials.append(trial)
            return saved_path

    expected_credentials_path = credentials_path
    expected_token_cache_path = token_cache_path
    expected_universe_path = universe_path
    expected_transport = transport
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
        "conduct_constrained_erc_research",
        fake_conduct,
    )
    monkeypatch.setattr(
        portfolio_application,
        "JsonConstrainedErcTrialRegistry",
        FakeRegistry,
    )

    result = portfolio_application.run_production_constrained_erc_research(
        START,
        END,
        output_dir,
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

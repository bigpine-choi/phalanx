from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import phalanx.portfolio.application as portfolio_application
from phalanx.domain import (
    AllocationBacktestConfig,
    AllocationPolicyFailure,
    AllocationPolicyOutcome,
    AllocationPolicyOutcomeStatus,
    AllocationResearchTrial,
    AllocationTrialStatus,
    DailyBar,
    KoreanStock,
    StockMarket,
)
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_policies import (
    AllocationPolicy,
    default_allocation_policies,
)

START = date(2024, 1, 1)
END = date(2026, 1, 31)
EXECUTED_AT = datetime(2026, 2, 1, 12, 30, tzinfo=UTC)


def _history() -> StockDailyBars:
    stock = KoreanStock("005930", "삼성전자", StockMarket.KOSPI)
    return StockDailyBars(
        stock=stock,
        bars=(
            DailyBar(
                stock_code="005930",
                trade_date=date(2026, 1, 2),
                open_price=Decimal("100"),
                high_price=Decimal("101"),
                low_price=Decimal("99"),
                close_price=Decimal("100"),
                volume=1_000,
            ),
            DailyBar(
                stock_code="005930",
                trade_date=date(2026, 1, 5),
                open_price=Decimal("101"),
                high_price=Decimal("102"),
                low_price=Decimal("100"),
                close_price=Decimal("101"),
                volume=1_100,
            ),
        ),
    )


def _failed_trial(
    policies: tuple[AllocationPolicy, ...],
    config: AllocationBacktestConfig,
) -> AllocationResearchTrial:
    failure = AllocationPolicyFailure(
        code="allocation_policy_error",
        message="합성 정책 계산 실패",
    )
    return AllocationResearchTrial(
        trial_id="application-trial-001",
        status=AllocationTrialStatus.FAILED,
        executed_at=EXECUTED_AT,
        requested_start=START,
        requested_end=END,
        actual_evaluation_start=None,
        actual_evaluation_end=None,
        stock_codes=("005930",),
        config=config,
        policy_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        market_data_fingerprint="c" * 64,
        policy_outcomes=tuple(
            AllocationPolicyOutcome(
                policy_id=policy.policy_id,
                status=AllocationPolicyOutcomeStatus.FAILED,
                failure=failure,
            )
            for policy in policies
        ),
        code_model_version="allocation-research-v1",
    )


def test_production_allocation_research_fetches_once_and_persists_one_shared_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    histories = (_history(),)
    expected_policies = default_allocation_policies()
    expected_config = AllocationBacktestConfig()
    trial = _failed_trial(expected_policies, expected_config)
    output_dir = tmp_path / "allocation-trials"
    saved_path = output_dir / "allocation_research_trial_application-trial-001.json"
    credentials_path = tmp_path / "credentials.env"
    token_cache_path = tmp_path / "token.json"
    universe_path = tmp_path / "universe.json"
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"unexpected HTTP request: {request.url}")
    )
    pacer = KisRequestPacer(monotonic=lambda: 0.0, sleep=lambda seconds: None)
    universe_calls: list[tuple[date, date]] = []
    research_inputs: list[Sequence[StockDailyBars]] = []
    registry_output_dirs: list[Path] = []
    saved_trials: list[AllocationResearchTrial] = []

    def callback(notification: object) -> None:
        pass

    def trial_id_factory() -> str:
        return "application-trial-001"

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
        assert credentials_path == tmp_path / "credentials.env"
        assert token_cache_path == tmp_path / "token.json"
        assert universe_path == tmp_path / "universe.json"
        assert transport is expected_transport
        assert rate_limit_callback is callback
        assert request_pacer is pacer
        return histories

    def fake_conduct(
        received_histories: Sequence[StockDailyBars],
        requested_start: date,
        requested_end: date,
        *,
        config: AllocationBacktestConfig | None = None,
        policies: tuple[AllocationPolicy, ...] | None = None,
        trial_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> AllocationResearchTrial:
        research_inputs.append(received_histories)
        assert received_histories is histories
        assert (requested_start, requested_end) == (START, END)
        assert config is expected_config
        assert policies is expected_policies
        assert trial_id_factory is expected_trial_id_factory
        assert clock is expected_clock
        return trial

    class FakeRegistry:
        def __init__(self, received_output_dir: Path) -> None:
            registry_output_dirs.append(received_output_dir)

        def save(self, received_trial: AllocationResearchTrial) -> Path:
            saved_trials.append(received_trial)
            return saved_path

    expected_transport = transport
    expected_trial_id_factory = trial_id_factory
    expected_clock = clock
    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        fake_universe_runner,
    )
    monkeypatch.setattr(portfolio_application, "conduct_allocation_research", fake_conduct)
    monkeypatch.setattr(portfolio_application, "JsonAllocationTrialRegistry", FakeRegistry)

    result = portfolio_application.run_production_allocation_research(
        START,
        END,
        output_dir,
        config=expected_config,
        policies=expected_policies,
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
    assert len(expected_policies) == 3
    assert registry_output_dirs == [output_dir]
    assert saved_trials == [trial]
    assert result.trial is trial
    assert result.saved_path == saved_path

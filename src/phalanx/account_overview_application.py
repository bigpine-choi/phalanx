"""One refresh use case shared by CLI and future GUI, with replaceable I/O adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

import httpx

from phalanx.account_overview import (
    build_account_overview,
    validate_observation_span,
    validate_overview_snapshot,
)
from phalanx.account_overview_storage import JsonAccountOverviewStore
from phalanx.config import load_kis_credentials
from phalanx.domain import AccountSnapshot, CurrentPriceMarket, ValuationPriceBundle
from phalanx.domain.account_overview import AccountOverview
from phalanx.kis import KisBalanceClient, KisTokenManager
from phalanx.kis.market_data_client import (
    KisCurrentPriceClient,
    KisRateLimitCallback,
    KisRequestPacer,
)
from phalanx.market_data.service import ValuationPriceService

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class BalanceReader(Protocol):
    def fetch_balance(self) -> AccountSnapshot: ...


class OverviewPriceService(Protocol):
    def fetch_valuation_price_bundle(
        self,
        stock_codes: tuple[str, ...],
        *,
        market: CurrentPriceMarket,
        maximum_acquisition_span: timedelta,
    ) -> ValuationPriceBundle: ...


class OverviewStore(Protocol):
    def save(self, overview: AccountOverview) -> Path: ...


@dataclass(frozen=True)
class OverviewProgress:
    stage: Literal["balance", "prices", "saving"]
    stock_count: int = 0


OverviewProgressCallback = Callable[[OverviewProgress], None]


@dataclass(frozen=True)
class AccountOverviewResult:
    overview: AccountOverview
    saved_path: Path


class AccountOverviewApplication:
    def __init__(
        self,
        balance_reader: BalanceReader,
        price_service: OverviewPriceService,
        store: OverviewStore,
    ) -> None:
        self._balance_reader = balance_reader
        self._price_service = price_service
        self._store = store

    def run(
        self,
        *,
        max_observation_span_seconds: int = 60,
        progress_callback: OverviewProgressCallback | None = None,
    ) -> AccountOverviewResult:
        maximum_span = validate_observation_span(max_observation_span_seconds)
        if progress_callback is not None:
            progress_callback(OverviewProgress("balance"))
        snapshot = self._balance_reader.fetch_balance()
        codes = validate_overview_snapshot(snapshot)
        prices = None
        if codes:
            if progress_callback is not None:
                progress_callback(OverviewProgress("prices", len(codes)))
            prices = self._price_service.fetch_valuation_price_bundle(
                codes, market=CurrentPriceMarket.KRX, maximum_acquisition_span=maximum_span
            )
        overview = build_account_overview(
            snapshot, prices, max_observation_span_seconds=max_observation_span_seconds
        )
        if progress_callback is not None:
            progress_callback(OverviewProgress("saving", len(codes)))
        return AccountOverviewResult(overview, self._store.save(overview))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_production_account_overview(
    *,
    max_observation_span_seconds: int = 60,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    overview_directory: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    request_pacer: KisRequestPacer | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    progress_callback: OverviewProgressCallback | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> AccountOverviewResult:
    """Use one OAuth manager and one HTTP client for balance followed by KRX quotes."""

    validate_observation_span(max_observation_span_seconds)
    credentials = load_kis_credentials(credentials_path)
    with httpx.Client(transport=transport, timeout=_TIMEOUT) as http_client:
        tokens = KisTokenManager(
            credentials, cache_path=token_cache_path, client=http_client, timeout=_TIMEOUT
        )
        balance = KisBalanceClient(credentials, tokens, client=http_client, clock=clock)
        prices = ValuationPriceService(
            KisCurrentPriceClient(
                credentials,
                tokens,
                client=http_client,
                request_pacer=request_pacer,
                rate_limit_callback=rate_limit_callback,
                clock=clock,
            )
        )
        application = AccountOverviewApplication(
            balance, prices, JsonAccountOverviewStore(overview_directory)
        )
        return application.run(
            max_observation_span_seconds=max_observation_span_seconds,
            progress_callback=progress_callback,
        )

"""Thin orchestration for one complete read-only account snapshot run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from phalanx.config import load_kis_credentials
from phalanx.domain import AccountSnapshot
from phalanx.kis import KisBalanceClient, KisTokenManager
from phalanx.snapshots import SnapshotStore

_APPLICATION_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class _BalanceReader(Protocol):
    def fetch_balance(self) -> AccountSnapshot: ...


class _SnapshotWriter(Protocol):
    def save(self, snapshot: AccountSnapshot) -> Path: ...


@dataclass(frozen=True)
class AccountSnapshotResult:
    """A complete immutable observation and its safely persisted path."""

    snapshot: AccountSnapshot
    saved_path: Path


class AccountSnapshotApplication:
    """Persist a balance only after every read-only page completed successfully."""

    def __init__(self, balance_reader: _BalanceReader, snapshot_writer: _SnapshotWriter) -> None:
        self._balance_reader = balance_reader
        self._snapshot_writer = snapshot_writer

    def run(self) -> AccountSnapshotResult:
        """Fetch, then atomically store, one complete account snapshot."""

        snapshot = self._balance_reader.fetch_balance()
        saved_path = self._snapshot_writer.save(snapshot)
        return AccountSnapshotResult(snapshot=snapshot, saved_path=saved_path)


def run_production_snapshot(
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    snapshot_directory: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> AccountSnapshotResult:
    """Build the fixed real-account production graph and execute it once.

    Paths and transport are injectable for isolated tests, but are not exposed as
    CLI options. With no injection, each component resolves its fixed external
    production path at execution time.
    """

    credentials = load_kis_credentials(credentials_path)
    with httpx.Client(transport=transport, timeout=_APPLICATION_TIMEOUT) as http_client:
        token_manager = KisTokenManager(
            credentials,
            cache_path=token_cache_path,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        balance_client = KisBalanceClient(
            credentials,
            token_manager,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        application = AccountSnapshotApplication(
            balance_client,
            SnapshotStore(snapshot_directory),
        )
        return application.run()


__all__ = [
    "AccountSnapshotApplication",
    "AccountSnapshotResult",
    "run_production_snapshot",
]

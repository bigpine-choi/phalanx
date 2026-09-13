from __future__ import annotations

import os
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from discovery_helpers import provider
from history_helpers import CODES, END, NOW, START, Reader, bar, job

from phalanx.discovery.errors import DiscoveryError
from phalanx.discovery.service import DiscoveryService
from phalanx.domain.discovery import Market
from phalanx.domain.price_history import HistoryAttempt, HistoryResult, SymbolHistory, SymbolStatus
from phalanx.market_data.history.errors import HistoryError, HistoryFetchError, HistoryStorageError
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.market_data.history.service import HistoryService


def test_frozen_input_order_provenance_and_separate_adjusted_jobs(tmp_path: Path) -> None:
    service, view, discovery = job(tmp_path)
    before = discovery.path.read_bytes()
    reader = Reader()
    first = service.run(view.job.job_id, reader.factory)
    repository = service.repository
    assert repository.load(view.job.job_id) == first
    assert discovery.path.read_bytes() == before
    assert tuple(t.short_code for t in first.job.targets) == CODES
    assert first.job.targets[1].standard_code == "KR70001A0001"
    assert all(t.source_files and t.policy_version for t in first.job.targets)
    assert (first.job.market_division, first.job.period_division, first.job.adjustment) == (
        "J",
        "D",
        "0",
    )
    assert repository.read_bars(view.job.job_id, "0001A0") == (bar("0001A0"),)
    assert '"close_price":"110.0010"' in first.symbols[1].model_dump_json()
    assert repository.path.stat().st_mode & 0o777 == 0o600
    assert repository.path.parent.stat().st_mode & 0o777 == 0o700
    # New source refreshes never retarget or rewrite old jobs.
    latest = DiscoveryService(discovery, provider()).refresh()
    assert repository.load(view.job.job_id) == first
    assert latest.run_id != first.job.discovery_run_id
    second = service.create(discovery, view.job.discovery_run_id, START, END, codes=CODES[::-1])
    changed = Reader({code: (bar(code, "111"),) for code in CODES})
    second = service.run(second.job.job_id, changed.factory)
    assert changed.calls == list(CODES[::-1])
    assert first.job.job_id != second.job.job_id
    assert first.symbols[0].result.sha256 != second.symbols[1].result.sha256
    assert repository.load(view.job.job_id) == first


def test_exact_discovery_run_never_falls_back_and_noneligible_is_rejected(tmp_path: Path) -> None:
    service, view, discovery = job(tmp_path)
    failed = DiscoveryService(discovery, provider({market: 500 for market in Market})).refresh()
    for run_id, error_code in [("missing", "RUN_NOT_FOUND"), (failed.run_id, "RUN_NOT_SUCCESSFUL")]:
        with pytest.raises(DiscoveryError) as error:
            service.create(discovery, run_id, START, END, all_eligible=True)
        assert error.value.code == error_code
    discovery.begin("still-running", NOW)
    with pytest.raises(DiscoveryError, match="성공"):
        discovery.load_successful_run("still-running")
    with pytest.raises(HistoryError) as error:
        service.create(discovery, view.job.discovery_run_id, START, END, codes=("999999",))
    assert error.value.code == "NOT_ELIGIBLE"
    assert service.repository.load(view.job.job_id) == view


@pytest.mark.parametrize(
    "options", [{}, {"codes": CODES, "all_eligible": True}, {"codes": ("005930",) * 2}]
)
def test_explicit_unambiguous_target_selection(tmp_path: Path, options: dict) -> None:
    service, view, discovery = job(tmp_path)
    with pytest.raises(HistoryError):
        service.create(discovery, view.job.discovery_run_id, START, END, **options)


def test_end_date_uses_seoul_today_and_exact_dates(tmp_path: Path) -> None:
    original, view, discovery = job(tmp_path)
    service = HistoryService(
        original.repository, clock=lambda: datetime(2026, 8, 31, 15, tzinfo=UTC)
    )  # September 1 in Seoul.
    service.create(discovery, view.job.discovery_run_id, START, END, all_eligible=True)
    with pytest.raises(HistoryError) as error:
        service.create(discovery, view.job.discovery_run_id, START, date(2026, 9, 1), codes=CODES)
    assert error.value.code == "INVALID_END_DATE"


def test_limit_resume_skip_and_empty_result_meaning(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    reader = Reader({"005930": (bar("005930"),), "0001A0": ()})
    limited = service.run(view.job.job_id, reader.factory, max_symbols=1)
    assert reader.calls == ["005930"]
    assert [s.status for s in limited.symbols] == ["completed", "pending"]
    with pytest.raises(HistoryError, match="pending"):
        service.repository.read_bars(view.job.job_id, "0001A0")
    completed = service.run(view.job.job_id, reader.factory)
    assert reader.calls == list(CODES)
    assert completed.complete
    assert completed.symbols[0] == limited.symbols[0]
    assert completed.symbols[1].status == "empty"
    assert completed.symbols[1].result.row_count == 0
    assert completed.symbols[1].result.first_trade_date is None
    assert completed.symbols[1].result.trading_day_completeness == "unverified"
    assert service.repository.read_bars(view.job.job_id, "0001A0") == ()
    service.run(view.job.job_id, reader.factory, retry_failed=True)
    assert reader.opened == 2
    assert reader.calls == list(CODES)


@pytest.mark.parametrize("common", [False, True])
def test_symbol_failure_continues_common_failure_stops_and_retry_is_explicit(
    tmp_path: Path, common: bool
) -> None:
    service, view, _ = job(tmp_path)
    error = HistoryFetchError("TEST_FAILURE", "safe error", common=common)
    reader = Reader({"005930": error, "0001A0": (bar("0001A0"),)})
    failed = service.run(view.job.job_id, reader.factory)
    assert failed.symbols[0].status == "failed"
    assert failed.symbols[0].attempts[0].error_code == "TEST_FAILURE"
    assert failed.symbols[1].status == ("pending" if common else "completed")
    reader.outcomes["005930"] = (bar("005930"),)
    service.run(view.job.job_id, reader.factory)
    assert reader.calls == list(CODES)
    retried = service.run(view.job.job_id, reader.factory, retry_failed=True)
    assert reader.calls == [*CODES, "005930"]
    assert retried.complete
    assert [a.outcome for a in retried.symbols[0].attempts] == ["failed", "completed"]


def test_ctrl_c_preserves_completed_and_restarts_whole_incomplete_symbol(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    reader = Reader({"005930": (bar("005930"),), "0001A0": KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        service.run(view.job.job_id, reader.factory)
    stopped = service.repository.load(view.job.job_id)
    assert stopped.symbols[0].status == "completed"
    assert stopped.symbols[1].status == "pending"
    assert stopped.symbols[1].attempts[0].outcome == "interrupted"
    reader.outcomes["0001A0"] = (bar("0001A0"),)
    resumed = service.run(view.job.job_id, reader.factory)
    assert resumed.complete
    assert reader.calls == [*CODES, "0001A0"]
    assert resumed.symbols[0] == stopped.symbols[0]


def test_process_death_recovers_open_attempt_with_no_invented_end_time(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    before = view.symbols[0]
    active = SymbolHistory(
        ordinal=0,
        status=SymbolStatus.IN_PROGRESS,
        attempts=(HistoryAttempt(number=1, started_at=NOW, outcome="in_progress"),),
    )
    service.repository.save_symbol(view.job.job_id, before, active)
    resumed = service.run(view.job.job_id, Reader().factory)
    attempt = resumed.symbols[0].attempts[0]
    assert attempt.outcome == "interrupted"
    assert attempt.finished_at is None
    assert attempt.recovered_at == NOW
    assert attempt.error_code == "PROCESS_INTERRUPTED"
    assert resumed.complete


def test_storage_failure_rolls_back_whole_symbol_and_stops_then_resumes(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    repository = service.repository
    reader = Reader()
    first = service.run(view.job.job_id, reader.factory, max_symbols=1)
    # Abort the real SQLite update of a completed result; BEGIN and pending state survive.
    with sqlite3.connect(repository.path) as connection:
        connection.execute("""CREATE TRIGGER fail_completion AFTER UPDATE ON symbols
            WHEN json_extract(NEW.state_json, '$.status') IN ('completed', 'empty')
            BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    with pytest.raises(HistoryStorageError):
        service.run(view.job.job_id, reader.factory)
    stored = repository.load(view.job.job_id)
    assert stored.symbols[0] == first.symbols[0]
    assert stored.symbols[1].status == "in_progress"
    assert stored.symbols[1].result is None
    with sqlite3.connect(repository.path) as connection:
        connection.execute("DROP TRIGGER fail_completion")
    resumed = service.run(view.job.job_id, reader.factory)
    assert resumed.complete
    assert reader.calls == [*CODES, "0001A0"]


def test_same_job_lock_blocks_other_repository_and_no_write_transaction_during_fetch(
    tmp_path: Path,
) -> None:
    service, view, _ = job(tmp_path)
    other = HistoryService(SqliteHistoryRepository(service.repository.path))

    class ConcurrentReader(Reader):
        def fetch_daily_bars(self, code: str, start: date, end: date):
            competitor = Reader()
            with pytest.raises(HistoryError) as error:
                other.run(view.job.job_id, competitor.factory)
            assert error.value.code == "JOB_BUSY"
            assert not competitor.calls and not competitor.opened
            with sqlite3.connect(service.repository.path, timeout=0) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            return super().fetch_daily_bars(code, start, end)

    assert service.run(view.job.job_id, ConcurrentReader().factory).complete


def test_completed_result_cannot_be_overwritten_even_by_stale_writer(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    finished = service.run(view.job.job_id, Reader().factory)
    for before in (view.symbols[0], finished.symbols[0]):
        with pytest.raises(HistoryStorageError):
            service.repository.save_symbol(view.job.job_id, before, view.symbols[0])
    assert service.repository.load(view.job.job_id) == finished


@pytest.mark.parametrize("failure", ["symlink", "permissions", "hardlink"])
def test_unsafe_history_store_is_rejected(tmp_path: Path, failure: str) -> None:
    service, view, _ = job(tmp_path)
    path = service.repository.path
    if failure == "symlink":
        moved = path.with_suffix(".real")
        path.rename(moved)
        path.symlink_to(moved)
    elif failure == "permissions":
        path.chmod(0o644)
    else:
        os.link(path, path.with_suffix(".link"))
    with pytest.raises(HistoryStorageError):
        service.repository.load(view.job.job_id)


def test_invalid_provider_rows_fail_explicitly_without_poisoning_next_symbol(
    tmp_path: Path,
) -> None:
    service, view, _ = job(tmp_path)
    reader = Reader({"005930": (bar("0001A0"),), "0001A0": (bar("0001A0"),)})
    result = service.run(view.job.job_id, reader.factory)
    assert result.symbols[0].error_code == "DATA_CONFLICT"
    assert result.symbols[1].status == "completed"


def test_result_hash_tampering_is_rejected_on_read(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    result = service.run(view.job.job_id, Reader().factory).symbols[0].result
    assert isinstance(result, HistoryResult)
    with sqlite3.connect(service.repository.path) as connection:
        connection.execute(
            "UPDATE symbols SET state_json=replace(state_json, ?, ?) WHERE ordinal=0",
            (result.sha256, "0" * 64),
        )
    with pytest.raises(HistoryStorageError):
        service.repository.load(view.job.job_id)


def test_process_exit_releases_lock_and_resumes_without_retry_failed(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    pid = os.fork()
    if pid == 0:
        try:
            with service.repository.execution_lock(view.job.job_id):
                active = SymbolHistory(
                    ordinal=0,
                    status=SymbolStatus.IN_PROGRESS,
                    attempts=(HistoryAttempt(number=1, started_at=NOW, outcome="in_progress"),),
                )
                service.repository.save_symbol(view.job.job_id, view.symbols[0], active)
                os._exit(0)  # no Python context manager cleanup
        except BaseException:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    result = service.run(view.job.job_id, Reader().factory)
    assert result.complete
    assert result.symbols[0].attempts[0].error_code == "PROCESS_INTERRUPTED"


def test_unsupported_eligible_identifier_is_recorded_and_never_requested(tmp_path: Path) -> None:
    service, view, discovery = job(tmp_path)
    snapshot = discovery.load_successful_run(view.job.discovery_run_id)
    market = snapshot.markets[0]
    candidate = market.candidates[0]
    unsupported = candidate.model_copy(
        update={"record": candidate.record.model_copy(update={"short_code": "0001a0"})}
    )
    revised = snapshot.model_copy(
        update={
            "markets": (
                market.model_copy(update={"candidates": (unsupported,)}),
                snapshot.markets[1],
            )
        }
    )

    class Source:
        def load_successful_run(self, run_id: str):
            assert run_id == revised.run_id
            return revised

    created = service.create(Source(), revised.run_id, START, END, all_eligible=True)
    assert created.job.targets[0].short_code == "0001a0"
    assert created.symbols[0].status == "unsupported"
    reader = Reader()
    completed = service.run(created.job.job_id, reader.factory, retry_failed=True)
    assert reader.calls == ["0001A0"]
    assert completed.counts["unsupported"] == 1
    assert completed.symbols[0].error_code == "UNSUPPORTED_IDENTIFIER"
    assert not completed.complete


def test_excluded_candidate_cannot_be_selected(tmp_path: Path) -> None:
    from discovery_helpers import archive, master

    service, _, discovery = job(tmp_path)
    snapshot = DiscoveryService(
        discovery,
        provider(
            {
                Market.KOSPI: archive(Market.KOSPI, master(patches={219: b"1"})),
                Market.KOSDAQ: archive(Market.KOSDAQ, master(Market.KOSDAQ)),
            }
        ),
    ).refresh()
    assert snapshot.status == "success"
    assert snapshot.markets[0].candidates[0].decision.status == "excluded"
    with pytest.raises(HistoryError) as error:
        service.create(discovery, snapshot.run_id, START, END, codes=("005930",))
    assert error.value.code == "NOT_ELIGIBLE"
    only_eligible = service.create(discovery, snapshot.run_id, START, END, all_eligible=True)
    assert len(only_eligible.job.targets) == 1
    assert only_eligible.job.targets[0].market == Market.KOSDAQ


def test_symbol_write_failure_stops_before_next_network_call(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    with sqlite3.connect(service.repository.path) as connection:
        connection.execute("""CREATE TRIGGER fail_result AFTER UPDATE ON symbols
            WHEN json_extract(NEW.state_json, '$.result') IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'disk full'); END""")
    reader = Reader()
    with pytest.raises(HistoryStorageError):
        service.run(view.job.job_id, reader.factory)
    assert reader.calls == ["005930"]
    assert service.repository.load(view.job.job_id).symbols[1].status == "pending"


def test_manual_universe_account_nav_and_user_directories_untouched(tmp_path: Path) -> None:
    from phalanx.domain.universe import KoreanStock, StockMarket
    from phalanx.universe.repository import JsonUniverseRepository

    manual = JsonUniverseRepository(tmp_path / "manual" / "universe.json")
    manual.add(KoreanStock(stock_code="005930", stock_name="수동 이름", market=StockMarket.KOSPI))
    preserved = {manual.path: manual.path.read_bytes()}
    for relative in (
        "account/snapshot.json",
        "nav/ledger.sqlite3",
        "reports/report.md",
        "research/note.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve this user data")
        preserved[path] = path.read_bytes()
    service, view, _ = job(tmp_path)
    service.run(view.job.job_id, Reader().factory)
    assert all(path.read_bytes() == contents for path, contents in preserved.items())


def test_run_recovers_hot_sqlite_journal_after_process_exit(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    pid = os.fork()
    if pid == 0:
        try:
            with (
                service.repository.execution_lock(view.job.job_id),
                sqlite3.connect(service.repository.path) as connection,
            ):
                # Force dirty pages onto disk before commit, leaving a hot journal.
                connection.execute("PRAGMA cache_size=1")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE symbols SET state_json=?", ("x" * 200_000,))
                os._exit(0)
        except BaseException:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    journal = service.repository.path.with_name(service.repository.path.name + "-journal")
    assert journal.exists()
    reader = Reader()
    result = service.run(view.job.job_id, reader.factory)
    assert result.complete
    assert reader.calls == list(CODES)
    assert not journal.exists()


def test_discovery_database_cannot_be_used_as_history_database(tmp_path: Path) -> None:
    _, view, discovery = job(tmp_path)
    before = discovery.path.read_bytes()
    repository = SqliteHistoryRepository(discovery.path)
    with pytest.raises(HistoryStorageError):
        repository.create(view)
    assert discovery.path.read_bytes() == before

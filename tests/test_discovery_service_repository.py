from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from discovery_helpers import archive, master, provider

from phalanx.discovery.errors import DiscoveryStorageError
from phalanx.discovery.repository import SqliteDiscoveryRepository, default_discovery_path
from phalanx.discovery.service import DiscoveryService
from phalanx.domain.discovery import Eligibility, Market
from phalanx.domain.universe import KoreanStock, StockMarket
from phalanx.universe.repository import JsonUniverseRepository


def test_round_trip_determinism_source_files_and_manual_universe_preservation(
    tmp_path: Path,
) -> None:
    manual = JsonUniverseRepository(tmp_path / "data" / "universe.json")
    manual.add(KoreanStock(stock_code="005930", stock_name="수동 이름", market=StockMarket.KOSPI))
    original = manual.path.read_bytes()
    repository = SqliteDiscoveryRepository(tmp_path / "data" / "discovery" / "discovery.sqlite3")
    service = DiscoveryService(repository, provider())
    first = service.refresh()
    second = service.refresh()
    assert first.status == second.status == "success"
    assert first.run_id != second.run_id
    assert repository.load().snapshot == second
    for left, right in zip(first.markets, second.markets, strict=True):
        assert left.candidates == right.candidates
        assert left.sources == right.sources
        assert right.counts == {"eligible": 1, "excluded": 0, "unknown": 0}
        assert right.provider_as_of is None
        assert right.http_last_modified is not None
        assert right.market_completeness == "unverified"
        assert right.collection_started_at.tzinfo is not None
        for source in right.sources:
            data = repository.read_source(second.run_id, right.market, source.filename)
            assert hashlib.sha256(data).hexdigest() == source.sha256
            assert len(data) == source.size_bytes
            if source.filename.endswith(".mst"):
                assert data == master(right.market)
    assert manual.path.read_bytes() == original
    assert repository.path.stat().st_mode & 0o777 == 0o600
    assert repository.path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    ("failure", "download_status", "parse_status", "issue"),
    [
        (503, "failed", "not_attempted", "DOWNLOAD_HTTP"),
        (b"broken zip", "success", "failed", "ZIP_INVALID"),
        (archive(Market.KOSDAQ, b""), "success", "failed", "EMPTY_MASTER"),
        (
            archive(Market.KOSDAQ, master(Market.KOSDAQ) + b"\ntruncated"),
            "success",
            "failed",
            "RECORD_WIDTH",
        ),
    ],
)
def test_market_failure_preserves_success_and_each_market_result(
    tmp_path: Path, failure: bytes | int, download_status: str, parse_status: str, issue: str
) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "discovery" / "data.sqlite3")
    first = DiscoveryService(repository, provider()).refresh()
    source = provider({Market.KOSPI: archive(Market.KOSPI, master()), Market.KOSDAQ: failure})
    attempt = DiscoveryService(repository, source).refresh()
    assert attempt.status == "partial"
    good, failed = attempt.markets
    assert good.successful
    assert failed.download_status == download_status
    assert failed.parse_status == parse_status
    assert failed.issues[0].code == issue
    view = repository.load()
    assert view.snapshot == first
    assert view.latest_snapshot == attempt
    assert view.degraded
    assert view.latest_attempt.run_id == attempt.run_id


def test_both_markets_fail_and_no_normal_snapshot(tmp_path: Path) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    attempt = DiscoveryService(
        repository, provider({Market.KOSPI: 500, Market.KOSDAQ: 503})
    ).refresh()
    assert attempt.status == "failed"
    assert all(m.download_status == "failed" for m in attempt.markets)
    assert repository.load().snapshot == attempt
    assert repository.load().degraded


@pytest.mark.parametrize(
    ("patches", "reason"),
    [
        ({}, "DUPLICATE_RECORD"),
        ({219: b"1"}, "RECORD_CONFLICT"),
        ({0: b"000660"}, "RECORD_CONFLICT"),
        ({9: b"KR7000660001"}, "RECORD_CONFLICT"),
    ],
)
def test_duplicates_and_conflicts_keep_all_rows(
    tmp_path: Path, patches: dict[int, bytes], reason: str
) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    source = provider(
        {
            Market.KOSPI: archive(Market.KOSPI, master() + b"\n" + master(patches=patches)),
            Market.KOSDAQ: archive(Market.KOSDAQ, master(Market.KOSDAQ)),
        }
    )
    snapshot = DiscoveryService(repository, source).refresh()
    market = snapshot.markets[0]
    assert snapshot.status == "partial"
    assert market.parse_status == "conflict"
    assert market.total_records == len(market.candidates) == 2
    assert market.candidates[0].decision.status == Eligibility.UNKNOWN
    for candidate in market.candidates:
        assert reason in {r.code for r in candidate.decision.reasons}
    if 219 in patches:
        assert market.candidates[1].decision.status == Eligibility.EXCLUDED


def test_cross_market_identifier_conflict(tmp_path: Path) -> None:
    source = provider(
        {
            Market.KOSPI: archive(Market.KOSPI, master()),
            Market.KOSDAQ: archive(Market.KOSDAQ, master(Market.KOSDAQ, {0: b"005930"})),
        }
    )
    result = DiscoveryService(
        SqliteDiscoveryRepository(tmp_path / "d" / "d.sqlite3"), source
    ).refresh()
    assert result.status == "failed"
    assert all(m.parse_status == "conflict" for m in result.markets)
    assert all(m.counts["unknown"] == 1 for m in result.markets)


def test_sql_failure_after_artifact_insert_rolls_back_entire_snapshot(tmp_path: Path) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    service = DiscoveryService(repository, provider())
    first = service.refresh()
    # Abort during the final UPDATE after all source BLOB inserts have happened.
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_snapshot BEFORE UPDATE OF snapshot_json ON runs "
            "BEGIN SELECT RAISE(ABORT, 'simulated disk write failure'); END"
        )
    with pytest.raises(DiscoveryStorageError):
        service.refresh()
    view = repository.load()
    assert view.snapshot == first
    assert view.latest_attempt.status == "storage_failed"
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT count(*) FROM source_files").fetchone()[0] == 4
        assert (
            connection.execute("SELECT count(*) FROM runs WHERE status='success'").fetchone()[0]
            == 1
        )


def test_interrupted_or_unwritable_run_is_visible_without_replacing_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    service = DiscoveryService(repository, provider())
    first = service.refresh()

    def fail(*args: object) -> None:
        raise DiscoveryStorageError()

    monkeypatch.setattr(repository, "save", fail)
    monkeypatch.setattr(repository, "storage_failed", fail)
    with pytest.raises(DiscoveryStorageError):
        service.refresh()
    view = repository.load()
    assert view.snapshot == first
    assert view.latest_attempt.status == "in_progress"
    assert view.degraded


def test_start_failure_does_not_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    source = provider()
    monkeypatch.setattr(
        repository, "begin", lambda *args: (_ for _ in ()).throw(DiscoveryStorageError())
    )
    monkeypatch.setattr(
        source, "download", lambda *args: pytest.fail("must not download before durable start")
    )
    with pytest.raises(DiscoveryStorageError):
        DiscoveryService(repository, source).refresh()


def test_default_path_and_missing_read_are_offline_and_nonmutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert default_discovery_path() == tmp_path / ".local/share/phalanx/discovery/discovery.sqlite3"
    repository = SqliteDiscoveryRepository()
    assert repository.load().snapshot is None
    assert not repository.path.parent.exists()


def test_corrupt_database_and_unsafe_paths(tmp_path: Path) -> None:
    directory = tmp_path / "d"
    directory.mkdir(mode=0o700)
    path = directory / "data.sqlite3"
    path.write_bytes(b"not sqlite")
    path.chmod(0o600)
    with pytest.raises(DiscoveryStorageError):
        SqliteDiscoveryRepository(path).load()
    link = directory / "link.sqlite3"
    link.symlink_to(path)
    with pytest.raises(DiscoveryStorageError):
        SqliteDiscoveryRepository(link).begin("test", datetime.now(UTC))
    assert path.read_bytes() == b"not sqlite"


def test_recovered_source_hash_is_verified(tmp_path: Path) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    snapshot = DiscoveryService(repository, provider()).refresh()
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE source_files SET payload=x'00'")
    with pytest.raises(DiscoveryStorageError):
        repository.read_source(snapshot.run_id, Market.KOSPI, "kospi_code.mst")


def test_v1_snapshot_is_not_reinterpreted_or_overwritten_when_v2_is_active(tmp_path: Path) -> None:
    from phalanx.domain.discovery import Snapshot

    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    payloads = {
        market: archive(market, master(market, {83 if market == Market.KOSPI else 79: b" "}))
        for market in Market
    }
    service = DiscoveryService(repository, provider(payloads))
    template = service.refresh()
    legacy = template.model_dump(mode="json")
    legacy["run_id"] = "persisted-v1"
    artifacts = {}
    for market in legacy["markets"]:
        market["policy_version"] = "domestic-common-stock-v1"
        for candidate in market["candidates"]:
            # Fixed historical expectation, not a reimplementation of the old policy.
            candidate["decision"] = {
                "policy_version": "domestic-common-stock-v1",
                "status": "unknown",
                "reasons": [
                    {
                        "code": "MISSING_REQUIRED_FIELD",
                        "description": "필수 정보 누락: etp_prod_cls_code",
                        "field": "etp_prod_cls_code",
                        "kind": "unknown",
                    }
                ],
            }
        for source in market["sources"]:
            key = (Market(market["market"]), source["filename"])
            artifacts[key] = repository.read_source(template.run_id, *key)
    historical = Snapshot.model_validate(legacy)
    repository.begin(historical.run_id, historical.collection_started_at)
    repository.save(historical, artifacts)
    assert service.view().snapshot == historical
    before = historical.model_dump_json()

    current = service.refresh()
    assert current.run_id != historical.run_id
    for old, new in zip(historical.markets, current.markets, strict=True):
        assert old.sources == new.sources
        assert old.candidates[0].record == new.candidates[0].record
        assert old.counts["unknown"] == 1
        assert new.counts["eligible"] == 1
        assert new.policy_version == "domestic-common-stock-v2"
    with sqlite3.connect(repository.path) as connection:
        stored = connection.execute(
            "SELECT snapshot_json FROM runs WHERE run_id=?", (historical.run_id,)
        ).fetchone()[0]
    assert stored == before
    for key, payload in artifacts.items():
        assert repository.read_source(historical.run_id, *key) == payload
    assert repository.load().snapshot == current

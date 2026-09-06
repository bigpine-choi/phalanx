from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

import phalanx.nav.storage as storage_module
from phalanx.nav.models import InputBundle, NavError
from phalanx.nav.storage import NavStorageError, NavStore


def _day(day: str = "2026-01-01", **changes: Any) -> dict[str, Any]:
    return {
        "date": day,
        "ledger_complete": True,
        "prices": {"SYNTHETIC": "10"},
        "benchmark_close": "100",
        "source_ref": "synthetic valuation",
        **changes,
    }


def _event(event_id: str = "deposit-1", **changes: Any) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "date": "2026-01-02",
        "sequence": 1,
        "kind": "deposit",
        "amount": "100",
        "source_ref": "synthetic ledger",
        **changes,
    }


def _bundle(
    *,
    inception: bool = True,
    days: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    environment: str = "development",
) -> InputBundle:
    return InputBundle.model_validate(
        {
            "schema_version": "1",
            "series_id": "synthetic",
            "environment": environment,
            "inception": {
                "series_id": "synthetic",
                "environment": environment,
                "inception_date": "2026-01-01",
                "initial_state": {
                    "cash": "1000",
                    "positions": {"SYNTHETIC": "10"},
                    "receivables": {"opening-income": "20"},
                    "payables": {"opening-fee": "10"},
                },
                "cash_flow_policy": "previous_close_unit_value",
                "benchmark_id": "KOSPI_TR",
                "source_ref": "synthetic user-selected inception",
            }
            if inception
            else None,
            "days": [_day()] if days is None else days,
            "events": [] if events is None else events,
        }
    )


def _import(store: NavStore, bundle: InputBundle) -> dict[str, int]:
    return store.import_bundle(
        bundle, raw_payload=(bundle.model_dump_json(indent=2) + "\n").encode()
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_private_database_reopen_preserves_decimal_state_and_exact_original(tmp_path: Path) -> None:
    path = tmp_path / "private" / "nav.sqlite3"
    bundle = _bundle()
    payload = (bundle.model_dump_json(indent=2) + "\n").encode("utf-16")
    with NavStore(path, create=True) as store:
        stats = store.import_bundle(bundle, raw_payload=payload)
        expected = store.restore("synthetic", "development", date(2026, 1, 1))
        assert stats["created_series"] == 1
        assert expected[0].nav == Decimal("1110")
        assert expected[0].unit_value == Decimal("1000")
        assert expected[0].state == bundle.inception.initial_state  # type: ignore[union-attr]
        assert _mode(path) == 0o600
        assert _mode(path.parent) == 0o700
        assert set(path.parent.iterdir()) == {path}

    with NavStore(path) as reopened:
        assert reopened.query("synthetic", "development") == expected
        history = reopened.history("synthetic", "development")
    source = history["source_imports"][0]
    assert base64.b64decode(source["raw_payload_base64"]) == payload
    assert source["sha256"] == hashlib.sha256(payload).hexdigest()
    assert history["inception"]["initial_state"]["receivables"] == {"opening-income": "20"}
    assert history["calculations"][0]["days"][0]["nav"] == "1110"
    json.dumps(history)


def test_same_import_and_historical_revision_retries_do_not_apply_twice(tmp_path: Path) -> None:
    path = tmp_path / "nav.sqlite3"
    first = _bundle(days=[_day(), _day("2026-01-02")], events=[_event()])
    correction = _bundle(
        inception=False,
        days=[],
        events=[_event(amount="200", revision=2, correction_reason="corrected synthetic receipt")],
    )
    with NavStore(path, create=True) as store:
        _import(store, first)
        before = store.restore("synthetic", "development", date(2026, 1, 2))
        stats = _import(store, first)
        assert stats["inserted_sources"] == stats["inserted_events"] == stats["inserted_days"] == 0
        assert stats["unchanged_events"] == 1
        assert store.query("synthetic", "development") == before
        assert store.restore("synthetic", "development", date(2026, 1, 2)) == before

        _import(store, correction)
        corrected = store.restore("synthetic", "development", date(2026, 1, 2))
        _import(store, first)
        assert store.restore("synthetic", "development", date(2026, 1, 2)) == corrected
        assert corrected[-1].nav == Decimal("1310")
        assert corrected[-1].external_flow == Decimal("200")
        assert len(store.history("synthetic", "development")["events"]) == 2


def test_conflicting_import_rolls_back_entire_source_and_revision_batch(tmp_path: Path) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        original = _bundle(events=[_event()])
        _import(store, original)
        expected = store.restore("synthetic", "development", date(2026, 1, 1))
        conflict = _bundle(
            inception=False,
            days=[_day("2026-01-02")],
            events=[_event("otherwise-valid-new-event", sequence=2), _event(amount="999")],
        )
        with pytest.raises(NavStorageError, match="conflicting content"):
            _import(store, conflict)
        assert store.query("synthetic", "development") == expected
        history = store.history("synthetic", "development")
        assert len(history["source_imports"]) == 1
        assert len(history["events"]) == 1
        assert len(history["days"]) == 1


@pytest.mark.parametrize("revision", [2, 4])
def test_new_event_requires_revision_one(tmp_path: Path, revision: int) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(store, _bundle())
        with pytest.raises(NavStorageError, match="start at 1"):
            _import(
                store, _bundle(events=[_event(revision=revision, correction_reason="synthetic")])
            )
        assert store.history("synthetic", "development")["events"] == []


def test_corrections_require_contiguous_revisions(tmp_path: Path) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(store, _bundle(events=[_event()]))
        with pytest.raises(NavStorageError, match="without gaps"):
            _import(
                store, _bundle(events=[_event(revision=3, correction_reason="skipped revision")])
            )


def test_changed_daily_input_invalidates_current_view_preserving_all_audits(tmp_path: Path) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(store, _bundle(days=[_day(), _day("2026-01-02"), _day("2026-01-03")]))
        old = store.restore("synthetic", "development", date(2026, 1, 3))
        correction = _bundle(
            inception=False,
            days=[
                _day(
                    "2026-01-02",
                    prices={"SYNTHETIC": "20"},
                    revision=2,
                    correction_reason="correct synthetic closing price",
                )
            ],
        )
        stats = _import(store, correction)
        assert stats["invalidated_days"] == 3
        assert store.query("synthetic", "development") == ()
        history = store.history("synthetic", "development")
        assert len(history["days"]) == 4
        assert history["calculations"][0]["days"][1] == old[1].model_dump(mode="json")
        # Earlier --through must not shorten the previously materialized horizon.
        replay = store.restore("synthetic", "development", date(2026, 1, 2))
        assert len(replay) == 3
        assert replay[1].nav == Decimal("1210")
        assert replay[2].daily_return != old[2].daily_return
        runs = store.history("synthetic", "development")["calculations"]
        assert len(runs) == 2
        assert runs[0]["input_manifest"]["days"][1]["revision"] == 1
        assert runs[1]["input_manifest"]["days"][1]["revision"] == 2
        assert runs[0]["input_sha256"] != runs[1]["input_sha256"]
        for run in runs:
            canonical_inputs = json.dumps(
                run["input_manifest"], sort_keys=True, separators=(",", ":")
            ).encode()
            assert hashlib.sha256(canonical_inputs).hexdigest() == run["input_sha256"]


def test_moving_and_voiding_event_preserves_old_date_and_recalculates(tmp_path: Path) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(
            store, _bundle(days=[_day(), _day("2026-01-02"), _day("2026-01-03")], events=[_event()])
        )
        initial = store.restore("synthetic", "development", date(2026, 1, 3))
        _import(
            store,
            _bundle(
                inception=False,
                days=[],
                events=[
                    _event(
                        date="2026-01-03",
                        revision=2,
                        correction_reason="wrong receipt date",
                    )
                ],
            ),
        )
        moved = store.restore("synthetic", "development", date(2026, 1, 3))
        assert initial[1].external_flow == Decimal("100")
        assert moved[1].external_flow == 0
        assert moved[2].external_flow == Decimal("100")
        _import(
            store,
            _bundle(
                inception=False,
                days=[],
                events=[
                    _event(
                        date="2026-01-03",
                        void=True,
                        revision=3,
                        correction_reason="void synthetic duplicate",
                    )
                ],
            ),
        )
        voided = store.restore("synthetic", "development", date(2026, 1, 3))
        assert voided[-1].nav == Decimal("1110")
        events = store.history("synthetic", "development")["events"]
        assert [entry["input"]["revision"] for entry in events] == [1, 2, 3]
        assert events[0]["input"]["date"] == "2026-01-02"


def test_inception_cannot_be_reset_and_unknown_series_needs_explicit_inception(
    tmp_path: Path,
) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        with pytest.raises(NavStorageError, match="explicit inception"):
            _import(store, _bundle(inception=False))
        original = _bundle()
        _import(store, original)
        changed_data = original.model_dump(mode="json")
        changed_data["inception"]["inception_date"] = "2026-01-02"
        changed = InputBundle.model_validate(changed_data)
        with pytest.raises(NavStorageError, match="inception is immutable"):
            _import(store, changed)
        assert store.history("synthetic", "development")[
            "inception"
        ] == original.inception.model_dump(mode="json")  # type: ignore[union-attr]


def test_development_and_official_have_separate_explicit_inception_and_event_namespaces(
    tmp_path: Path,
) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(store, _bundle(events=[_event()]))
        with pytest.raises(NavStorageError, match="does not exist"):
            store.query("synthetic", "official")
        with pytest.raises(NavStorageError, match="explicit inception"):
            _import(store, _bundle(inception=False, environment="official"))
        _import(store, _bundle(environment="official", events=[_event(amount="999")]))
        dev = store.history("synthetic", "development")
        official = store.history("synthetic", "official")
        assert dev["events"][0]["input"]["amount"] == "100"
        assert official["events"][0]["input"]["amount"] == "999"
        assert len(dev["source_imports"]) == len(official["source_imports"]) == 1


@pytest.mark.parametrize("item", ["event", "day"])
def test_preinception_inputs_fail_atomically(tmp_path: Path, item: str) -> None:
    bundle = _bundle(
        events=[_event(date="2026-01-01")] if item == "event" else [],
        days=[_day("2025-12-31")] if item == "day" else [],
    )
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        with pytest.raises(NavStorageError):
            _import(store, bundle)
        with pytest.raises(NavStorageError, match="does not exist"):
            store.history("synthetic", "development")


def test_original_source_must_match_bundle_and_reject_ambiguous_json(tmp_path: Path) -> None:
    bundle = _bundle()
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        with pytest.raises(NavStorageError, match="does not match"):
            store.import_bundle(bundle, raw_payload=_bundle(days=[]).model_dump_json().encode())
        duplicate_key = bundle.model_dump_json().replace(
            '"schema_version":"1"', '"schema_version":"1","schema_version":"1"'
        )
        with pytest.raises(NavStorageError, match="not a valid"):
            store.import_bundle(bundle, raw_payload=duplicate_key.encode())


def test_replay_failure_keeps_prior_materialization_and_calculation_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with NavStore(tmp_path / "nav.sqlite3", create=True) as store:
        _import(store, _bundle())
        expected = store.restore("synthetic", "development", date(2026, 1, 1))

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise NavError("synthetic calculation failure")

        monkeypatch.setattr(storage_module, "calculate_daily_nav", fail)
        with pytest.raises(NavError, match="synthetic calculation failure"):
            store.restore("synthetic", "development", date(2026, 1, 2))
        assert store.query("synthetic", "development") == expected
        assert len(store.history("synthetic", "development")["calculations"]) == 1


def test_concurrent_store_imports_serialize_conflicting_corrections(tmp_path: Path) -> None:
    path = tmp_path / "nav.sqlite3"
    with NavStore(path, create=True) as store:
        _import(store, _bundle(events=[_event()]))
    barrier = Barrier(2)

    def correct(amount: str) -> str:
        with NavStore(path) as store:
            barrier.wait(timeout=10)
            try:
                _import(
                    store,
                    _bundle(
                        inception=False,
                        days=[],
                        events=[
                            _event(
                                amount=amount, revision=2, correction_reason="competing correction"
                            )
                        ],
                    ),
                )
            except NavStorageError as error:
                assert "conflicting content" in str(error)
                return "conflict"
            return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(correct, ["200", "300"])) == ["accepted", "conflict"]
    with NavStore(path) as store:
        history = store.history("synthetic", "development")
        assert len(history["events"]) == 2
        assert len(history["source_imports"]) == 2


def test_missing_store_read_does_not_create_directories_or_infer_settings(tmp_path: Path) -> None:
    path = tmp_path / "absent" / "nav.sqlite3"
    with pytest.raises(NavStorageError, match="does not exist"):
        NavStore(path)
    assert not path.parent.exists()


def test_failed_schema_install_leaves_no_final_file_and_can_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nav.sqlite3"
    schema = storage_module._SCHEMA
    monkeypatch.setattr(storage_module, "_SCHEMA", (*schema, "synthetic invalid SQL"))
    with pytest.raises(NavStorageError, match="safely open"):
        NavStore(path, create=True)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(storage_module, "_SCHEMA", schema)
    with NavStore(path, create=True) as store:
        _import(store, _bundle())
        assert store.restore("synthetic", "development", date(2026, 1, 1))[0].status == "confirmed"


def test_completed_install_recovers_reserved_temporary_hardlink_after_interruption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nav.sqlite3"
    with NavStore(path, create=True) as store:
        _import(store, _bundle())
    temporary_link = tmp_path / ".nav.sqlite3.0123456789abcdef.tmp"
    os.link(path, temporary_link)
    assert path.stat().st_nlink == 2
    with NavStore(path) as store:
        assert (
            store.history("synthetic", "development")["inception"]["inception_date"] == "2026-01-01"
        )
    assert not temporary_link.exists()
    assert path.stat().st_nlink == 1


def test_simultaneous_initializers_install_one_complete_database_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nav.sqlite3"
    barrier = Barrier(2)
    original = storage_module._write_initial_schema

    def prepare(temporary: Path) -> None:
        original(temporary)
        barrier.wait(timeout=10)

    monkeypatch.setattr(storage_module, "_write_initial_schema", prepare)

    def initialize(_: int) -> None:
        with NavStore(path, create=True) as store:
            _import(store, _bundle())

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(initialize, [1, 2]))
    assert set(tmp_path.iterdir()) == {path}
    with NavStore(path) as store:
        assert len(store.history("synthetic", "development")["source_imports"]) == 1


@pytest.mark.parametrize("target", ["database", "-journal", "-wal", "-shm"])
def test_database_and_sidecar_symlinks_never_followed(tmp_path: Path, target: str) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "nav.sqlite3"
    victim = tmp_path / "victim"
    victim.write_bytes(b"synthetic confidential sentinel")
    victim.chmod(0o600)
    unsafe = path if target == "database" else private / (path.name + target)
    unsafe.symlink_to(victim)
    with pytest.raises(NavStorageError):
        NavStore(path, create=True)
    assert victim.read_bytes() == b"synthetic confidential sentinel"
    assert unsafe.is_symlink()


def test_parent_symlink_and_insecure_existing_directory_are_not_repaired(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(NavStorageError):
        NavStore(link / "nav.sqlite3", create=True)
    assert list(real.iterdir()) == []
    real.chmod(0o755)
    with pytest.raises(NavStorageError):
        NavStore(real / "nav.sqlite3", create=True)
    assert _mode(real) == 0o755
    assert list(real.iterdir()) == []


@pytest.mark.parametrize("unsafe", ["mode", "hardlink", "owner"])
def test_unsafe_existing_database_is_rejected_without_modifying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    path = tmp_path / "nav.sqlite3"
    with NavStore(path, create=True) as store:
        _import(store, _bundle())
    original = path.read_bytes()
    if unsafe == "mode":
        path.chmod(0o644)
    elif unsafe == "hardlink":
        os.link(path, tmp_path / "other-name")
    else:
        monkeypatch.setattr(storage_module.os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(NavStorageError):
        NavStore(path)
    assert path.read_bytes() == original


def test_unsafe_journal_cannot_be_used_for_recovery(tmp_path: Path) -> None:
    path = tmp_path / "nav.sqlite3"
    with NavStore(path, create=True) as store:
        _import(store, _bundle())
    journal = tmp_path / "nav.sqlite3-journal"
    journal.write_bytes(b"synthetic journal")
    journal.chmod(0o644)
    with pytest.raises(NavStorageError, match="private"):
        NavStore(path)
    assert journal.read_bytes() == b"synthetic journal"
    assert _mode(journal) == 0o644


def test_unrelated_sqlite_database_is_not_initialized_or_replaced(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve')")
    path.chmod(0o600)
    original = path.read_bytes()
    with pytest.raises(NavStorageError, match="unrecognized"):
        NavStore(path, create=True)
    assert path.read_bytes() == original


def test_security_is_rechecked_before_operations_and_closed_store_errors_are_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nav.sqlite3"
    store = NavStore(path, create=True)
    try:
        _import(store, _bundle())
        path.chmod(0o644)
        with pytest.raises(NavStorageError, match="private"):
            store.query("synthetic", "development")
    finally:
        store.close()
    with pytest.raises(NavStorageError, match="closed"):
        store.query("synthetic", "development")


def test_sqlite_open_error_does_not_echo_driver_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("synthetic-secret-token")

    monkeypatch.setattr(storage_module.sqlite3, "connect", fail)
    with pytest.raises(NavStorageError) as caught:
        NavStore(tmp_path / "nav.sqlite3", create=True)
    assert "synthetic-secret-token" not in str(caught.value)

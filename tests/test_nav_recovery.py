"""Cross-layer regression checks using only the documented synthetic evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from phalanx.nav.engine import calculate_daily_nav
from phalanx.nav.models import InputBundle, NavError, parse_bundle_bytes
from phalanx.nav.storage import NavStore

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "daily-nav"


def _example(name: str) -> InputBundle:
    return parse_bundle_bytes((EXAMPLES / name).read_bytes())


def _import(store: NavStore, bundle: InputBundle) -> None:
    store.import_bundle(bundle, raw_payload=bundle.model_dump_json().encode())


def _complete() -> InputBundle:
    seed = _example("01-seed.json")
    completion = _example("02-complete.json")
    return InputBundle.model_validate(
        {
            **seed.model_dump(),
            "days": sorted((*seed.days, *completion.days), key=lambda day: day.date),
        }
    )


def test_daily_saved_and_reopened_results_match_one_batch_with_all_event_kinds(
    tmp_path: Path,
) -> None:
    bundle = _complete()
    daily_path = tmp_path / "daily" / "nav.sqlite3"
    bulk_path = tmp_path / "bulk" / "nav.sqlite3"
    assert bundle.inception is not None
    daily_rows = []
    for day in bundle.days:
        piece = InputBundle(
            schema_version="1",
            series_id=bundle.series_id,
            environment=bundle.environment,
            inception=bundle.inception if not daily_rows else None,
            events=tuple(event for event in bundle.events if event.date == day.date),
            days=(day,),
        )
        with NavStore(daily_path, create=True) as store:
            _import(store, piece)
            restored = store.restore(bundle.series_id, bundle.environment, day.date)
            assert list(restored[:-1]) == daily_rows
            daily_rows = list(restored)
        with NavStore(daily_path) as reopened:
            assert list(reopened.query(bundle.series_id, bundle.environment)) == daily_rows

    with NavStore(bulk_path, create=True) as store:
        _import(store, bundle)
        batch = store.restore(bundle.series_id, bundle.environment, bundle.days[-1].date)
        assert list(batch) == daily_rows
        assert all(row.status == "confirmed" for row in batch)
        _import(store, bundle)
        assert store.restore(bundle.series_id, bundle.environment, batch[-1].date) == batch
        assert store.query(bundle.series_id, bundle.environment) == batch


def test_fill_then_correct_then_move_event_replays_dependents_and_keeps_exact_sources(
    tmp_path: Path,
) -> None:
    seed = _example("01-seed.json")
    complete = _complete()
    correction = _example("03-correction.json")
    assert seed.inception is not None
    through = date(2026, 1, 9)
    path = tmp_path / "recovery" / "nav.sqlite3"
    with NavStore(path, create=True) as store:
        raw = (EXAMPLES / "01-seed.json").read_bytes()
        store.import_bundle(seed, raw_payload=raw)
        gap = store.restore(seed.series_id, seed.environment, through)
        assert [row.status for row in gap] == ["confirmed"] * 2 + ["pending"] * 3
        _import(store, _example("02-complete.json"))
        filled = store.restore(seed.series_id, seed.environment, through)
        assert all(row.status == "confirmed" for row in filled)
        _import(store, correction)
        assert store.query(seed.series_id, seed.environment) == ()

    with NavStore(path) as store:
        corrected = store.restore(seed.series_id, seed.environment, through)
        events = {event.event_id: event for event in complete.events}
        events.update({event.event_id: event for event in correction.events})
        days = {day.date: day for day in complete.days}
        days.update({day.date: day for day in correction.days})
        expected = calculate_daily_nav(
            seed.inception, tuple(events.values()), tuple(days.values()), through
        )
        assert corrected == expected
        assert corrected[0] == filled[0]
        assert corrected[1:] != filled[1:]

        # Moving a historical cash flow affects the old date AND every dependent date.
        original = events["withdrawal-1"]
        moved = original.model_copy(
            update={
                "date": date(2026, 1, 8),
                "sequence": 4,
                "revision": 2,
                "correction_reason": "synthetic:verified-cash-movement-date",
            }
        )
        changed = InputBundle(
            schema_version="1",
            series_id=seed.series_id,
            environment=seed.environment,
            events=(moved,),
        )
        _import(store, changed)
        events[moved.event_id] = moved
        replay = store.restore(seed.series_id, seed.environment, through)
        assert replay == calculate_daily_nav(
            seed.inception, tuple(events.values()), tuple(days.values()), through
        )
        assert replay[:2] == corrected[:2]
        assert replay[2:] != corrected[2:]
        history = store.history(seed.series_id, seed.environment)
        assert history["inception"]["inception_date"] == "2026-01-05"
        assert history["source_imports"][0]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert history["calculations"][0]["days"][2]["status"] == "pending"
        assert len(history["calculations"]) == 4
        # Re-importing the exact old source does not resurrect its superseded revisions.
        store.import_bundle(seed, raw_payload=raw)
        assert store.query(seed.series_id, seed.environment) == replay
        assert store.restore(seed.series_id, seed.environment, through) == replay


@pytest.mark.parametrize("invalid", [0.5, True, float("nan"), float("inf")])
def test_json_decimal_validation_happens_before_any_database_creation(invalid: object) -> None:
    payload = _complete().model_dump(mode="json")
    payload["inception"]["initial_state"]["cash"] = invalid
    with pytest.raises(NavError):
        parse_bundle_bytes(json.dumps(payload).encode())


def test_duplicate_json_keys_are_never_silently_discarded() -> None:
    raw = (EXAMPLES / "01-seed.json").read_bytes()
    payload = raw.replace(b'"cash": "10000"', b'"cash": "10000", "cash": "20000"')
    with pytest.raises(NavError):
        parse_bundle_bytes(payload)

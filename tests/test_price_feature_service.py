from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from feature_helpers import CODES, END, NOW, bars, history

from phalanx.domain.price_history import SymbolHistory, SymbolStatus, price_data_hash
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.repository import SqliteHistoryRepository


def stored(tmp_path: Path):
    view = history((bars(CODES[0], ["100"] * 253), bars(CODES[1], ["110"] * 21)))
    repository = SqliteHistoryRepository(tmp_path / "private" / "history.sqlite3")
    repository.create(view)
    return PriceFeatureService(repository, clock=lambda: NOW), view


@pytest.mark.parametrize(
    "options,ordinals",
    [
        ({"codes": (CODES[1],)}, [1]),
        ({"codes": CODES[::-1]}, [1, 0]),
        ({"all_targets": True}, [0, 1]),
    ],
)
def test_selection_preserves_order_and_parses_each_selected_price_result_once(
    tmp_path: Path, options: dict, ordinals: list[int]
) -> None:
    service, view = stored(tmp_path)
    original = service.repository.path.read_bytes()
    with (
        patch.object(
            SymbolHistory, "model_validate_json", wraps=SymbolHistory.model_validate_json
        ) as parse,
        patch("phalanx.domain.price_history.price_data_hash", wraps=price_data_hash) as hash_result,
    ):
        result = service.calculate(view.job.job_id, as_of=END, **options)
    assert [s.ordinal for s in result.symbols] == ordinals
    assert [json.loads(call.args[0])["ordinal"] for call in parse.call_args_list] == ordinals
    assert [call.args[0] for call in hash_result.call_args_list] == [
        view.symbols[ordinal].result.bars for ordinal in ordinals
    ]
    assert result.history_job_id == view.job.job_id
    assert result.discovery_run_id == view.job.discovery_run_id
    assert [s.target for s in result.symbols] == [view.job.targets[i] for i in ordinals]
    assert service.repository.path.read_bytes() == original
    assert (
        service.calculate(view.job.job_id, as_of=END, **options).to_json_bytes()
        == result.to_json_bytes()
    )


def test_selected_symbols_are_read_in_one_snapshot_during_concurrent_write(tmp_path: Path) -> None:
    service, view = stored(tmp_path)
    revised = history((bars(CODES[0], ["200"] * 253), bars(CODES[1], ["220"] * 21)))
    parse = SymbolHistory.model_validate_json
    calls = 0
    writer = sqlite3.connect(service.repository.path, timeout=0, isolation_level=None)

    def parse_with_writer(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            writer.execute("BEGIN IMMEDIATE")
            writer.executemany(
                "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=?",
                [(s.model_dump_json(), view.job.job_id, s.ordinal) for s in revised.symbols],
            )
            # A real rollback-journal writer cannot publish between selected reads.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.commit()
        return parse(payload)

    try:
        with patch.object(SymbolHistory, "model_validate_json", side_effect=parse_with_writer):
            result = service.calculate(view.job.job_id, as_of=END, all_targets=True)
        assert calls == 2
        assert [s.last_close for s in result.symbols] == [100, 110]
        writer.commit()
        updated = service.calculate(view.job.job_id, as_of=END, all_targets=True)
        assert [s.last_close for s in updated.symbols] == [200, 220]
    finally:
        writer.close()


@pytest.mark.parametrize(
    "options,error_code",
    [
        ({}, "TARGET_SELECTION_REQUIRED"),
        ({"codes": CODES, "all_targets": True}, "TARGET_SELECTION_REQUIRED"),
        ({"codes": (CODES[0],) * 2}, "DUPLICATE_CODE"),
        ({"codes": ("999999",)}, "SYMBOL_NOT_FOUND"),
        ({"codes": ("0001a0",)}, "SYMBOL_NOT_FOUND"),
    ],
)
def test_selection_errors_parse_no_price_results(
    tmp_path: Path, options: dict, error_code: str
) -> None:
    service, view = stored(tmp_path)
    with (
        patch.object(
            SymbolHistory, "model_validate_json", side_effect=AssertionError("price parsed")
        ),
        pytest.raises(HistoryError) as error,
    ):
        service.calculate(view.job.job_id, as_of=END, **options)
    assert error.value.code == error_code


def test_selected_corruption_raises_storage_error_including_after_as_of(tmp_path: Path) -> None:
    service, view = stored(tmp_path)
    with sqlite3.connect(service.repository.path) as connection:
        connection.execute(
            "UPDATE symbols SET state_json=replace(state_json, ?, ?) WHERE ordinal=0",
            (view.symbols[0].result.sha256, "0" * 64),
        )
    with pytest.raises(HistoryStorageError):
        service.calculate(view.job.job_id, as_of=view.job.start, codes=(CODES[0],))
    result = service.calculate(view.job.job_id, as_of=END, codes=(CODES[1],))
    assert result.symbols[0].target.short_code == CODES[1]


def test_all_targets_retains_unavailable_states_and_unsupported_identifier(tmp_path: Path) -> None:
    codes = ("005930", "0001A0", "000002", "000003", "000004", "invalid")
    view = history(
        (
            bars(codes[0], ["100"] * 253),
            (),
            SymbolStatus.PENDING,
            SymbolStatus.IN_PROGRESS,
            SymbolStatus.FAILED,
            SymbolStatus.UNSUPPORTED,
        ),
        codes=codes,
    )
    repository = SqliteHistoryRepository(tmp_path / "private" / "history.sqlite3")
    repository.create(view)
    before = repository.path.read_bytes()
    result = PriceFeatureService(repository).calculate(view.job.job_id, as_of=END, all_targets=True)
    assert [s.target.short_code for s in result.symbols] == list(codes)
    assert [s.source_status for s in result.symbols] == [s.status for s in view.symbols]
    assert result.symbols[0].complete
    assert all(not s.complete and all(m.reason_code for m in s.metrics) for s in result.symbols[1:])
    assert repository.path.read_bytes() == before


def test_missing_store_read_does_not_create_it(tmp_path: Path) -> None:
    repository = SqliteHistoryRepository(tmp_path / "absent" / "history.sqlite3")
    with pytest.raises(HistoryStorageError):
        PriceFeatureService(repository).calculate("a" * 32, as_of=END, all_targets=True)
    assert not repository.path.parent.exists()

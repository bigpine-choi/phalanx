from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from history_helpers import CODES, END, NOW, START, Reader, bar, job

from phalanx.domain.price_history import (
    HistoryAttempt,
    HistoryResult,
    SymbolHistory,
    SymbolStatus,
    price_data_hash,
)
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError


@pytest.mark.parametrize("method", ["show", "read_bars"])
@pytest.mark.parametrize("ordinal", [0, 1])
def test_single_symbol_read_parses_and_hashes_only_selected_prices(
    tmp_path: Path, method: str, ordinal: int
) -> None:
    service, view, discovery = job(tmp_path)
    outcomes = {
        code: tuple(
            bar(code).model_copy(update={"trade_date": START + timedelta(days=day)})
            for day in range((END - START).days + 1)
        )
        for code in CODES
    }
    service.run(view.job.job_id, Reader(outcomes).factory)
    # The same codes at different ordinals in another job must stay independent.
    other = service.create(discovery, view.job.discovery_run_id, START, END, codes=CODES[::-1])
    saved = service.run(other.job.job_id, Reader().factory)
    code = saved.job.targets[ordinal].short_code
    with (
        patch.object(
            SymbolHistory, "model_validate_json", wraps=SymbolHistory.model_validate_json
        ) as parse_state,
        patch("phalanx.domain.price_history.price_data_hash", wraps=price_data_hash) as hash_prices,
    ):
        actual = getattr(service.repository, method)(saved.job.job_id, code)
    expected = saved.symbols[ordinal]
    assert actual == ((saved.job, expected) if method == "show" else expected.result.bars)
    assert [json.loads(call.args[0])["ordinal"] for call in parse_state.call_args_list] == [ordinal]
    assert [call.args[0] for call in hash_prices.call_args_list] == [expected.result.bars]


@pytest.mark.parametrize("method", ["show", "read_bars"])
@pytest.mark.parametrize("damage", ["invalid_json", "hash"])
def test_single_symbol_read_does_not_parse_another_symbols_corrupt_result(
    tmp_path: Path, method: str, damage: str
) -> None:
    service, view, _ = job(tmp_path)
    saved = service.run(view.job.job_id, Reader().factory)
    unrelated = saved.symbols[0].model_dump(mode="json")
    unrelated["result"]["sha256"] = "0" * 64
    payload = "not-json" if damage == "invalid_json" else json.dumps(unrelated)
    with sqlite3.connect(service.repository.path) as connection:
        connection.execute(
            "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=0",
            (payload, view.job.job_id),
        )
    actual = getattr(service.repository, method)(view.job.job_id, CODES[1])
    assert actual == (
        (saved.job, saved.symbols[1]) if method == "show" else saved.symbols[1].result.bars
    )
    with pytest.raises(HistoryStorageError):
        service.repository.load(view.job.job_id)


@pytest.mark.parametrize("method", ["show", "read_bars"])
@pytest.mark.parametrize(
    "damage",
    ["job_id", "ordinal_key", "ordinal_json", "missing", "code", "start", "end", "hash", "json"],
)
def test_single_symbol_read_preserves_frozen_request_and_result_validation(
    tmp_path: Path, method: str, damage: str
) -> None:
    service, view, _ = job(tmp_path)
    saved = service.run(view.job.job_id, Reader().factory)
    state = saved.symbols[1].model_dump(mode="json")
    if damage == "ordinal_json":
        state["ordinal"] = 0
    elif damage == "hash":
        state["result"]["sha256"] = "0" * 64
    elif damage in ("code", "start", "end"):
        changed = bar(CODES[0] if damage == "code" else CODES[1])
        if damage != "code":
            changed = changed.model_copy(
                update={
                    "trade_date": (
                        START - timedelta(days=1) if damage == "start" else END + timedelta(days=1)
                    )
                }
            )
        # Keep a valid result hash so the frozen code/range check must reject this.
        state["result"] = HistoryResult(
            bars=(changed,),
            row_count=1,
            first_trade_date=changed.trade_date,
            last_trade_date=changed.trade_date,
            sha256=price_data_hash((changed,)),
        ).model_dump(mode="json")
    with sqlite3.connect(service.repository.path) as connection:
        if damage == "job_id":
            changed_job = saved.job.model_dump(mode="json")
            changed_job["job_id"] = "f" * 32
            connection.execute(
                "UPDATE jobs SET job_json=? WHERE job_id=?",
                (json.dumps(changed_job), view.job.job_id),
            )
        elif damage == "ordinal_key":
            connection.execute(
                "UPDATE symbols SET ordinal=7 WHERE job_id=? AND ordinal=1", (view.job.job_id,)
            )
        elif damage == "missing":
            connection.execute(
                "DELETE FROM symbols WHERE job_id=? AND ordinal=1", (view.job.job_id,)
            )
        else:
            connection.execute(
                "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=1",
                ("not-json" if damage == "json" else json.dumps(state), view.job.job_id),
            )
    with pytest.raises(HistoryStorageError):
        getattr(service.repository, method)(view.job.job_id, CODES[1])


@pytest.mark.parametrize("method", ["show", "read_bars"])
def test_single_symbol_lookup_errors(tmp_path: Path, method: str) -> None:
    service, view, _ = job(tmp_path)
    read = getattr(service.repository, method)
    with pytest.raises(HistoryError) as missing_job:
        read("f" * 32, CODES[1])
    assert missing_job.value.code == "JOB_NOT_FOUND"
    for code in ("999999", "0001a0", "0001A0 "):
        with pytest.raises(HistoryError) as missing_symbol:
            read(view.job.job_id, code)
        assert missing_symbol.value.code == "SYMBOL_NOT_FOUND"


@pytest.mark.parametrize(
    "status",
    [SymbolStatus.PENDING, SymbolStatus.IN_PROGRESS, SymbolStatus.FAILED, SymbolStatus.UNSUPPORTED],
)
def test_single_symbol_read_distinguishes_unfinished_from_completed_empty(
    tmp_path: Path, status: SymbolStatus
) -> None:
    service, view, _ = job(tmp_path)
    saved = service.run(
        view.job.job_id, Reader({CODES[0]: (), CODES[1]: ()}).factory, max_symbols=1
    )
    assert service.repository.show(view.job.job_id, CODES[0]) == (saved.job, saved.symbols[0])
    assert service.repository.read_bars(view.job.job_id, CODES[0]) == ()
    state = SymbolHistory(
        ordinal=1,
        status=status,
        attempts=(HistoryAttempt(number=1, started_at=NOW, outcome="in_progress"),)
        if status == SymbolStatus.IN_PROGRESS
        else (),
    )
    service.repository.save_symbol(view.job.job_id, view.symbols[1], state)
    assert service.repository.show(view.job.job_id, CODES[1]) == (saved.job, state)
    with pytest.raises(HistoryError) as error:
        service.repository.read_bars(view.job.job_id, CODES[1])
    assert error.value.code == "RESULT_NOT_READY"
    assert status.value in str(error.value)

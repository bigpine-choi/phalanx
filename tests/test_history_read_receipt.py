"""Portable checks for read confirmation of committed history results.

The fake reader represents a new, independent read after a writer has returned.
SQLite commit ordering itself is covered by the Linux repository integration tests.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from feature_helpers import CODES, bars, history

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import (
    HistoryAttempt,
    HistoryJob,
    HistoryView,
    SymbolHistory,
)
from phalanx.market_data.history.read_receipt import (
    HistoryReadReceiptError,
    HistoryReadReceiptService,
    parse_read_receipt,
    validate_read_receipt,
)
from phalanx.portfolio.private_json_storage import PrivateJsonAlreadyExistsError
from phalanx.selection.history_replay import HistoryReplayService

FETCH_STARTED = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
FETCH_FINISHED = datetime(2026, 9, 13, 1, 1, tzinfo=UTC)
READ_STARTED_AT = datetime(2026, 9, 13, 1, 2, tzinfo=UTC)
READ_COMPLETED_AT = datetime(2026, 9, 13, 1, 3, tzinfo=UTC)
DECISION_AT = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
AS_OF = date(2026, 8, 20)
POLICY = SelectionPolicy(metric=SelectionMetric.RETURN_20, top=1, max_age_days=0)


class Reader:
    def __init__(self, view: HistoryView) -> None:
        self.view = view
        self.calls: list[tuple[str, tuple[str, ...], bool]] = []
        self.read_complete = False

    def read_selected(
        self,
        job_id: str,
        *,
        codes: tuple[str, ...] = (),
        all_targets: bool = False,
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        self.calls.append((job_id, codes, all_targets))
        assert job_id == self.view.job.job_id
        assert codes and not all_targets
        by_code = {
            target.short_code: state
            for target, state in zip(self.view.job.targets, self.view.symbols, strict=True)
        }
        selected = tuple(by_code[code] for code in codes)
        self.read_complete = True
        return self.view.job, selected


def collected_view(*, first_close: str = "110") -> HistoryView:
    view = history(
        (
            bars(CODES[0], ["100", first_close], start=date(2026, 8, 19)),
            bars(CODES[1], ["100", "90"], start=date(2026, 8, 19)),
        )
    )
    states = tuple(
        state.model_copy(
            update={
                "attempts": (
                    HistoryAttempt(
                        number=1,
                        started_at=FETCH_STARTED,
                        finished_at=FETCH_FINISHED,
                        outcome="completed",
                    ),
                )
            }
        )
        for state in view.symbols
    )
    return HistoryView(job=view.job, symbols=states)


def captured(
    view: HistoryView | None = None,
    *,
    codes: tuple[str, ...] = CODES,
    read_completed_at: datetime = READ_COMPLETED_AT,
):
    selected_view = collected_view() if view is None else view
    reader = Reader(selected_view)
    clock_calls: list[bool] = []

    def clock() -> datetime:
        clock_calls.append(reader.read_complete)
        return READ_STARTED_AT if len(clock_calls) == 1 else read_completed_at

    receipt = HistoryReadReceiptService(clock=clock).capture(
        reader, selected_view.job.job_id, codes=codes
    )
    assert reader.calls == [(selected_view.job.job_id, codes, False)]
    assert clock_calls == [False, True]
    return receipt


def test_capture_is_after_read_and_binds_exact_selected_results() -> None:
    view = collected_view()
    first = captured(view)
    second = captured(view)

    assert first.to_json_bytes() == second.to_json_bytes()
    assert parse_read_receipt(first.to_json_bytes()) == first
    validate_read_receipt(first, view.job, view.symbols, DECISION_AT)
    payload = json.loads(first.to_json_bytes())
    assert payload["history_job_id"] == view.job.job_id
    assert payload["read_started_at"] == "2026-09-13T01:02:00Z"
    assert payload["read_completed_at"] == "2026-09-13T01:03:00Z"
    assert payload["evidence_basis"] == "local_committed_snapshot_read"
    assert payload["trusted_timestamp_verified"] is False
    assert [item["stock_code"] for item in payload["symbols"]] == list(CODES)


def test_duplicate_json_member_is_rejected() -> None:
    receipt = captured()
    payload = receipt.to_json_bytes()
    duplicated = b'{"history_job_id":"' + (b"b" * 32) + b'",' + payload[1:]

    with pytest.raises(HistoryReadReceiptError) as caught:
        parse_read_receipt(duplicated)
    assert caught.value.code == "INVALID_RECEIPT"


def test_one_selected_symbol_is_bound_without_unrelated_result() -> None:
    view = collected_view()
    receipt = captured(view, codes=(CODES[1],))

    validate_read_receipt(receipt, view.job, (view.symbols[1],), DECISION_AT)
    assert [symbol.stock_code for symbol in receipt.symbols] == [CODES[1]]


def test_read_confirmation_after_decision_is_rejected_even_if_fetch_was_early() -> None:
    view = collected_view()
    receipt = captured(view, read_completed_at=datetime(2026, 9, 14, 0, 1, tzinfo=UTC))

    with pytest.raises(HistoryReadReceiptError) as caught:
        validate_read_receipt(receipt, view.job, view.symbols, DECISION_AT)
    assert caught.value.code == "READ_AFTER_DECISION"


def test_receipt_rejects_another_job_or_symbol_order() -> None:
    view = collected_view()
    receipt = captured(view)
    other_job = view.job.model_copy(update={"job_id": "b" * 32})

    with pytest.raises(HistoryReadReceiptError) as caught:
        validate_read_receipt(receipt, other_job, view.symbols, DECISION_AT)
    assert caught.value.code == "RECEIPT_MISMATCH"
    with pytest.raises(HistoryReadReceiptError) as caught:
        validate_read_receipt(receipt, view.job, view.symbols[::-1], DECISION_AT)
    assert caught.value.code == "RECEIPT_MISMATCH"


def test_receipt_rejects_revised_price_for_same_job_and_trade_dates() -> None:
    view = collected_view()
    revised = collected_view(first_close="80")
    receipt = captured(view)
    assert [bar.trade_date for bar in view.symbols[0].result.bars] == [
        bar.trade_date for bar in revised.symbols[0].result.bars
    ]

    with pytest.raises(HistoryReadReceiptError) as caught:
        validate_read_receipt(receipt, view.job, revised.symbols, DECISION_AT)
    assert caught.value.code == "RECEIPT_MISMATCH"


def test_completed_result_without_terminal_success_attempt_cannot_be_confirmed() -> None:
    view = collected_view()
    missing = HistoryView(
        job=view.job,
        symbols=(view.symbols[0].model_copy(update={"attempts": ()}), view.symbols[1]),
    )

    with pytest.raises(HistoryReadReceiptError) as caught:
        captured(missing)
    assert caught.value.code == "MISSING_FETCH_RECEIPT"


def test_replay_with_matching_receipt_records_exact_bytes_and_narrow_evidence() -> None:
    view = collected_view()
    receipt_bytes = captured(view).to_json_bytes()

    result = HistoryReplayService(clock=lambda: DECISION_AT).run(
        Reader(view),
        view.job.job_id,
        AS_OF,
        DECISION_AT,
        POLICY,
        codes=CODES,
        read_receipt_bytes=receipt_bytes,
    )

    assert result.read_receipt == parse_read_receipt(receipt_bytes)
    assert result.read_receipt_sha256 == hashlib.sha256(receipt_bytes).hexdigest()
    assert result.local_snapshot_read_before_decision_confirmed is True
    assert result.receipt_check == "local_committed_snapshot_read_before_decision"
    assert result.database_commit_before_decision_verified is False
    assert result.vendor_release_time_verified is False
    assert result.point_in_time_backtest_guaranteed is False


def test_replay_rejects_read_confirmation_after_decision() -> None:
    view = collected_view()
    late_receipt = captured(
        view, read_completed_at=datetime(2026, 9, 14, 0, 1, tzinfo=UTC)
    )

    with pytest.raises(HistoryReadReceiptError) as caught:
        HistoryReplayService(clock=lambda: DECISION_AT).run(
            Reader(view),
            view.job.job_id,
            AS_OF,
            DECISION_AT,
            POLICY,
            codes=CODES,
            read_receipt_bytes=late_receipt.to_json_bytes(),
        )
    assert caught.value.code == "READ_AFTER_DECISION"


@pytest.mark.parametrize("mutation", ["price", "code_order"])
def test_replay_rejects_snapshot_or_selection_mismatch(mutation: str) -> None:
    original = collected_view()
    receipt_bytes = captured(original).to_json_bytes()
    current = collected_view(first_close="80") if mutation == "price" else original
    codes = CODES[::-1] if mutation == "code_order" else CODES

    with pytest.raises(HistoryReadReceiptError) as caught:
        HistoryReplayService(clock=lambda: DECISION_AT).run(
            Reader(current),
            current.job.job_id,
            AS_OF,
            DECISION_AT,
            POLICY,
            codes=codes,
            read_receipt_bytes=receipt_bytes,
        )
    assert caught.value.code == "RECEIPT_MISMATCH"


@pytest.mark.skipif(sys.platform == "win32", reason="native Windows write guard needs its own test")
def test_export_is_write_once_and_preserves_exact_receipt_bytes(tmp_path: Path) -> None:
    receipt = captured()
    destination = tmp_path / "private" / "read-receipt.json"
    service = HistoryReadReceiptService(clock=lambda: READ_COMPLETED_AT)

    service.export(receipt, destination)
    assert destination.read_bytes() == receipt.to_json_bytes()
    with pytest.raises(PrivateJsonAlreadyExistsError):
        service.export(receipt, destination)
    assert destination.read_bytes() == receipt.to_json_bytes()

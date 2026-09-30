"""Decision-time replay from actual, immutable history collection receipts.

These tests use the shared reader contract and synthetic bars, so they can run
without the Unix writer, a live KIS account, or a Windows database export.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from feature_helpers import CODES, bars, history

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import (
    HistoryAttempt,
    HistoryJob,
    HistoryView,
    SymbolHistory,
    SymbolStatus,
)
from phalanx.selection.history_replay import (
    HistoryReplayError,
    HistoryReplayResult,
    HistoryReplayService,
)

AS_OF = date(2026, 8, 20)
START = date(2026, 6, 21)
FETCH_STARTED = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
FETCH_FINISHED = datetime(2026, 9, 13, 1, 1, tzinfo=UTC)
DECISION_AT = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
LATER_FETCH_STARTED = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
LATER_FETCH_FINISHED = datetime(2026, 9, 15, 1, 1, tzinfo=UTC)
LATER_DECISION_AT = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)
REPLAYED_AT = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
POLICY = SelectionPolicy(metric=SelectionMetric.RETURN_60, top=1, max_age_days=0)


class FakeHistoryReader:
    """Return requested states through the platform-neutral read_selected API."""

    def __init__(self, view: HistoryView) -> None:
        self.view = view
        self.calls: list[tuple[str, tuple[str, ...], bool]] = []

    def read_selected(
        self,
        job_id: str,
        *,
        codes: tuple[str, ...] = (),
        all_targets: bool = False,
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        self.calls.append((job_id, codes, all_targets))
        if all_targets:
            return self.view.job, self.view.symbols
        by_code = {
            target.short_code: state
            for target, state in zip(self.view.job.targets, self.view.symbols, strict=True)
        }
        return self.view.job, tuple(by_code[code] for code in codes)


def collected_view(
    *,
    first_final: str = "110",
    second_final: str = "90",
    job_id: str = "a" * 32,
    fetch_started: datetime = FETCH_STARTED,
    fetch_finished: datetime = FETCH_FINISHED,
) -> HistoryView:
    view = history(
        (
            bars(CODES[0], ["100"] * 60 + [first_final], start=START),
            bars(CODES[1], ["100"] * 60 + [second_final], start=START),
        )
    )
    states = tuple(
        state.model_copy(
            update={
                "attempts": (
                    HistoryAttempt(
                        number=1,
                        started_at=fetch_started,
                        finished_at=fetch_finished,
                        outcome="completed",
                    ),
                )
            }
        )
        for state in view.symbols
    )
    return HistoryView(job=view.job.model_copy(update={"job_id": job_id}), symbols=states)


def replay(
    view: HistoryView,
    *,
    decision_at: datetime = DECISION_AT,
) -> HistoryReplayResult:
    return HistoryReplayService(clock=lambda: decision_at).run(
        FakeHistoryReader(view),
        view.job.job_id,
        AS_OF,
        decision_at,
        POLICY,
        all_targets=True,
    )


def test_two_symbol_replay_has_deterministic_row_evidence_and_selection() -> None:
    view = collected_view()
    reader = FakeHistoryReader(view)
    service = HistoryReplayService(clock=lambda: DECISION_AT)

    first = service.run(
        reader, view.job.job_id, AS_OF, DECISION_AT, POLICY, all_targets=True
    )
    second = service.run(
        reader, view.job.job_id, AS_OF, DECISION_AT, POLICY, all_targets=True
    )

    assert reader.calls == [(view.job.job_id, (), True)] * 2
    assert first.features.history_job_id == view.job.job_id
    assert first.features.as_of == AS_OF
    assert first.selection.selected_codes == (CODES[0],)
    assert first.selection.source.input_sha256 == hashlib.sha256(
        first.features.to_json_bytes()
    ).hexdigest()
    assert len(first.rows) == 122
    assert [(row.stock_code, row.trade_date) for row in first.rows] == [
        (code, bar.trade_date)
        for code, state in zip(CODES, view.symbols, strict=True)
        for bar in state.result.bars
    ]
    assert all(row.fetch_completed_at == FETCH_FINISHED for row in first.rows)
    assert all(row.attempt_number == 1 for row in first.rows)
    assert all(re.fullmatch(r"[0-9a-f]{64}", row.row_sha256) for row in first.rows)
    assert [row.history_result_sha256 for row in first.rows] == [
        state.result.sha256
        for state in view.symbols
        for _ in state.result.bars
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", first.row_evidence_sha256)
    assert first.to_json_bytes() == second.to_json_bytes()
    exported = json.loads(first.to_json_bytes())
    assert exported["row_evidence_sha256"] == first.row_evidence_sha256
    assert len(exported["rows"]) == 122


def test_rejects_naive_decision_time() -> None:
    view = collected_view()
    with pytest.raises(HistoryReplayError) as caught:
        replay(view, decision_at=datetime(2026, 9, 14))
    assert caught.value.code == "INVALID_DECISION_TIME"


def test_rejects_job_created_after_decision() -> None:
    view = collected_view()
    view = HistoryView(
        job=view.job.model_copy(update={"created_at": LATER_FETCH_STARTED}),
        symbols=view.symbols,
    )
    with pytest.raises(HistoryReplayError) as caught:
        replay(view)
    assert caught.value.code == "JOB_AFTER_DECISION"


def test_rejects_collection_completed_after_decision() -> None:
    view = collected_view(
        fetch_started=FETCH_STARTED,
        fetch_finished=LATER_FETCH_FINISHED,
    )
    with pytest.raises(HistoryReplayError) as caught:
        replay(view)
    assert caught.value.code == "FETCH_AFTER_DECISION"


def test_replay_time_is_reported_separately_from_historical_decision() -> None:
    view = collected_view()
    result = HistoryReplayService(clock=lambda: REPLAYED_AT).run(
        FakeHistoryReader(view),
        view.job.job_id,
        AS_OF,
        DECISION_AT,
        POLICY,
        all_targets=True,
    )

    assert result.decision_at == DECISION_AT
    assert result.replayed_at == REPLAYED_AT
    assert result.features.calculated_at == REPLAYED_AT
    assert result.selection.evaluated_at == REPLAYED_AT
    assert result.selection.source.calculated_at == REPLAYED_AT
    exported = json.loads(result.to_json_bytes())
    assert exported["decision_at"] != exported["replayed_at"]
    assert exported["features"]["calculated_at"] == exported["replayed_at"]
    assert exported["selection"]["evaluated_at"] == exported["replayed_at"]


def test_rejects_more_than_25_targets_before_calculating_history() -> None:
    codes = tuple(f"{index:06d}" for index in range(26))
    view = history((SymbolStatus.PENDING,) * 26, codes=codes)
    with pytest.raises(HistoryReplayError) as caught:
        replay(view)
    assert caught.value.code == "TOO_MANY_TARGETS"


def test_rejects_receipt_started_before_job_creation() -> None:
    view = collected_view(
        fetch_started=datetime(2026, 9, 12, 23, 59, tzinfo=UTC),
        fetch_finished=FETCH_FINISHED,
    )
    with pytest.raises(HistoryReplayError) as caught:
        replay(view)
    assert caught.value.code == "MISSING_FETCH_RECEIPT"


@pytest.mark.parametrize(
    "decision_at",
    [
        datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
        datetime.max.replace(tzinfo=timezone(-timedelta(hours=12))),
    ],
)
def test_extreme_aware_offset_that_overflows_market_date_is_rejected(
    decision_at: datetime,
) -> None:
    view = collected_view()
    with pytest.raises(HistoryReplayError) as caught:
        replay(view, decision_at=decision_at)
    assert caught.value.code == "INVALID_DECISION_TIME"


@pytest.mark.parametrize("receipt", ["missing", "wrong_outcome"])
def test_completed_bars_need_a_terminal_success_receipt(receipt: str) -> None:
    view = collected_view()
    state = view.symbols[0]
    if receipt == "missing":
        attempts: tuple[HistoryAttempt, ...] = ()
    else:
        attempts = (
            HistoryAttempt(
                number=1,
                started_at=FETCH_STARTED,
                finished_at=FETCH_FINISHED,
                outcome="failed",
            ),
        )
    view = HistoryView(
        job=view.job,
        symbols=(state.model_copy(update={"attempts": attempts}), view.symbols[1]),
    )
    with pytest.raises(HistoryReplayError) as caught:
        replay(view)
    assert caught.value.code == "MISSING_FETCH_RECEIPT"


def test_reader_job_identity_must_match_requested_job() -> None:
    view = collected_view(job_id="b" * 32)
    with pytest.raises(HistoryReplayError) as caught:
        HistoryReplayService(clock=lambda: DECISION_AT).run(
            FakeHistoryReader(view),
            "a" * 32,
            AS_OF,
            DECISION_AT,
            POLICY,
            all_targets=True,
        )
    assert caught.value.code == "INCONSISTENT_HISTORY"


def test_later_recollection_of_same_dates_changes_evidence_and_future_decision_only() -> None:
    original = collected_view()
    revised = collected_view(
        first_final="80",
        job_id="b" * 32,
        fetch_started=LATER_FETCH_STARTED,
        fetch_finished=LATER_FETCH_FINISHED,
    )
    revised = HistoryView(
        job=revised.job.model_copy(update={"created_at": LATER_FETCH_STARTED}),
        symbols=revised.symbols,
    )

    original_result = replay(original)
    with pytest.raises(HistoryReplayError) as caught:
        replay(revised, decision_at=DECISION_AT)
    assert caught.value.code == "JOB_AFTER_DECISION"
    revised_result = replay(revised, decision_at=LATER_DECISION_AT)

    assert original_result.selection.selected_codes == (CODES[0],)
    assert revised_result.selection.selected_codes == (CODES[1],)
    assert [(row.stock_code, row.trade_date) for row in original_result.rows] == [
        (row.stock_code, row.trade_date) for row in revised_result.rows
    ]
    assert original_result.row_evidence_sha256 != revised_result.row_evidence_sha256
    assert original_result.rows[60].row_sha256 != revised_result.rows[60].row_sha256
    assert original_result.rows[60].history_result_sha256 != (
        revised_result.rows[60].history_result_sha256
    )

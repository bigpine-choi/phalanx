from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import ROUND_UP, Decimal, Inexact, localcontext

import pytest
from feature_helpers import NOW
from selection_helpers import AS_OF, CODES, features, scores

from phalanx.domain.candidate_selection import CandidateSelection, SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import SymbolStatus
from phalanx.selection.engine import select_candidates
from phalanx.selection.errors import SelectionInputError
from phalanx.selection.validation import parse_features


def select(source, *, metric=SelectionMetric.RETURN_60, top=1, age=7, when=NOW):
    payload = source.to_json_bytes()
    return select_candidates(
        parse_features(payload),
        SelectionPolicy(metric=metric, top=top, max_age_days=age),
        input_sha256=hashlib.sha256(payload).hexdigest(),
        evaluated_at=when,
    )


@pytest.mark.parametrize("metric", list(SelectionMetric))
def test_metric_direction_preserves_exact_scores_and_zero(metric: SelectionMetric) -> None:
    if metric.value.startswith("return"):
        values, order = ("0.1000", "0.20", "0"), (CODES[1], CODES[0], CODES[2])
    elif metric.value.startswith("volatility"):
        values, order = ("0.20", "0.1000", "0"), (CODES[2], CODES[1], CODES[0])
    else:
        values, order = ("-0.20", "-0.1000", "0"), (CODES[2], CODES[1], CODES[0])
    result = select(scores(features(), values, metric), metric=metric, top=3)
    assert result.selected_codes == order
    assert result.complete and result.evaluation_complete and result.selection_filled
    assert [c.score for c in result.candidates] == [Decimal(v) for v in values]
    assert [c.target.short_code for c in result.candidates] == list(CODES)
    assert all(c.status == "selected" for c in result.candidates)
    assert all(c.reasons[0].code == "SELECTED_TOP_N" for c in result.candidates)
    assert CandidateSelection.model_validate_json(result.to_json_bytes()) == result


def test_competition_ranks_ascii_tie_break_and_strict_top_boundary() -> None:
    source = scores(features(), ("0.10", "0.100", "0"))
    result = select(source, top=1)
    assert result.selected_codes == ("000001",)
    assert [c.metric_rank for c in result.candidates] == [1, 1, 3]
    assert [c.selection_order for c in result.candidates] == [2, 1, 3]
    assert result.candidates[0].status == "not_selected"
    assert result.candidates[0].reasons[0].code == "OUTSIDE_TOP_N"
    assert result.eligible_count == 3 and result.not_selected_count == 2
    assert result.complete
    reversed_source = source.model_copy(update={"symbols": source.symbols[::-1]})
    reversed_result = select(reversed_source, top=1)
    assert reversed_result.selected_codes == result.selected_codes
    assert [(c.ordinal, c.metric_rank, c.selection_order) for c in reversed_result.candidates] == [
        (c.ordinal, c.metric_rank, c.selection_order) for c in result.candidates[::-1]
    ]


def test_only_selected_metric_needs_to_be_available() -> None:
    source = features(counts=(61, 61, 61))
    assert not source.complete
    result = select(source, top=3)
    assert result.complete
    assert result.source.features_complete is False
    assert result.selected_count == 3 and result.unavailable_count == 0
    assert result.selected_codes == tuple(sorted(CODES))


@pytest.mark.parametrize(
    "counts,top,evaluation_complete,filled",
    [
        ((61, 61, 61), 3, True, True),
        ((61, 61, 61), 4, True, False),
        ((61, 21, 61), 2, False, True),
        ((61, 21, 61), 3, False, False),
    ],
)
def test_partial_flags_and_counts_are_independent(counts, top, evaluation_complete, filled) -> None:
    result = select(features(counts=counts), top=top)
    assert result.evaluation_complete is evaluation_complete
    assert result.selection_filled is filled
    assert result.complete is (evaluation_complete and filled)
    assert result.selected_count + result.shortfall == top
    assert result.selected_count + result.not_selected_count == result.eligible_count
    assert result.eligible_count + result.unavailable_count == 3


def test_all_unavailable_source_states_are_preserved_without_reference() -> None:
    states = (
        SymbolStatus.PENDING,
        SymbolStatus.IN_PROGRESS,
        SymbolStatus.FAILED,
        SymbolStatus.UNSUPPORTED,
        SymbolStatus.EMPTY,
    )
    source = features(codes=("000001", "000002", "000003", "invalid", "0001A0"), statuses=states)
    missing = source.symbols[3].model_copy(
        update={
            "target": source.symbols[3].target.model_copy(update={"short_code": None}),
        }
    )
    source = source.model_copy(
        update={"symbols": (*source.symbols[:3], missing, source.symbols[4])}
    )
    result = select(source, top=2)
    assert result.selected_codes == () and result.reference_price_date is None
    assert result.shortfall == 2 and result.unavailable_count == 5
    assert not result.evaluation_complete and not result.selection_filled
    for candidate, original in zip(result.candidates, source.symbols, strict=True):
        assert candidate.status == "unavailable"
        assert candidate.metric_rank is None and candidate.selection_order is None
        assert candidate.score is None
        codes = {r.code for r in candidate.reasons}
        assert f"SOURCE_{original.source_status.value.upper()}" in codes
        assert "NO_REFERENCE_PRICE_DATE" in codes
        assert (
            candidate.selected_feature.reason_code
            == f"SOURCE_{original.source_status.value.upper()}"
        )
    assert result.candidates[2].source_error_code == "SOURCE_TEST_ERROR"
    assert result.candidates[3].target.short_code is None
    assert "INVALID_IDENTIFIER" in {r.code for r in result.candidates[3].reasons}


def test_completed_without_observation_or_valid_identifier_is_unavailable() -> None:
    source = features(counts=(0, 61, 61))
    invalid = source.symbols[1].model_copy(
        update={
            "target": source.symbols[1].target.model_copy(update={"short_code": "0001a0"}),
        }
    )
    source = source.model_copy(update={"symbols": (source.symbols[0], invalid, source.symbols[2])})
    result = select(source)
    assert result.selected_codes == (CODES[2],)
    assert result.candidates[0].selected_feature.reason_code == "NO_OBSERVATIONS_AS_OF"
    assert "INVALID_IDENTIFIER" in {r.code for r in result.candidates[1].reasons}
    assert result.candidates[1].score == 0  # available score retained even when not eligible


@pytest.mark.parametrize("metric", list(SelectionMetric))
@pytest.mark.parametrize("top", [1, 10])
def test_latest_short_history_sets_reference_without_falling_back(metric, top) -> None:
    source = features(counts=(1, 253, 253), ages=(0, 1, 1))
    result = select(source, metric=metric, top=top, when=NOW + timedelta(days=100))
    assert result.reference_price_date == AS_OF
    assert result.selected_codes == ()
    assert result.candidates[0].selected_feature.reason_code == "INSUFFICIENT_OBSERVATIONS"
    assert all(
        "PRICE_ENDPOINT_MISMATCH" in {r.code for r in c.reasons} for c in result.candidates[1:]
    )


@pytest.mark.parametrize("age,selected", [(7, True), (8, False)])
def test_calendar_age_limit_uses_input_as_of_not_evaluation_time(age, selected) -> None:
    source = features(ages=(age, age, age))
    result = select(source, age=7, when=NOW + timedelta(days=1000))
    assert bool(result.selected_codes) is selected
    assert result.reference_price_date == AS_OF - timedelta(days=age)
    if not selected:
        assert all("PRICE_TOO_OLD" in {r.code for r in c.reasons} for c in result.candidates)


def test_evaluation_and_feature_calculation_times_do_not_affect_ranking() -> None:
    source = scores(features(), ("0.1", "0.2", "0.3"))
    first = select(source)
    second = select(source, when=NOW + timedelta(days=5))
    changed = select(source.model_copy(update={"calculated_at": NOW - timedelta(days=1000)}))
    assert first.candidates == second.candidates == changed.candidates
    assert first.selected_codes == second.selected_codes == changed.selected_codes
    assert first.source.input_sha256 == second.source.input_sha256
    assert first.source.input_sha256 != changed.source.input_sha256
    assert first.evaluated_at != second.evaluated_at


def test_decimal_comparison_is_exact_under_hostile_global_context() -> None:
    source = scores(
        features(),
        (
            "0.1111111111111111111111111111111111111111111111111111111111",
            "0.1111111111111111111111111111111111111111111111111111111112",
            "0",
        ),
    )
    expected = select(source).to_json_bytes()
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        before = str(context)
        assert select(source).to_json_bytes() == expected
        assert str(context) == before


def test_naive_evaluation_clock_is_input_error() -> None:
    with pytest.raises(SelectionInputError) as error:
        select(features(), when=NOW.replace(tzinfo=None))
    assert error.value.code == "INVALID_EVALUATION_TIME"

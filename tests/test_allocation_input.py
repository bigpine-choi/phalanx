from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest
from allocation_input_helpers import AS_OF, CODES, create_inputs, make_view, view_from_series
from feature_helpers import bars

from phalanx.domain.portfolio import AlignedReturnMatrix
from phalanx.domain.universe import KoreanStock, StockMarket
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_input.calculation import prepare_allocation_input
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.returns import build_aligned_return_matrix


def reason_codes(result):
    return {reason.code for reason in result.reasons}


def test_real_pipeline_keeps_selection_order_decimals_and_partial_completion(tmp_path):
    repository, path, selection, view = create_inputs(tmp_path, make_view(failed=True))
    assert not selection.complete and not selection.evaluation_complete
    assert selection.selection_filled
    result = AllocationInputService(repository).prepare(path)
    assert result.input_ready and reason_codes(result) == {"INPUT_READY"}
    assert result.selection_completion.complete is False
    assert result.selected_codes == selection.selected_codes == CODES
    assert isinstance(result.matrix, AlignedReturnMatrix)
    expected = build_aligned_return_matrix(
        tuple(
            StockDailyBars(KoreanStock(code, code, StockMarket.KOSPI), state.result.bars)
            for code, state in zip(CODES, view.symbols[:2], strict=True)
        )
    )
    assert result.matrix == expected
    assert all(type(value) is Decimal for row in result.matrix.values for value in row)
    assert result.return_start_dates[1:] == result.matrix.dates[:-1]
    assert result.return_start_dates[0] == view.job.start
    assert result.return_observation_count == 504
    assert result.minimum_observations == 504 and result.maximum_observations == 756
    raw = json.loads(result.to_json_bytes())
    assert raw["matrix"]["values"][0] == [format(value, "f") for value in expected.values[0]]
    assert raw["selection_source"]["source_price_hashes_verified"] is False
    assert raw["features_consumed_input_hashes_verified"] is False
    assert raw["trading_day_completeness"] == "unverified"
    assert raw["point_in_time_backtest_guaranteed"] is False
    assert result.price_window_sha256 != selection.candidates[0].consumed_input_sha256
    assert [s.verified_source_price_sha256 for s in result.symbols] == [
        s.result.sha256 for s in view.symbols[:2]
    ]


@pytest.mark.parametrize(
    "count,ready,returns", [(504, False, 503), (505, True, 504), (757, True, 756), (810, True, 756)]
)
def test_minimum_return_count_and_maximum_tail_window(tmp_path, count, ready, returns):
    repository, path, _, _ = create_inputs(tmp_path, make_view(counts=(count, count)))
    result = AllocationInputService(repository).prepare(path)
    assert result.input_ready is ready
    assert result.return_observation_count == returns
    assert result.used_start == AS_OF - timedelta(days=returns)
    assert result.used_end == AS_OF
    assert len(result.inspected_price_dates) == returns + 1
    if not ready:
        assert result.matrix is None
        assert reason_codes(result) == {"INSUFFICIENT_RETURN_OBSERVATIONS"}


@pytest.mark.parametrize("future", [0, 7])
def test_future_prices_never_enter_matrix_or_calculation_fingerprint(tmp_path, future):
    repository, path, _, _ = create_inputs(tmp_path / "first", make_view(future=future))
    result = AllocationInputService(repository).prepare(path)
    repo2, path2, _, _ = create_inputs(tmp_path / "second", make_view())
    base = AllocationInputService(repo2).prepare(path2)
    assert result.matrix == base.matrix
    assert result.calculation_fingerprint == base.calculation_fingerprint
    assert result.price_window_sha256 == base.price_window_sha256
    assert all(s.stored_price_count == 505 + future for s in result.symbols)
    assert result.matrix.dates[-1] == AS_OF


def test_missing_middle_date_is_not_hidden_by_intersection(tmp_path):
    missing = AS_OF - timedelta(days=300)
    repo, path, _, _ = create_inputs(
        tmp_path,
        make_view(
            counts=(760, 760),
            missing={CODES[1]: (missing,)},
        ),
    )
    result = AllocationInputService(repo).prepare(path)
    assert not result.input_ready and result.matrix is None
    assert reason_codes(result) == {"OBSERVED_DATE_MISMATCH"}
    assert len(result.inspected_price_dates) == 757
    assert result.symbols[0].missing_dates == ()
    assert result.symbols[1].missing_dates == (missing,)
    assert result.symbols[1].window_price_count == 756
    assert result.return_observation_count == 0


def test_missing_date_outside_inspected_window_does_not_block(tmp_path):
    missing = AS_OF - timedelta(days=780)
    repo, path, _, _ = create_inputs(
        tmp_path,
        make_view(
            counts=(810, 810),
            missing={CODES[1]: (missing,)},
        ),
    )
    result = AllocationInputService(repo).prepare(path)
    assert result.input_ready and result.return_observation_count == 756


def test_weekends_and_days_missing_for_all_symbols_are_not_invented(tmp_path):
    start = AS_OF - timedelta(days=800)
    full = tuple(bars(code, ["100"] * 801, start=start) for code in CODES)
    series = tuple(tuple(b for b in item if b.trade_date.weekday() < 5) for item in full)
    repo, path, _, _ = create_inputs(tmp_path, view_from_series(series))
    result = AllocationInputService(repo).prepare(path)
    assert result.input_ready
    assert any(
        (end - start).days == 3
        for start, end in zip(result.return_start_dates, result.matrix.dates, strict=True)
    )
    assert result.trading_day_completeness == "unverified"


@pytest.mark.parametrize(
    "counts,top,reason", [((61, 61), 3, "SELECTION_SHORTFALL"), ((1, 1), 2, "EMPTY_SELECTION")]
)
def test_empty_or_unfilled_selection_never_produces_matrix(tmp_path, counts, top, reason):
    repo, path, selection, _ = create_inputs(tmp_path, make_view(counts=counts), top=top)
    result = AllocationInputService(repo).prepare(path)
    assert reason in reason_codes(result)
    assert not result.input_ready and result.matrix is None
    assert result.selected_codes == selection.selected_codes
    if not result.selected_codes:
        assert result.symbols == () and result.history_contract is None


def test_alphanumeric_code_blocks_whole_input_without_replacing_it(tmp_path):
    codes = ("0001A0", "000001")
    repo, path, selection, _ = create_inputs(tmp_path, make_view(codes=codes))
    result = AllocationInputService(repo).prepare(path)
    assert not result.input_ready and result.matrix is None
    assert result.selected_codes == selection.selected_codes == codes
    assert [s.code for s in result.symbols] == list(codes)
    assert reason_codes(result) == {"RISK_MODEL_CODE_UNSUPPORTED"}


def test_decimal_context_independence_and_reproducible_json(tmp_path):
    repo, path, _, _ = create_inputs(tmp_path)
    service = AllocationInputService(repo)
    base = service.prepare(path)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        result = service.prepare(path)
        assert result.to_json_bytes() == base.to_json_bytes()
    # File formatting and paths change provenance, not the calculation.
    second = tmp_path / "copy.json"
    second.write_bytes(b" \n" + path.read_bytes())
    other = service.prepare(second)
    assert other.selection_file_sha256 != base.selection_file_sha256
    assert other.calculation_fingerprint == base.calculation_fingerprint
    assert result.selection_file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "case,reason",
    [
        ("endpoint", "PRICE_ENDPOINT_MISMATCH"),
        ("no_prices_as_of", "NO_OBSERVATIONS_AS_OF"),
        ("no_overlap", "NO_OVERLAPPING_RANGE"),
    ],
)
def test_validated_prices_with_unusable_periods_return_diagnostics(tmp_path, case, reason):
    # Exercise the pure adapter on valid models with deliberately inconsistent
    # *feature endpoint evidence*. It must not silently fall back to older dates.
    _, path, selection, _ = create_inputs(tmp_path)
    if case == "endpoint":
        series = (
            bars(CODES[0], ["100"] * 505, start=AS_OF - timedelta(days=504)),
            bars(CODES[1], ["100"] * 505, start=AS_OF - timedelta(days=505)),
        )
    elif case == "no_prices_as_of":
        series = tuple(bars(code, ["100"], start=AS_OF + timedelta(days=1)) for code in CODES)
    else:
        series = (
            bars(CODES[0], ["100"], start=AS_OF - timedelta(days=2)),
            bars(CODES[1], ["100"], start=AS_OF),
        )
    changed = view_from_series(series)
    # Re-validate the selection after replacing only source hashes. Model
    # validation cannot infer the DB endpoints, which the adapter must diagnose.
    raw = json.loads(path.read_bytes())
    for candidate, state in zip(raw["candidates"], changed.symbols, strict=True):
        candidate["source_price_sha256"] = state.result.sha256
    from phalanx.portfolio.allocation_input.validation import parse_selection

    selection = parse_selection(json.dumps(raw).encode())
    result = prepare_allocation_input(
        selection, changed.job, changed.symbols, selection_file_sha256="a" * 64
    )
    assert reason in reason_codes(result)
    assert result.matrix is None and not result.input_ready
    assert result.used_end is None

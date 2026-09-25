"""Pure evidence checks and strict observed-date alignment before Decimal returns."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from itertools import pairwise

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.allocation_input import (
    DATE_POLICY,
    AllocationInput,
    AllocationInputReason,
    HistoryContract,
    SelectionCompletion,
    SymbolInputDiagnostics,
)
from phalanx.domain.candidate_selection import CandidateSelection
from phalanx.domain.market_data import DailyBar
from phalanx.domain.portfolio import AlignedReturnMatrix
from phalanx.domain.price_history import HistoryJob, SymbolHistory, SymbolStatus
from phalanx.domain.risk_model import DynamicRiskModelConfig
from phalanx.portfolio.allocation_input.errors import AllocationInputError

_CONFIG = DynamicRiskModelConfig()


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise AllocationInputError(code, message)


def _linked_prices(
    selection: CandidateSelection, job: HistoryJob, states: tuple[SymbolHistory, ...]
) -> tuple[dict[str, tuple[DailyBar, ...]], tuple[SymbolInputDiagnostics, ...]]:
    _require(
        job.job_id == selection.source.history_job_id
        and job.discovery_run_id == selection.source.discovery_run_id
        and job.start <= selection.source.as_of <= job.end,
        "HISTORY_INPUT_MISMATCH",
        "선정 결과와 history 작업·discovery 식별자·요청 기간이 다릅니다.",
    )
    by_code = {c.target.short_code: c for c in selection.candidates if c.status == "selected"}
    _require(
        len(states) == len(selection.selected_codes),
        "HISTORY_INPUT_MISMATCH",
        "선정 종목과 저장 결과의 개수가 다릅니다.",
    )
    prices: dict[str, tuple[DailyBar, ...]] = {}
    diagnostics: list[SymbolInputDiagnostics] = []
    for code, state in zip(selection.selected_codes, states, strict=True):
        candidate = by_code[code]
        _require(
            state.ordinal == candidate.ordinal
            and 0 <= state.ordinal < len(job.targets)
            and job.targets[state.ordinal] == candidate.target,
            "HISTORY_TARGET_MISMATCH",
            "선정 후보의 target 식별자·ordinal·고정 원천 근거가 history 작업과 다릅니다.",
        )
        _require(
            state.status == SymbolStatus.COMPLETED and state.result is not None,
            "HISTORY_RESULT_MISMATCH",
            "선정 종목의 저장 가격 결과가 completed가 아닙니다.",
        )
        assert state.result is not None
        _require(
            state.result.sha256 == candidate.source_price_sha256,
            "SOURCE_PRICE_HASH_MISMATCH",
            "선정 당시 원천 가격 해시와 저장 결과가 다릅니다.",
        )
        previous: date | None = None
        for bar in state.result.bars:
            _require(
                bar.stock_code == code
                and (previous is None or previous < bar.trade_date)
                and job.start <= bar.trade_date <= job.end
                and bar.close_price.is_finite()
                and bar.close_price > 0,
                "INVALID_HISTORY_PRICES",
                "저장 가격의 코드·날짜 순서·종가가 유효하지 않습니다.",
            )
            previous = bar.trade_date
        eligible = tuple(b for b in state.result.bars if b.trade_date <= selection.source.as_of)
        prices[code] = eligible
        assert candidate.consumed_input_sha256 is not None
        diagnostics.append(
            SymbolInputDiagnostics(
                code=code,
                ordinal=state.ordinal,
                verified_source_price_sha256=state.result.sha256,
                selection_consumed_input_sha256=candidate.consumed_input_sha256,
                stored_price_count=len(state.result.bars),
                eligible_price_count=len(eligible),
                first_eligible_date=eligible[0].trade_date if eligible else None,
                last_eligible_date=eligible[-1].trade_date if eligible else None,
            )
        )
    return prices, tuple(diagnostics)


def prepare_allocation_input(
    selection: CandidateSelection,
    job: HistoryJob | None,
    states: tuple[SymbolHistory, ...],
    *,
    selection_file_sha256: str,
) -> AllocationInput:
    """Consume a validated selection and hash-verified repository snapshot, without I/O.

    HistoryResult validates source hashes at construction/read. Unsafe Pydantic
    model_construct/model_copy inputs are outside this reusable service contract.
    """
    reasons: list[AllocationInputReason] = []
    symbols: tuple[SymbolInputDiagnostics, ...] = ()
    window: tuple[date, ...] = ()
    aligned = False
    matrix: AlignedReturnMatrix | None = None
    window_hash: str | None = None
    fingerprint: str | None = None

    def block(code: str, message: str) -> None:
        reasons.append(AllocationInputReason(code=code, description=message))

    if not selection.selected_codes:
        block("EMPTY_SELECTION", "선정 종목이 없어 수익률 입력을 준비할 수 없습니다.")
    elif not selection.selection_filled:
        block("SELECTION_SHORTFALL", "선정 종목 수가 요청 top에 미달합니다.")
    if any(re.fullmatch(r"[0-9]{6}", code) is None for code in selection.selected_codes):
        block("RISK_MODEL_CODE_UNSUPPORTED", "기존 위험모형은 숫자 6자리 코드만 지원합니다.")

    if selection.selected_codes:
        _require(
            job is not None, "HISTORY_INPUT_MISMATCH", "선정에 연결된 history 작업이 없습니다."
        )
        assert job is not None
        prices, symbols = _linked_prices(selection, job, states)
        if any(not bars for bars in prices.values()):
            block("NO_OBSERVATIONS_AS_OF", "일부 선정 종목에 기준일 이하의 종가 관측이 없습니다.")
        else:
            start = max(bars[0].trade_date for bars in prices.values())
            last_common_bound = min(bars[-1].trade_date for bars in prices.values())
            end = selection.reference_price_date
            if start > last_common_bound or end is None or start > end:
                block("NO_OVERLAPPING_RANGE", "선정 종목들의 관측 가격 기간이 겹치지 않습니다.")
            if any(bars[-1].trade_date != end for bars in prices.values()):
                block("PRICE_ENDPOINT_MISMATCH", "최종 사용 종점이 선정 참조 종점과 다릅니다.")
            if end is not None and start <= last_common_bound and start <= end:
                window = tuple(
                    sorted(
                        {
                            bar.trade_date
                            for bars in prices.values()
                            for bar in bars
                            if start <= bar.trade_date <= end
                        }
                    )
                )[-(_CONFIG.maximum_observations + 1) :]
                closes = {
                    code: {bar.trade_date: bar.close_price for bar in bars}
                    for code, bars in prices.items()
                }
                symbols = tuple(
                    s.model_copy(
                        update={
                            "window_price_count": sum(day in closes[s.code] for day in window),
                            "missing_dates": tuple(
                                day for day in window if day not in closes[s.code]
                            ),
                        }
                    )
                    for s in symbols
                )
                if any(s.missing_dates for s in symbols):
                    block(
                        "OBSERVED_DATE_MISMATCH", "검사 가격 창에 일부 종목의 관측 날짜가 없습니다."
                    )
                else:
                    aligned = bool(window) and all(
                        bars[-1].trade_date == end for bars in prices.values()
                    )
                if aligned:
                    if len(window) - 1 < _CONFIG.minimum_observations:
                        block(
                            "INSUFFICIENT_RETURN_OBSERVATIONS",
                            "최소 504개 수익률에는 동일 날짜열의 종가 505개 이상이 필요합니다.",
                        )
                    if not reasons:
                        try:
                            with localcontext(financial_decimal_context()):
                                values = tuple(
                                    tuple(
                                        closes[code][current] / closes[code][previous] - Decimal(1)
                                        for code in selection.selected_codes
                                    )
                                    for previous, current in pairwise(window)
                                )
                        except DecimalException:
                            raise AllocationInputError(
                                "NUMERIC_RANGE",
                                "가격·수익률이 고정 Decimal 계산 범위를 벗어났습니다.",
                            ) from None
                        matrix = AlignedReturnMatrix(
                            stock_codes=selection.selected_codes, dates=window[1:], values=values
                        )
                        window_hash = _hash(
                            {
                                "contract": "allocation_dated_closes_v1",
                                "stock_codes": selection.selected_codes,
                                "price_dates": tuple(day.isoformat() for day in window),
                                "closes": tuple(
                                    tuple(
                                        format(closes[code][day], "f")
                                        for code in selection.selected_codes
                                    )
                                    for day in window
                                ),
                            }
                        )
                        fingerprint = _hash(
                            {
                                "contract": "allocation_return_matrix_v1",
                                "date_policy": DATE_POLICY,
                                "price_basis": selection.price_basis,
                                "minimum_observations": _CONFIG.minimum_observations,
                                "maximum_observations": _CONFIG.maximum_observations,
                                "decimal_precision": 50,
                                "decimal_rounding": "ROUND_HALF_EVEN",
                                "price_window_sha256": window_hash,
                                "values": tuple(
                                    tuple(format(v, "f") for v in row) for row in values
                                ),
                            }
                        )
    if matrix is not None:
        reasons.append(
            AllocationInputReason(
                code="INPUT_READY",
                description="기존 위험모형에 전달할 수익률 입력이 준비되었습니다.",
            )
        )
    return AllocationInput(
        input_ready=matrix is not None,
        reasons=tuple(reasons),
        selected_codes=selection.selected_codes,
        selection_as_of=selection.source.as_of,
        reference_price_date=selection.reference_price_date,
        selection_file_sha256=selection_file_sha256,
        selection_source=selection.source,
        selection_policy=selection.policy,
        selection_completion=SelectionCompletion.from_selection(selection),
        history_job_id=selection.source.history_job_id,
        discovery_run_id=selection.source.discovery_run_id,
        history_contract=HistoryContract(requested_start=job.start, requested_end=job.end)
        if job
        else None,
        symbols=symbols,
        minimum_observations=_CONFIG.minimum_observations,
        maximum_observations=_CONFIG.maximum_observations,
        inspected_price_dates=window,
        used_start=window[0] if aligned else None,
        used_end=window[-1] if aligned else None,
        return_observation_count=len(window) - 1 if aligned else 0,
        return_start_dates=window[:-1] if matrix is not None else (),
        matrix=matrix,
        price_window_sha256=window_hash,
        calculation_fingerprint=fingerprint,
    )

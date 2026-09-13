"""Pure deterministic ranking of one feature at a shared observed price endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from phalanx.domain.candidate_selection import (
    CandidateEvaluation,
    CandidateSelection,
    SelectionPolicy,
    SelectionReason,
    SelectionSource,
    valid_candidate_code,
)
from phalanx.domain.price_features import (
    CandidatePriceFeatures,
    PriceFeatureMetric,
    SymbolPriceFeatures,
)
from phalanx.domain.price_history import SymbolStatus
from phalanx.selection.errors import SelectionInputError
from phalanx.selection.validation import validate_features


@dataclass(frozen=True)
class _Evaluation:
    symbol: SymbolPriceFeatures
    feature: PriceFeatureMetric
    reasons: tuple[SelectionReason, ...]

    @property
    def score(self) -> Decimal:
        assert self.feature.value is not None
        return self.feature.value


def _unavailable_reasons(
    symbol: SymbolPriceFeatures,
    feature: PriceFeatureMetric,
    reference: date | None,
    policy: SelectionPolicy,
) -> tuple[SelectionReason, ...]:
    reasons: list[SelectionReason] = []
    if symbol.source_status != SymbolStatus.COMPLETED:
        reasons.append(
            SelectionReason(
                code=f"SOURCE_{symbol.source_status.value.upper()}",
                description=f"원천 {symbol.source_status.value} 상태는 평가 불가입니다.",
            )
        )
    if not valid_candidate_code(symbol.target.short_code):
        reasons.append(
            SelectionReason(
                code="INVALID_IDENTIFIER",
                description="정확한 ASCII 숫자·대문자 6자리 식별자가 없습니다.",
            )
        )
    if not feature.available:
        reasons.append(
            SelectionReason(
                code="METRIC_UNAVAILABLE",
                description="선택한 가격 지표를 계산할 수 없는 원천 결과입니다.",
            )
        )
    if reference is None:
        reasons.append(
            SelectionReason(
                code="NO_REFERENCE_PRICE_DATE",
                description="입력에 비교 종점으로 사용할 완료 관측일이 없습니다.",
            )
        )
    elif symbol.used_end is None:
        reasons.append(
            SelectionReason(
                code="PRICE_OBSERVATION_UNAVAILABLE",
                description="기준일 이하의 가격 종점이 없습니다.",
            )
        )
    elif symbol.used_end != reference:
        reasons.append(
            SelectionReason(
                code="PRICE_ENDPOINT_MISMATCH",
                description="가격 종점이 입력의 최신 완료 관측 종점과 다릅니다.",
            )
        )
    if (
        symbol.calendar_days_since_last_observation is not None
        and symbol.calendar_days_since_last_observation > policy.max_age_days
    ):
        reasons.append(
            SelectionReason(
                code="PRICE_TOO_OLD",
                description="기준일까지의 가격 경과 달력일이 명시한 한도를 초과합니다.",
            )
        )
    return tuple(reasons)


def select_candidates(
    features: CandidatePriceFeatures,
    policy: SelectionPolicy,
    *,
    input_sha256: str,
    evaluated_at: datetime,
) -> CandidateSelection:
    """Rank only eligible candidates; preserve every input row and exact feature value."""
    validate_features(features)
    if re.fullmatch(r"[0-9a-f]{64}", input_sha256) is None:
        raise SelectionInputError("INVALID_INPUT_HASH", "입력 바이트의 SHA-256이 필요합니다.")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise SelectionInputError(
            "INVALID_EVALUATION_TIME", "timezone-aware 평가 시각이 필요합니다."
        )
    try:
        evaluation_time = evaluated_at.astimezone(UTC)
    except OverflowError:
        raise SelectionInputError(
            "INVALID_EVALUATION_TIME", "UTC로 표현할 수 없는 평가 시각입니다."
        ) from None
    reference = max(
        (
            s.used_end
            for s in features.symbols
            if s.source_status == SymbolStatus.COMPLETED and s.used_end is not None
        ),
        default=None,
    )
    rule = policy.rule
    evaluations: list[_Evaluation] = []
    for symbol in features.symbols:
        feature = next(
            m for m in symbol.metrics if (m.name, m.intervals) == (rule.name, rule.intervals)
        )
        evaluations.append(
            _Evaluation(symbol, feature, _unavailable_reasons(symbol, feature, reference, policy))
        )
    # Two stable comparisons avoid negation/quantization of Decimal scores, even
    # when the active Decimal context has a tiny precision or traps Inexact.
    eligible = sorted(
        (item for item in evaluations if not item.reasons),
        key=lambda item: item.symbol.target.short_code or "",
    )
    eligible.sort(key=lambda item: item.score, reverse=rule.direction == "descending")
    ranks: dict[int, tuple[int, int]] = {}
    previous_score: Decimal | None = None
    rank = 0
    for order, item in enumerate(eligible, 1):
        if previous_score is None or item.score != previous_score:
            rank = order
        ranks[item.symbol.ordinal] = rank, order
        previous_score = item.score

    candidates: list[CandidateEvaluation] = []
    for item in evaluations:
        symbol = item.symbol
        metric_rank, selection_order = ranks.get(symbol.ordinal, (None, None))
        status: Literal["selected", "not_selected", "unavailable"]
        if item.reasons:
            status = "unavailable"
            reasons = item.reasons
        elif selection_order is not None and selection_order <= policy.top:
            status = "selected"
            reasons = (
                SelectionReason(
                    code="SELECTED_TOP_N", description="명시한 정책의 상위 범위에 선정되었습니다."
                ),
            )
        else:
            status = "not_selected"
            reasons = (
                SelectionReason(
                    code="OUTSIDE_TOP_N", description="평가 가능하지만 요청한 상위 범위 밖입니다."
                ),
            )
        candidates.append(
            CandidateEvaluation(
                ordinal=symbol.ordinal,
                target=symbol.target,
                source_status=symbol.source_status,
                source_error_code=symbol.source_error_code,
                source_error_message=symbol.source_error_message,
                source_price_sha256=symbol.source_price_sha256,
                consumed_input_sha256=symbol.consumed_input_sha256,
                eligible_observation_count=symbol.eligible_observation_count,
                used_observation_count=symbol.used_observation_count,
                used_start=symbol.used_start,
                used_end=symbol.used_end,
                last_close=symbol.last_close,
                calendar_days_since_last_observation=symbol.calendar_days_since_last_observation,
                selected_feature=item.feature,
                score=item.feature.value,
                status=status,
                metric_rank=metric_rank,
                selection_order=selection_order,
                reasons=reasons,
            )
        )
    selected_codes = tuple(item.symbol.target.short_code or "" for item in eligible[: policy.top])
    evaluation_complete = len(eligible) == len(features.symbols)
    selection_filled = len(selected_codes) == policy.top
    return CandidateSelection(
        source=SelectionSource(
            input_sha256=input_sha256,
            history_job_id=features.history_job_id,
            discovery_run_id=features.discovery_run_id,
            as_of=features.as_of,
            calculated_at=features.calculated_at,
            feature_schema_version=features.schema_version,
            feature_policy=features.policy,
            features_complete=features.complete,
        ),
        policy=policy,
        sort_direction=rule.direction,
        reference_price_date=reference,
        evaluated_at=evaluation_time,
        candidates=tuple(candidates),
        selected_codes=selected_codes,
        requested_top=policy.top,
        eligible_count=len(eligible),
        selected_count=len(selected_codes),
        not_selected_count=len(eligible) - len(selected_codes),
        unavailable_count=len(features.symbols) - len(eligible),
        shortfall=policy.top - len(selected_codes),
        evaluation_complete=evaluation_complete,
        selection_filled=selection_filled,
        complete=evaluation_complete and selection_filled,
    )

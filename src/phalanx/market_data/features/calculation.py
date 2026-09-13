"""Pure independent observed-close calculations; no storage, calendars or network."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException, localcontext
from itertools import pairwise

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_features import (
    CandidatePriceFeatures,
    MetricName,
    PriceFeatureMetric,
    PriceFeaturePolicy,
    SymbolPriceFeatures,
)
from phalanx.domain.price_history import HistoryJob, HistoryTarget, SymbolHistory, SymbolStatus
from phalanx.market_data.features.errors import PriceFeatureError

_POLICY = PriceFeaturePolicy()
_MAX_OBSERVATIONS = (
    max(*_POLICY.return_intervals, *_POLICY.volatility_intervals, *_POLICY.drawdown_intervals) + 1
)
_ZERO = Decimal(0)
_ONE = Decimal(1)


def calculate_price_features(
    job: HistoryJob,
    states: tuple[SymbolHistory, ...],
    *,
    as_of: date,
    calculated_at: datetime,
) -> CandidatePriceFeatures:
    """Calculate a selected, validated history snapshot without aligning symbols."""
    if type(as_of) is not date or not job.start <= as_of <= job.end:
        raise PriceFeatureError(
            "INVALID_AS_OF", "as_of는 history 작업 요청 기간 안의 날짜여야 합니다."
        )
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise PriceFeatureError("INVALID_CLOCK", "timezone-aware 계산 시각이 필요합니다.")
    ordinals = [state.ordinal for state in states]
    if (
        not states
        or len(set(ordinals)) != len(states)
        or any(ordinal < 0 or ordinal >= len(job.targets) for ordinal in ordinals)
    ):
        raise PriceFeatureError("INVALID_SELECTION", "작업의 중복 없는 종목 선택이 필요합니다.")
    for state in states:
        if state.result is not None and any(
            bar.stock_code != job.targets[state.ordinal].short_code
            or not job.start <= bar.trade_date <= job.end
            for bar in state.result.bars
        ):
            raise PriceFeatureError(
                "INVALID_HISTORY_INPUT", "가격의 종목·기간이 고정 입력과 다릅니다."
            )
    try:
        with localcontext(financial_decimal_context()):
            symbols = tuple(_calculate_symbol(job.targets[s.ordinal], s, as_of) for s in states)
    except DecimalException:
        raise PriceFeatureError(
            "NUMERIC_RANGE", "가격 또는 계산 결과가 고정 Decimal 계산 범위를 벗어났습니다."
        ) from None
    return CandidatePriceFeatures(
        history_job_id=job.job_id,
        discovery_run_id=job.discovery_run_id,
        history_requested_start=job.start,
        history_requested_end=job.end,
        as_of=as_of,
        calculated_at=calculated_at.astimezone(UTC),
        policy=_POLICY,
        symbols=symbols,
        complete=all(symbol.complete for symbol in symbols),
    )


def _calculate_symbol(
    target: HistoryTarget, state: SymbolHistory, as_of: date
) -> SymbolPriceFeatures:
    source = state.result
    eligible = tuple(bar for bar in source.bars if bar.trade_date <= as_of) if source else ()
    used = eligible[-_MAX_OBSERVATIONS:]
    reason_code: str | None = None
    reason: str | None = None
    if state.status != SymbolStatus.COMPLETED:
        reason_code = f"SOURCE_{state.status.value.upper()}"
        reason = f"원천 상태가 {state.status.value}이므로 계산할 종가 자료가 없습니다."
    elif not eligible:
        reason_code = "NO_OBSERVATIONS_AS_OF"
        reason = "기준일 이하의 관측 종가가 없습니다."
    settings: tuple[tuple[MetricName, tuple[int, ...]], ...] = (
        ("price_return", _POLICY.return_intervals),
        ("annualized_volatility", _POLICY.volatility_intervals),
        ("maximum_drawdown", _POLICY.drawdown_intervals),
    )
    metrics = tuple(
        _metric(name, intervals, used, len(eligible), reason_code, reason)
        for name, periods in settings
        for intervals in periods
    )
    return SymbolPriceFeatures(
        ordinal=state.ordinal,
        target=target,
        source_status=state.status,
        source_error_code=state.error_code,
        source_error_message=state.error_message,
        source_price_sha256=source.sha256 if source else None,
        consumed_input_sha256=_consumed_hash(target.short_code, as_of, used) if source else None,
        eligible_observation_count=len(eligible),
        used_observation_count=len(used),
        used_start=used[0].trade_date if used else None,
        used_end=used[-1].trade_date if used else None,
        last_close=used[-1].close_price if used else None,
        calendar_days_since_last_observation=(as_of - used[-1].trade_date).days if used else None,
        metrics=metrics,
    )


def _metric(
    name: MetricName,
    intervals: int,
    used: tuple[DailyBar, ...],
    available_observations: int,
    reason_code: str | None,
    reason: str | None,
) -> PriceFeatureMetric:
    required = intervals + 1
    if reason_code is None and len(used) < required:
        reason_code = "INSUFFICIENT_OBSERVATIONS"
        reason = (
            f"{intervals}개 관측 구간에는 {required}개 종가가 필요하지만 "
            f"기준일 이하 관측은 {available_observations}개입니다."
        )
    if reason_code is not None:
        return PriceFeatureMetric(
            name=name,
            intervals=intervals,
            required_observations=required,
            available_observations=available_observations,
            window_start=None,
            window_end=None,
            value=None,
            available=False,
            reason_code=reason_code,
            reason=reason,
        )
    window = used[-required:]
    closes = tuple(bar.close_price for bar in window)
    if name == "price_return":
        value = closes[-1] / closes[0] - _ONE
    elif name == "annualized_volatility":
        returns = tuple(current / previous - _ONE for previous, current in pairwise(closes))
        mean = sum(returns, _ZERO) / Decimal(intervals)
        variance = sum(((r - mean) ** 2 for r in returns), _ZERO) / Decimal(
            intervals - _POLICY.variance_ddof
        )
        value = variance.sqrt() * Decimal(_POLICY.annualization_periods).sqrt()
    else:
        peak = closes[0]
        value = _ZERO
        for close in closes:
            peak = max(peak, close)
            value = min(value, close / peak - _ONE)
    return PriceFeatureMetric(
        name=name,
        intervals=intervals,
        required_observations=required,
        available_observations=available_observations,
        window_start=window[0].trade_date,
        window_end=window[-1].trade_date,
        value=_ZERO if value == 0 else value,
        available=True,
    )


def _consumed_hash(stock_code: str | None, as_of: date, used: tuple[DailyBar, ...]) -> str:
    # Only dated closes used by the metrics, code and cutoff are consumed inputs.
    # Source OHLCV hashes, job metadata and calculation time are separate evidence.
    payload = {
        "contract": _POLICY.consumed_input_contract,
        "stock_code": stock_code,
        "as_of": as_of.isoformat(),
        "closes": [
            {"trade_date": bar.trade_date.isoformat(), "close_price": format(bar.close_price, "f")}
            for bar in used
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()

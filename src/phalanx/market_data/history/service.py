"""Offline job creation and sequential, bounded, resumable symbol collection."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from phalanx.domain.discovery import Eligibility, Snapshot
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import (
    HistoryAttempt,
    HistoryJob,
    HistoryResult,
    HistoryTarget,
    HistoryView,
    SymbolHistory,
    SymbolStatus,
    price_data_hash,
)
from phalanx.market_data.errors import InvalidMarketDataRequestError
from phalanx.market_data.history.errors import HistoryError, HistoryFetchError
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.market_data.service import DailyBarReader
from phalanx.market_data.validation import validate_daily_date_range, validate_daily_stock_code

ProviderFactory = Callable[[], AbstractContextManager[DailyBarReader]]


class DiscoveryRunReader(Protocol):
    def load_successful_run(self, run_id: str) -> Snapshot: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class HistoryService:
    def __init__(
        self, repository: SqliteHistoryRepository, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.repository = repository
        self._clock = clock

    def create(
        self,
        discovery: DiscoveryRunReader,
        run_id: str,
        start: date,
        end: date,
        *,
        codes: tuple[str, ...] = (),
        all_eligible: bool = False,
    ) -> HistoryView:
        validate_daily_date_range(start, end)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise HistoryError("INVALID_CLOCK", "timezone-aware 수집 시각이 필요합니다.")
        if end >= now.astimezone(ZoneInfo("Asia/Seoul")).date():
            raise HistoryError(
                "INVALID_END_DATE", "종료일은 Asia/Seoul 기준 오늘보다 이전이어야 합니다."
            )
        if bool(codes) == all_eligible:
            raise HistoryError(
                "TARGET_SELECTION_REQUIRED", "--code 또는 --all-eligible 중 하나가 필요합니다."
            )
        if len(codes) != len(set(codes)):
            raise HistoryError("DUPLICATE_CODE", "중복 --code는 허용하지 않습니다.")
        snapshot = discovery.load_successful_run(run_id)
        # Enforce the service contract even for a different discovery adapter.
        if snapshot.run_id != run_id or snapshot.status != "success":
            raise HistoryError("RUN_NOT_SUCCESSFUL", "지정한 성공 discovery 실행이 필요합니다.")
        eligible = [
            HistoryTarget(
                market=market.market,
                short_code=c.record.short_code,
                standard_code=c.record.standard_code,
                name=c.record.name,
                policy_version=c.decision.policy_version,
                source_files=market.sources,
            )
            for market in snapshot.markets
            for c in market.candidates
            if c.decision.status == Eligibility.ELIGIBLE
        ]
        known = [t.short_code for t in eligible if t.short_code is not None]
        if len(known) != len(set(known)):
            raise HistoryError(
                "AMBIGUOUS_CODE", "입력 실행의 적격 단축코드가 중복되어 대상을 확정할 수 없습니다."
            )
        if codes:
            by_code = {t.short_code: t for t in eligible}
            if any(code not in by_code for code in codes):
                raise HistoryError(
                    "NOT_ELIGIBLE", "요청 종목이 지정 실행에 없거나 적격 후보가 아닙니다."
                )
            targets = tuple(by_code[code] for code in codes)
        else:
            targets = tuple(eligible)
        if not targets:
            raise HistoryError("NO_TARGETS", "해당 실행에 적격 후보가 없습니다.")
        states: list[SymbolHistory] = []
        for ordinal, target in enumerate(targets):
            try:
                validate_daily_stock_code(target.short_code)
            except InvalidMarketDataRequestError:
                states.append(
                    SymbolHistory(
                        ordinal=ordinal,
                        status=SymbolStatus.UNSUPPORTED,
                        error_code="UNSUPPORTED_IDENTIFIER",
                        error_message="일봉 요청 형식 미지원: ASCII 숫자·대문자 6자리 필요.",
                    )
                )
            else:
                states.append(SymbolHistory(ordinal=ordinal, status=SymbolStatus.PENDING))
        view = HistoryView(
            job=HistoryJob(
                job_id=uuid4().hex,
                created_at=now,
                discovery_run_id=run_id,
                discovery_started_at=snapshot.collection_started_at,
                discovery_completed_at=snapshot.collection_completed_at,
                start=start,
                end=end,
                targets=targets,
            ),
            symbols=tuple(states),
        )
        self.repository.create(view)
        return view

    def run(
        self,
        job_id: str,
        provider_factory: ProviderFactory,
        *,
        retry_failed: bool = False,
        max_symbols: int | None = None,
    ) -> HistoryView:
        if max_symbols is not None and (type(max_symbols) is not int or max_symbols < 1):
            raise HistoryError("INVALID_LIMIT", "--max-symbols는 1 이상의 정수여야 합니다.")
        with self.repository.execution_lock(job_id):
            view = self.repository.load(job_id)
            for state in view.symbols:
                if state.status == SymbolStatus.IN_PROGRESS:
                    self._interrupt(job_id, state, recovered=True)
            view = self.repository.load(job_id)
            selected = tuple(
                s
                for s in view.symbols
                if s.status == SymbolStatus.PENDING
                or (retry_failed and s.status == SymbolStatus.FAILED)
            )[:max_symbols]
            # No credentials/OAuth needed when there is no remaining authorized work.
            if selected:
                with provider_factory() as provider:
                    for state in selected:
                        if not self._collect(view.job, state, provider):
                            break
            return self.repository.load(job_id)

    def _interrupt(self, job_id: str, state: SymbolHistory, *, recovered: bool = False) -> None:
        previous = state.attempts[-1]
        attempt = HistoryAttempt(
            number=previous.number,
            started_at=previous.started_at,
            finished_at=None if recovered else self._clock(),
            recovered_at=self._clock() if recovered else None,
            outcome="interrupted",
            error_code="PROCESS_INTERRUPTED" if recovered else "INTERRUPTED",
            error_message="완료되지 않은 시도입니다. 재개 시 요청 기간 전체를 다시 조회합니다.",
        )
        self.repository.save_symbol(
            job_id,
            state,
            SymbolHistory(
                ordinal=state.ordinal,
                status=SymbolStatus.PENDING,
                attempts=(*state.attempts[:-1], attempt),
            ),
        )

    def _collect(self, job: HistoryJob, state: SymbolHistory, provider: DailyBarReader) -> bool:
        code = job.targets[state.ordinal].short_code
        validated_code = validate_daily_stock_code(code)
        attempt = HistoryAttempt(
            number=len(state.attempts) + 1, started_at=self._clock(), outcome="in_progress"
        )
        active = SymbolHistory(
            ordinal=state.ordinal,
            status=SymbolStatus.IN_PROGRESS,
            attempts=(*state.attempts, attempt),
        )
        self.repository.save_symbol(job.job_id, state, active)
        try:
            try:
                bars = provider.fetch_daily_bars(validated_code, job.start, job.end)
                self._validate_bars(bars, validated_code, job.start, job.end)
            except HistoryFetchError as error:
                failed = HistoryAttempt(
                    number=attempt.number,
                    started_at=attempt.started_at,
                    finished_at=self._clock(),
                    outcome="failed",
                    error_code=error.code,
                    error_message=str(error),
                )
                self.repository.save_symbol(
                    job.job_id,
                    active,
                    SymbolHistory(
                        ordinal=state.ordinal,
                        status=SymbolStatus.FAILED,
                        attempts=(*state.attempts, failed),
                        error_code=error.code,
                        error_message=str(error),
                    ),
                )
                return not error.common
            result = HistoryResult(
                bars=bars,
                row_count=len(bars),
                first_trade_date=bars[0].trade_date if bars else None,
                last_trade_date=bars[-1].trade_date if bars else None,
                sha256=price_data_hash(bars),
            )
            finished = HistoryAttempt(
                number=attempt.number,
                started_at=attempt.started_at,
                finished_at=self._clock(),
                outcome="completed" if bars else "empty",
            )
            self.repository.save_symbol(
                job.job_id,
                active,
                SymbolHistory(
                    ordinal=state.ordinal,
                    status=SymbolStatus.COMPLETED if bars else SymbolStatus.EMPTY,
                    attempts=(*state.attempts, finished),
                    result=result,
                ),
            )
            return True
        except KeyboardInterrupt:
            # A write may already have committed: reread before marking interruption.
            current = self.repository.load(job.job_id).symbols[state.ordinal]
            if current.status == SymbolStatus.IN_PROGRESS:
                self._interrupt(job.job_id, current)
            raise

    @staticmethod
    def _validate_bars(bars: tuple[DailyBar, ...], code: str, start: date, end: date) -> None:
        dates = [bar.trade_date for bar in bars]
        if dates != sorted(set(dates)) or any(
            bar.stock_code != code or not start <= bar.trade_date <= end for bar in bars
        ):
            raise HistoryFetchError(
                "DATA_CONFLICT", "응답 종목·기간·날짜 순서가 요청과 일치하지 않습니다."
            )

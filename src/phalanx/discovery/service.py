"""Refresh and offline query use cases shared by CLI and future GUI callers."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from phalanx.discovery.errors import DiscoveryError, DiscoveryStorageError
from phalanx.discovery.policy import POLICY_VERSION, evaluate
from phalanx.discovery.provider import MasterProvider
from phalanx.discovery.repository import DiscoveryRepository
from phalanx.domain.discovery import (
    CandidateResult,
    DiscoveryView,
    Eligibility,
    Market,
    MarketSnapshot,
    ParseIssue,
    Reason,
    Snapshot,
    SourceFile,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _resolve_duplicates(markets: list[MarketSnapshot]) -> tuple[MarketSnapshot, ...]:
    groups: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for mi, market in enumerate(markets):
        for ri, candidate in enumerate(market.candidates):
            for field in ("short_code", "standard_code"):
                value = getattr(candidate.record, field)
                if value:
                    groups[(field, value)].append((mi, ri))
    affected: dict[tuple[int, int], str] = {}
    for indices in groups.values():
        if len(indices) < 2:
            continue
        first = markets[indices[0][0]].candidates[indices[0][1]].record
        identical = all(
            markets[mi].candidates[ri].record.market == first.market
            and markets[mi].candidates[ri].record.raw_fields == first.raw_fields
            for mi, ri in indices
        )
        code = "DUPLICATE_RECORD" if identical else "RECORD_CONFLICT"
        for key in indices:
            if affected.get(key) != "RECORD_CONFLICT":
                affected[key] = code
    for mi, market in enumerate(markets):
        records = list(market.candidates)
        issues = list(market.issues)
        for ri, candidate in enumerate(records):
            issue_code = affected.get((mi, ri))
            if issue_code is None:
                continue
            description = (
                "동일 식별자의 중복 레코드"
                if issue_code == "DUPLICATE_RECORD"
                else "단축·표준코드에 연결된 레코드 정보 충돌"
            )
            reason = Reason(code=issue_code, description=description, kind="unknown")
            records[ri] = CandidateResult(
                record=candidate.record, decision=evaluate(candidate.record, conflicts=(reason,))
            )
            issues.append(
                ParseIssue(
                    code=issue_code,
                    description=description,
                    line_number=candidate.record.line_number,
                )
            )
        if len(issues) != len(market.issues):
            markets[mi] = market.model_copy(
                update={
                    "candidates": tuple(records),
                    "issues": tuple(issues),
                    "parse_status": "failed" if market.parse_status == "failed" else "conflict",
                }
            )
    return tuple(markets)


class DiscoveryService:
    def __init__(
        self,
        repository: DiscoveryRepository,
        provider: MasterProvider,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self._clock = clock

    def refresh(self) -> Snapshot:
        started = self._clock()
        run_id = uuid4().hex
        self.repository.begin(run_id, started)
        artifacts: dict[tuple[Market, str], bytes] = {}
        markets = [self._collect(market, artifacts) for market in Market]
        snapshot = Snapshot(
            run_id=run_id,
            collection_started_at=started,
            collection_completed_at=self._clock(),
            markets=_resolve_duplicates(markets),
        )
        try:
            self.repository.save(snapshot, artifacts)
        except DiscoveryStorageError:
            # If even this write fails, the durable in_progress journal still exposes failure.
            with suppress(DiscoveryStorageError):
                self.repository.storage_failed(run_id, self._clock())
            raise
        return snapshot

    def _collect(
        self, market: Market, artifacts: dict[tuple[Market, str], bytes]
    ) -> MarketSnapshot:
        started = self._clock()
        sources: list[SourceFile] = []
        download_status: Literal["success", "failed"] = "failed"
        parse_status: Literal["success", "failed", "not_attempted"] = "not_attempted"
        issues: tuple[ParseIssue, ...] = ()
        candidates: tuple[CandidateResult, ...] = ()
        total = 0
        last_modified = None

        def preserve(filename: str, payload: bytes) -> None:
            artifacts[(market, filename)] = payload
            sources.append(
                SourceFile(
                    filename=filename,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                )
            )

        try:
            downloaded = self.provider.download(market)
            download_status = "success"
            last_modified = downloaded.last_modified
            filename = f"{market.value.lower()}_code.mst"
            preserve(filename + ".zip", downloaded.payload)
            parse_status = "failed"
            raw = self.provider.unpack(market, downloaded.payload)
            preserve(filename, raw)
            parsed = self.provider.parse(market, raw)
            total = parsed.total_lines
            issues = parsed.issues
            if not parsed.records and not issues:
                issues = (ParseIssue(code="EMPTY_MASTER", description="정규화 레코드가 없습니다."),)
            parse_status = "failed" if issues else "success"
            candidates = tuple(
                CandidateResult(record=record, decision=evaluate(record))
                for record in parsed.records
            )
        except DiscoveryError as error:
            issues = (ParseIssue(code=error.code, description=str(error)),)
        return MarketSnapshot(
            provider=self.provider.name,
            market=market,
            source_url=self.provider.source_url(market),
            collection_started_at=started,
            collection_completed_at=self._clock(),
            http_last_modified=last_modified,
            schema_version=self.provider.schema_version,
            parser_version=self.provider.parser_version,
            policy_version=POLICY_VERSION,
            download_status=download_status,
            parse_status=parse_status,
            total_records=total,
            issues=issues,
            sources=tuple(sources),
            candidates=candidates,
        )

    def view(self) -> DiscoveryView:
        return self.repository.load()

    @staticmethod
    def list_candidates(
        view: DiscoveryView, status: Eligibility | None = None
    ) -> tuple[CandidateResult, ...]:
        if view.snapshot is None:
            return ()
        return tuple(
            c
            for m in view.snapshot.markets
            for c in m.candidates
            if status is None or c.decision.status == status
        )

    @staticmethod
    def show_candidate(view: DiscoveryView, short_code: str) -> tuple[CandidateResult, ...]:
        return tuple(
            c for c in DiscoveryService.list_candidates(view) if c.record.short_code == short_code
        )

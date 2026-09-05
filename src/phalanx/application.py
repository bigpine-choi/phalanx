"""Thin orchestration for account snapshots and offline period performance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from phalanx.account_performance import AccountPerformanceError, calculate_account_performance
from phalanx.config import load_kis_credentials
from phalanx.domain import AccountSnapshot
from phalanx.domain.account_performance import AccountPerformance, CashFlowLedger
from phalanx.kis import KisBalanceClient, KisTokenManager
from phalanx.portfolio.private_json_storage import store_private_json_bytes
from phalanx.snapshots import SnapshotStore

_APPLICATION_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class _BalanceReader(Protocol):
    def fetch_balance(self) -> AccountSnapshot: ...


class _SnapshotWriter(Protocol):
    def save(self, snapshot: AccountSnapshot) -> Path: ...


@dataclass(frozen=True)
class AccountSnapshotResult:
    """A complete immutable observation and its safely persisted path."""

    snapshot: AccountSnapshot
    saved_path: Path


@dataclass(frozen=True)
class AccountPerformanceInputHashes:
    """SHA-256 of the exact three input files consumed by this run."""

    start_snapshot: str
    end_snapshot: str
    cash_flows: str


@dataclass(frozen=True)
class AccountPerformanceResult:
    """Deterministic account-wide calculation, provenance and optional output path."""

    performance: AccountPerformance
    input_sha256: AccountPerformanceInputHashes
    saved_path: Path | None = None

    def to_json_bytes(self) -> bytes:
        """Serialize unquantized values without paths, run IDs or wall-clock times."""

        payload = self.performance.model_dump(mode="json")
        payload["input_sha256"] = asdict(self.input_sha256)
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _safe_ledger_validation_reason(error: ValidationError) -> str:
    """Select static guidance only; validation inputs and arbitrary keys stay private."""

    locations = {part for item in error.errors() for part in item["loc"] if isinstance(part, str)}
    if "no_in_kind_transfers" in locations:
        return "현물 입출고가 있는 기간은 v1 미지원이며 no_in_kind_transfers는 true여야 합니다."
    if "same_account_confirmed" in locations:
        return "동일계좌 사용자 선언 same_account_confirmed는 true여야 합니다."
    if "external_flows_complete" in locations:
        return "외부 자금이동 완전성 선언 external_flows_complete는 true여야 합니다."
    if "schema_version" in locations:
        return 'schema_version은 문자열 "1"을 명시해야 합니다.'
    if {"coverage_start", "coverage_end", "occurred_at"} & locations:
        return "기간·발생시각은 timezone-aware ISO 8601 시각이어야 합니다."
    if "amount" in locations:
        return "amount는 0이 아닌 유한한 십진 문자열이어야 합니다."
    return "기간·필수 선언·events·고유 event_id와 지원 스키마를 확인해 주세요."


def _load_account_performance_input[InputModel: BaseModel](
    path: Path, model: type[InputModel], label: str
) -> tuple[InputModel, str]:
    try:
        payload = path.read_bytes()
    except OSError:
        raise AccountPerformanceError(f"{label} 파일을 읽지 못했습니다.") from None
    try:
        decoded = json.loads(
            payload,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
        parsed = model.model_validate(decoded)
    except ValidationError as error:
        reason = (
            _safe_ledger_validation_reason(error)
            if model is CashFlowLedger
            else "기존 AccountSnapshot 스키마·계좌 식별값·순자산·조회시각을 확인해 주세요."
        )
        raise AccountPerformanceError(f"{label} 검증 실패: {reason}") from None
    except (ValueError, UnicodeError, RecursionError):
        raise AccountPerformanceError(
            f"{label} JSON이 잘못되었습니다. 중복 키·비유한 값도 허용하지 않습니다."
        ) from None
    return parsed, hashlib.sha256(payload).hexdigest()


def run_account_performance(
    start_snapshot_path: Path,
    end_snapshot_path: Path,
    cash_flows_path: Path,
    *,
    output_path: Path | None = None,
) -> AccountPerformanceResult:
    """Read exactly the supplied files and calculate without credentials or networking."""

    start, start_hash = _load_account_performance_input(
        start_snapshot_path, AccountSnapshot, "시작 스냅샷"
    )
    end, end_hash = _load_account_performance_input(
        end_snapshot_path, AccountSnapshot, "종료 스냅샷"
    )
    ledger, ledger_hash = _load_account_performance_input(
        cash_flows_path, CashFlowLedger, "외부 입출금 원장"
    )
    result = AccountPerformanceResult(
        performance=calculate_account_performance(start, end, ledger),
        input_sha256=AccountPerformanceInputHashes(start_hash, end_hash, ledger_hash),
    )
    if output_path is None:
        return result
    saved_path = store_private_json_bytes(output_path, result.to_json_bytes())
    return AccountPerformanceResult(result.performance, result.input_sha256, saved_path)


class AccountSnapshotApplication:
    """Persist a balance only after every read-only page completed successfully."""

    def __init__(self, balance_reader: _BalanceReader, snapshot_writer: _SnapshotWriter) -> None:
        self._balance_reader = balance_reader
        self._snapshot_writer = snapshot_writer

    def run(self) -> AccountSnapshotResult:
        """Fetch, then atomically store, one complete account snapshot."""

        snapshot = self._balance_reader.fetch_balance()
        saved_path = self._snapshot_writer.save(snapshot)
        return AccountSnapshotResult(snapshot=snapshot, saved_path=saved_path)


def run_production_snapshot(
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    snapshot_directory: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> AccountSnapshotResult:
    """Build the fixed real-account production graph and execute it once.

    Paths and transport are injectable for isolated tests, but are not exposed as
    CLI options. With no injection, each component resolves its fixed external
    production path at execution time.
    """

    credentials = load_kis_credentials(credentials_path)
    with httpx.Client(transport=transport, timeout=_APPLICATION_TIMEOUT) as http_client:
        token_manager = KisTokenManager(
            credentials,
            cache_path=token_cache_path,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        balance_client = KisBalanceClient(
            credentials,
            token_manager,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        application = AccountSnapshotApplication(
            balance_client,
            SnapshotStore(snapshot_directory),
        )
        return application.run()


__all__ = [
    "AccountPerformanceInputHashes",
    "AccountPerformanceResult",
    "AccountSnapshotApplication",
    "AccountSnapshotResult",
    "run_account_performance",
    "run_production_snapshot",
]

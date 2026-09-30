"""Replay an existing selection against an explicit decision-time input claim.

This manifest records when a source says its data was available. It cannot
establish historical availability of each underlying price observation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from phalanx.domain.candidate_selection import CandidateSelection, SelectionPolicy
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)
from phalanx.selection.engine import select_candidates
from phalanx.selection.errors import SelectionInputError
from phalanx.selection.validation import parse_features

_MARKET_TIMEZONE = timezone(timedelta(hours=9))


class DecisionInputError(SelectionInputError):
    def __init__(self, code: str = "INVALID_DECISION_MANIFEST") -> None:
        super().__init__(code, "판단 시점 명세와 features 입력의 일관성을 확인해 주세요.")


class DecisionStorageError(Exception):
    """The manifest or feature file could not be read."""


class DecisionManifest(BaseModel):
    """External availability claim for one exact feature-file byte sequence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    snapshot_id: str
    source_name: str
    source_revision: str
    features_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_schema_version: Literal["1"]
    feature_policy_version: Literal["candidate_price_features_v1"]
    price_basis: Literal["adjusted_close_price_return_excluding_dividends"]
    return_unit: Literal["simple_decimal_ratio"]
    market_timezone: Literal["Asia/Seoul"]
    observed_at: AwareDatetime
    available_at: AwareDatetime
    decision_at: AwareDatetime
    availability_evidence: Literal["declared"]

    @model_validator(mode="after")
    def _coherent_claim(self) -> Self:
        if (
            not self.snapshot_id.strip()
            or not self.source_name.strip()
            or not self.source_revision.strip()
            or self.observed_at > self.available_at
            or self.available_at > self.decision_at
        ):
            raise ValueError("invalid source identity or availability order")
        return self


class DecisionSnapshotResult(BaseModel):
    """Selection and its byte-identifiable, explicitly limited time claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    manifest: DecisionManifest
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: CandidateSelection
    availability_check: Literal["declared_manifest_only"] = "declared_manifest_only"
    point_in_time_backtest_guaranteed: Literal[False] = False

    @model_validator(mode="after")
    def _coherent_source(self) -> Self:
        if (
            self.selection.source.input_sha256 != self.manifest.features_sha256
            or self.selection.source.feature_schema_version != self.manifest.feature_schema_version
            or self.selection.source.feature_policy.version != self.manifest.feature_policy_version
            or self.selection.price_basis != self.manifest.price_basis
        ):
            raise ValueError("selection and decision manifest refer to different inputs")
        return self

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonfinite JSON number")


def parse_manifest(payload: bytes) -> DecisionManifest:
    """Reject silent defaults, unknown keys, coercions and ambiguous JSON."""
    try:
        raw: object = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(raw, dict):
            raise ValueError("manifest must be an object")
        fields = set(DecisionManifest.model_fields)
        if set(raw) != fields or any(type(value) is not str for value in raw.values()):
            raise ValueError("manifest fields must be explicit strings")
        values = cast(dict[str, str], raw)
        for value in values.values():
            value.encode("utf-8")
        return DecisionManifest.model_validate(values)
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise DecisionInputError() from None


def utc_now() -> datetime:
    return datetime.now(UTC)


class DecisionSnapshotService:
    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def run(
        self,
        manifest_path: Path,
        features_path: Path,
        policy: SelectionPolicy,
    ) -> DecisionSnapshotResult:
        """Read each file once and pass the validated features to the existing engine."""
        try:
            manifest_bytes = manifest_path.read_bytes()
            features_bytes = features_path.read_bytes()
        except OSError:
            raise DecisionStorageError("입력 파일을 읽지 못했습니다.") from None
        manifest = parse_manifest(manifest_bytes)
        features_sha256 = hashlib.sha256(features_bytes).hexdigest()
        if features_sha256 != manifest.features_sha256:
            raise DecisionInputError("FEATURE_HASH_MISMATCH")
        features = parse_features(features_bytes)
        try:
            decision_date = manifest.decision_at.astimezone(_MARKET_TIMEZONE).date()
            observed_date = manifest.observed_at.astimezone(_MARKET_TIMEZONE).date()
        except OverflowError:
            raise DecisionInputError() from None
        if (
            features.schema_version != manifest.feature_schema_version
            or features.policy.version != manifest.feature_policy_version
            or features.price_basis != manifest.price_basis
            or features.as_of > decision_date
            or features.calculated_at > manifest.decision_at
            or any(
                symbol.used_end is not None and symbol.used_end > observed_date
                for symbol in features.symbols
            )
        ):
            raise DecisionInputError("FEATURE_DECISION_MISMATCH")
        selection = select_candidates(
            features,
            policy,
            input_sha256=features_sha256,
            evaluated_at=self._clock(),
        )
        return DecisionSnapshotResult(
            manifest=manifest,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            selection=selection,
        )

    @staticmethod
    def export(result: DecisionSnapshotResult, output: Path) -> Path:
        payload = result.to_json_bytes()
        if sys.platform == "win32":
            from phalanx.platforms.windows_files import (
                ensure_private_directory,
                store_private_bytes,
            )

            try:
                ensure_private_directory(output.parent)
                return store_private_bytes(output, payload)
            except FileExistsError:
                raise PrivateJsonAlreadyExistsError("private JSON output already exists") from None
            except OSError:
                raise PrivateJsonStorageError("private JSON atomic write failed") from None
        return store_private_json_bytes(output, payload)

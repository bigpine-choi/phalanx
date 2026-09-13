"""Single-read feature-file selection and write-once JSON publication."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from phalanx.domain.candidate_selection import CandidateSelection, SelectionPolicy
from phalanx.portfolio.private_json_storage import store_private_json_bytes
from phalanx.selection.engine import select_candidates
from phalanx.selection.errors import SelectionStorageError
from phalanx.selection.validation import parse_features


def utc_now() -> datetime:
    return datetime.now(UTC)


class CandidateSelectionService:
    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def select(self, features_path: Path, policy: SelectionPolicy) -> CandidateSelection:
        try:
            payload = features_path.read_bytes()
        except OSError:
            raise SelectionStorageError("features 입력 파일을 읽지 못했습니다.") from None
        features = parse_features(payload)
        return select_candidates(
            features,
            policy,
            input_sha256=hashlib.sha256(payload).hexdigest(),
            evaluated_at=self._clock(),
        )

    @staticmethod
    def export(result: CandidateSelection, output: Path) -> Path:
        return store_private_json_bytes(output, result.to_json_bytes())

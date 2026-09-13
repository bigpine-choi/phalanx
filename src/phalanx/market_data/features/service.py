"""Read one consistent history selection and optionally publish exact JSON once."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from phalanx.domain.price_features import CandidatePriceFeatures
from phalanx.market_data.features.calculation import calculate_price_features
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.private_json_storage import store_private_json_bytes


def utc_now() -> datetime:
    return datetime.now(UTC)


class PriceFeatureService:
    def __init__(
        self, repository: SqliteHistoryRepository, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.repository = repository
        self._clock = clock

    def calculate(
        self,
        job_id: str,
        *,
        as_of: date,
        codes: tuple[str, ...] = (),
        all_targets: bool = False,
    ) -> CandidatePriceFeatures:
        job, states = self.repository.read_selected(job_id, codes=codes, all_targets=all_targets)
        return calculate_price_features(job, states, as_of=as_of, calculated_at=self._clock())

    @staticmethod
    def export(result: CandidatePriceFeatures, output: Path) -> Path:
        """Export complete or partial results without replacing an existing path."""
        return store_private_json_bytes(output, result.to_json_bytes())

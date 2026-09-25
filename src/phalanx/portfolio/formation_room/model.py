"""Small presentation-only model; never includes return or covariance matrices."""

from dataclasses import asdict, dataclass, field
from typing import cast


@dataclass(frozen=True, slots=True)
class FormationRoomPresentation:
    """Explicit caller-owned demo labeling; never inferred from financial inputs."""

    synthetic_demo: bool = False

    def __post_init__(self) -> None:
        if type(self.synthetic_demo) is not bool:
            raise ValueError("synthetic_demo must be a boolean")


@dataclass(frozen=True, slots=True)
class FormationRoomModel:
    source_name: str
    source_sha256: str
    status: str
    status_label: str
    selected_codes: list[str]
    selection_as_of: str
    calculation_date: str | None
    reference_price_date: str | None
    selected_count: int
    return_observation_count: int
    succeeded_count: int
    used_start: str | None
    used_end: str | None
    symbols: list[dict[str, object]]
    scenarios: list[dict[str, object]]
    reasons: list[dict[str, object]]
    fingerprints: list[dict[str, object]]
    limitations: list[str]
    selection_linked: bool = False
    presentation: FormationRoomPresentation = field(default_factory=FormationRoomPresentation)

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))

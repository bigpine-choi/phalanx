"""Single-date ERC research outcomes; no account execution or strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from phalanx.domain.allocation_input import AllocationInput
from phalanx.domain.constrained_erc import (
    ConstrainedErcFailure,
    ConstrainedErcSolverConfig,
    ConstrainedErcTarget,
)
from phalanx.domain.risk_model import (
    SCENARIO_KIND_ORDER,
    CovarianceScenarioKind,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    RiskModelLibraryProvenance,
)
from phalanx.portfolio.allocation_targets.errors import AllocationTargetsContractError

ALLOCATION_TARGETS_SCHEMA = "phalanx.selection_allocation_targets.v1"
ALLOCATION_TARGETS_VERSION = "selection-allocation-targets-v1"


@dataclass(frozen=True, slots=True)
class AllocationTargetFailure:
    stage: Literal["input_contract", "risk_snapshot", "scenario"]
    category: Literal["calculation", "contract", "unexpected"]
    failure: ConstrainedErcFailure

    def __post_init__(self) -> None:
        if (
            self.stage not in ("input_contract", "risk_snapshot", "scenario")
            or self.category not in ("calculation", "contract", "unexpected")
            or not isinstance(self.failure, ConstrainedErcFailure)
        ):
            raise AllocationTargetsContractError("계산 실패의 단계·분류·근거가 유효하지 않습니다.")


@dataclass(frozen=True, slots=True)
class ScenarioAllocationTarget:
    scenario_kind: CovarianceScenarioKind
    status: Literal["succeeded", "failed", "not_run"]
    covariance_fingerprint: str | None = None
    target: ConstrainedErcTarget | None = None
    failure: AllocationTargetFailure | None = None

    def __post_init__(self) -> None:
        if self.status == "succeeded":
            coherent = (
                self.target is not None
                and self.failure is None
                and self.target.scenario_kind == self.scenario_kind
                and self.target.covariance_fingerprint == self.covariance_fingerprint
            )
        elif self.status == "failed":
            coherent = (
                self.target is None
                and self.failure is not None
                and self.failure.stage == "scenario"
                and self.failure.failure.scenario_kind == self.scenario_kind
            )
        elif self.status == "not_run":
            coherent = (
                self.target is None and self.failure is None and self.covariance_fingerprint is None
            )
        else:
            coherent = False
        if not coherent:
            raise AllocationTargetsContractError("시나리오 상태·목표비중·실패 근거가 모순됩니다.")


@dataclass(frozen=True, slots=True)
class AllocationTargets:
    status: Literal["input_unavailable", "common_failure", "succeeded", "partial", "failed"]
    prepared: AllocationInput
    calculation_date: date | None
    risk_config: DynamicRiskModelConfig
    solver_config: ConstrainedErcSolverConfig
    library_provenance: RiskModelLibraryProvenance
    risk_config_fingerprint: str
    solver_config_fingerprint: str
    risk_input_fingerprint: str | None
    risk_snapshot: DynamicRiskModelSnapshot | None
    common_failure: AllocationTargetFailure | None
    scenarios: tuple[ScenarioAllocationTarget, ...]

    @property
    def succeeded_count(self) -> int:
        return sum(item.status == "succeeded" for item in self.scenarios)

    @property
    def complete(self) -> bool:
        return self.status == "succeeded"

    def __post_init__(self) -> None:
        if tuple(item.scenario_kind for item in self.scenarios) != SCENARIO_KIND_ORDER:
            raise AllocationTargetsContractError("고정 순서의 네 시나리오가 필요합니다.")
        skipped = all(item.status == "not_run" for item in self.scenarios)
        if not self.prepared.input_ready:
            coherent = (
                self.status == "input_unavailable"
                and self.calculation_date is None
                and self.risk_input_fingerprint is None
                and self.risk_snapshot is None
                and self.common_failure is None
                and skipped
            )
        elif self.common_failure is not None:
            coherent = (
                self.status == "common_failure"
                and self.risk_snapshot is None
                and skipped
                and self.common_failure.stage in ("input_contract", "risk_snapshot")
            )
        else:
            expected = (
                "succeeded"
                if self.succeeded_count == 4
                else "partial"
                if self.succeeded_count
                else "failed"
            )
            coherent = (
                self.status == expected
                and self.risk_snapshot is not None
                and self.risk_input_fingerprint == self.risk_snapshot.consumed_input_fingerprint
                and self.calculation_date
                == self.prepared.used_end
                == self.prepared.reference_price_date
                == self.risk_snapshot.as_of_date
                and self.risk_snapshot.stock_codes == self.prepared.selected_codes
                and all(item.status != "not_run" for item in self.scenarios)
            )
            for item in self.scenarios:
                if item.target is not None:
                    coherent = coherent and (
                        item.target.as_of_date == self.calculation_date
                        and item.target.stock_codes == self.prepared.selected_codes
                        and item.target.solver_config_fingerprint == self.solver_config_fingerprint
                    )
                if item.failure is not None:
                    coherent = coherent and item.failure.failure.as_of_date == self.calculation_date
        if not coherent:
            raise AllocationTargetsContractError(
                "전체 상태와 입력·위험모형·시나리오 결과가 모순됩니다."
            )

    def to_json_bytes(self) -> bytes:
        from phalanx.portfolio.allocation_targets.serialization import serialize_allocation_targets

        return serialize_allocation_targets(self)

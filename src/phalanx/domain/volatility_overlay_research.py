"""Auditable research-trial contracts for the volatility-target overlay."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from phalanx.domain.allocation import AllocationBacktestResult
from phalanx.domain.constrained_erc import (
    CONSTRAINED_ERC_SCENARIO_POLICY_IDS,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcResearchTrial,
)
from phalanx.domain.risk_model import (
    SCENARIO_KIND_ORDER,
    CovarianceScenarioKind,
    RiskModelLibraryProvenance,
)
from phalanx.domain.volatility_overlay import (
    VOLATILITY_OVERLAY_CODE_MODEL_VERSION,
    VOLATILITY_OVERLAY_RESEARCH_SCOPE,
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    VOLATILITY_OVERLAY_SCHEMA,
    VOLATILITY_OVERLAY_SCHEMA_VERSION,
    VolatilityOverlayConfig,
    VolatilityOverlayTarget,
    volatility_overlay_policy_id,
)
from phalanx.portfolio.errors import InvalidVolatilityOverlayDomainError

_TRIAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class VolatilityOverlayOutcomeStatus(StrEnum):
    """One independently evaluated covariance-scenario overlay state."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VolatilityOverlayResearchStatus(StrEnum):
    """Whole-trial state; one failed scenario makes the trial failed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VolatilityOverlayFailure:
    """Allow-listed, secret-free failure information for one scenario."""

    code: str
    message: str
    as_of_date: date | None = None
    scenario_kind: CovarianceScenarioKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _FAILURE_CODE_PATTERN.fullmatch(self.code) is None:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 실패 코드는 안전한 snake_case여야 합니다."
            )
        if (
            not isinstance(self.message, str)
            or not self.message
            or self.message != self.message.strip()
            or len(self.message) > 500
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 실패 메시지는 비어 있지 않은 정제 문자열이어야 합니다."
            )
        if self.as_of_date is not None and type(self.as_of_date) is not date:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 실패 as-of는 date 또는 None이어야 합니다."
            )
        if self.scenario_kind is not None and not isinstance(
            self.scenario_kind, CovarianceScenarioKind
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 실패 scenario가 올바르지 않습니다."
            )


@dataclass(frozen=True, slots=True)
class VolatilityOverlayPolicyOutcome:
    """One of four scenario overlays, with no fallback or winner selection."""

    policy_id: str
    status: VolatilityOverlayOutcomeStatus
    overlay_targets: tuple[VolatilityOverlayTarget, ...] = ()
    result: AllocationBacktestResult | None = None
    failure: VolatilityOverlayFailure | None = None

    def __post_init__(self) -> None:
        if self.policy_id not in VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS:
            raise InvalidVolatilityOverlayDomainError(
                "지원하지 않는 volatility overlay 정책 식별자입니다."
            )
        if not isinstance(self.overlay_targets, tuple) or any(
            not isinstance(target, VolatilityOverlayTarget) for target in self.overlay_targets
        ):
            raise InvalidVolatilityOverlayDomainError(
                "overlay targets는 VolatilityOverlayTarget tuple이어야 합니다."
            )
        scenario_kind = SCENARIO_KIND_ORDER[
            VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS.index(self.policy_id)
        ]
        if any(
            target.policy_id != self.policy_id or target.scenario_kind is not scenario_kind
            for target in self.overlay_targets
        ):
            raise InvalidVolatilityOverlayDomainError(
                "overlay target 정책·scenario가 outcome과 일치하지 않습니다."
            )
        target_dates = tuple(target.as_of_date for target in self.overlay_targets)
        if any(current <= previous for previous, current in pairwise(target_dates)):
            raise InvalidVolatilityOverlayDomainError(
                "overlay target as-of는 엄격한 오름차순이어야 합니다."
            )
        if not isinstance(self.status, VolatilityOverlayOutcomeStatus):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay outcome 상태가 올바르지 않습니다."
            )
        if self.status is VolatilityOverlayOutcomeStatus.SUCCEEDED:
            if (
                not self.overlay_targets
                or not isinstance(self.result, AllocationBacktestResult)
                or self.failure is not None
            ):
                raise InvalidVolatilityOverlayDomainError(
                    "성공 overlay outcome에는 전체 target과 backtest 결과만 있어야 합니다."
                )
            if self.result.policy_id != self.policy_id:
                raise InvalidVolatilityOverlayDomainError(
                    "overlay backtest 정책 식별자가 outcome과 일치하지 않습니다."
                )
        elif self.result is not None or not isinstance(self.failure, VolatilityOverlayFailure):
            raise InvalidVolatilityOverlayDomainError(
                "실패 overlay outcome에는 정제된 실패 정보만 있어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class VolatilityOverlayResearchTrial:
    """Separate v1 trial layered on an unchanged constrained-ERC source trial."""

    trial_id: str
    status: VolatilityOverlayResearchStatus
    executed_at: datetime
    requested_start: date
    requested_end: date
    actual_evaluation_start: date | None
    actual_evaluation_end: date | None
    source_trial: ConstrainedErcResearchTrial
    overlay_config: VolatilityOverlayConfig
    policy_outcomes: tuple[VolatilityOverlayPolicyOutcome, ...]
    config_fingerprint: str
    trial_fingerprint: str
    provenance: RiskModelLibraryProvenance
    schema: str = VOLATILITY_OVERLAY_SCHEMA
    schema_version: str = VOLATILITY_OVERLAY_SCHEMA_VERSION
    code_model_version: str = VOLATILITY_OVERLAY_CODE_MODEL_VERSION
    research_scope: str = VOLATILITY_OVERLAY_RESEARCH_SCOPE

    def __post_init__(self) -> None:
        if not isinstance(self.trial_id, str) or _TRIAL_ID_PATTERN.fullmatch(self.trial_id) is None:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay trial ID는 경로 구분자 없는 안전한 문자열이어야 합니다."
            )
        if not isinstance(self.status, VolatilityOverlayResearchStatus):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay trial 상태가 올바르지 않습니다."
            )
        if not isinstance(self.executed_at, datetime) or self.executed_at.tzinfo is None:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 실행시각은 timezone-aware datetime이어야 합니다."
            )
        if (
            type(self.requested_start) is not date
            or type(self.requested_end) is not date
            or self.requested_start > self.requested_end
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay 요청기간이 올바르지 않습니다."
            )
        if not isinstance(self.source_trial, ConstrainedErcResearchTrial):
            raise InvalidVolatilityOverlayDomainError(
                "source trial은 변경되지 않은 ConstrainedErcResearchTrial이어야 합니다."
            )
        if (
            self.requested_start != self.source_trial.requested_start
            or self.requested_end != self.source_trial.requested_end
        ):
            raise InvalidVolatilityOverlayDomainError(
                "overlay와 source Constrained ERC 요청기간이 일치해야 합니다."
            )
        if not isinstance(self.overlay_config, VolatilityOverlayConfig):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay config 타입이 올바르지 않습니다."
            )
        if not isinstance(self.policy_outcomes, tuple) or any(
            not isinstance(outcome, VolatilityOverlayPolicyOutcome)
            for outcome in self.policy_outcomes
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay policy outcomes 타입이 올바르지 않습니다."
            )
        if (
            tuple(outcome.policy_id for outcome in self.policy_outcomes)
            != VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay outcome은 고정된 네 scenario 순서여야 합니다."
            )
        self._validate_source_lineage()
        succeeded = all(
            outcome.status is VolatilityOverlayOutcomeStatus.SUCCEEDED
            for outcome in self.policy_outcomes
        )
        if (self.status is VolatilityOverlayResearchStatus.SUCCEEDED) != succeeded:
            raise InvalidVolatilityOverlayDomainError(
                "전체 overlay trial 상태가 네 scenario outcome과 일치하지 않습니다."
            )
        successful_results = tuple(
            outcome.result for outcome in self.policy_outcomes if outcome.result is not None
        )
        if successful_results:
            evaluation_dates = successful_results[0].dates
            if any(result.dates != evaluation_dates for result in successful_results[1:]):
                raise InvalidVolatilityOverlayDomainError(
                    "성공 overlay 정책의 실제 평가기간은 모두 같아야 합니다."
                )
            if (
                self.actual_evaluation_start != evaluation_dates[0]
                or self.actual_evaluation_end != evaluation_dates[-1]
            ):
                raise InvalidVolatilityOverlayDomainError(
                    "overlay trial 실제 평가기간이 성공 결과와 일치하지 않습니다."
                )
        elif self.actual_evaluation_start is not None or self.actual_evaluation_end is not None:
            raise InvalidVolatilityOverlayDomainError(
                "성공 overlay 정책이 없으면 실제 평가기간은 None이어야 합니다."
            )
        _validate_fingerprint(self.config_fingerprint, "overlay config")
        _validate_fingerprint(self.trial_fingerprint, "overlay trial")
        if not isinstance(self.provenance, RiskModelLibraryProvenance):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay library provenance가 올바르지 않습니다."
            )
        if self.provenance != self.source_trial.provenance:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay provenance는 source ERC provenance와 같아야 합니다."
            )
        if (
            self.schema != VOLATILITY_OVERLAY_SCHEMA
            or self.schema_version != VOLATILITY_OVERLAY_SCHEMA_VERSION
            or self.code_model_version != VOLATILITY_OVERLAY_CODE_MODEL_VERSION
            or self.research_scope != VOLATILITY_OVERLAY_RESEARCH_SCOPE
        ):
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay schema·model·scope 계약이 올바르지 않습니다."
            )

    def _validate_source_lineage(self) -> None:
        source_outcomes = self.source_trial.policy_outcomes[:4]
        if tuple(outcome.policy_id for outcome in source_outcomes) != (
            CONSTRAINED_ERC_SCENARIO_POLICY_IDS
        ):
            raise InvalidVolatilityOverlayDomainError(
                "source Constrained ERC scenario 순서가 올바르지 않습니다."
            )
        for index, (source, overlay) in enumerate(
            zip(source_outcomes, self.policy_outcomes, strict=True)
        ):
            scenario_kind = SCENARIO_KIND_ORDER[index]
            if overlay.policy_id != volatility_overlay_policy_id(scenario_kind):
                raise InvalidVolatilityOverlayDomainError(
                    "overlay 정책 식별자가 source scenario와 일치하지 않습니다."
                )
            if (
                source.status is ConstrainedErcOutcomeStatus.FAILED
                and overlay.status is VolatilityOverlayOutcomeStatus.SUCCEEDED
            ):
                raise InvalidVolatilityOverlayDomainError(
                    "실패한 source ERC scenario를 fallback으로 성공 처리할 수 없습니다."
                )
            source_targets = source.erc_targets
            if len(overlay.overlay_targets) > len(source_targets):
                raise InvalidVolatilityOverlayDomainError(
                    "overlay target 수가 source ERC target 수를 넘을 수 없습니다."
                )
            for source_target, overlay_target in zip(
                source_targets,
                overlay.overlay_targets,
                strict=False,
            ):
                if (
                    overlay_target.as_of_date != source_target.as_of_date
                    or overlay_target.stock_codes != source_target.stock_codes
                    or overlay_target.source_policy_id != source_target.policy_id
                    or overlay_target.scenario_kind is not source_target.scenario_kind
                    or overlay_target.risky_sleeve_weights != source_target.reconciled_weights
                    or overlay_target.source_covariance_fingerprint
                    != source_target.covariance_fingerprint
                    or overlay_target.source_solver_config_fingerprint
                    != source_target.solver_config_fingerprint
                    or overlay_target.forecast_annual_volatility
                    != Decimal(str(source_target.expected_portfolio_volatility))
                    or overlay_target.target_annual_volatility
                    != self.overlay_config.target_annual_volatility
                    or overlay_target.annual_cash_yield != self.overlay_config.annual_cash_yield
                ):
                    raise InvalidVolatilityOverlayDomainError(
                        "overlay target이 source ERC·CLI config provenance와 일치하지 않습니다."
                    )
            if overlay.status is VolatilityOverlayOutcomeStatus.SUCCEEDED:
                if len(overlay.overlay_targets) != len(source_targets):
                    raise InvalidVolatilityOverlayDomainError(
                        "성공 overlay는 source ERC target 전체를 소비해야 합니다."
                    )
                if overlay.result is None:
                    raise InvalidVolatilityOverlayDomainError(
                        "성공 overlay에는 backtest 결과가 필요합니다."
                    )
                if overlay.result.stock_codes != self.source_trial.stock_codes:
                    raise InvalidVolatilityOverlayDomainError(
                        "overlay backtest 종목 순서가 source trial과 일치해야 합니다."
                    )
                if (
                    tuple(record.execution_date for record in overlay.result.rebalances)
                    != self.source_trial.execution_dates
                ):
                    raise InvalidVolatilityOverlayDomainError(
                        "overlay 체결일은 source next-common-open 일정과 같아야 합니다."
                    )
                for target, record in zip(
                    overlay.overlay_targets,
                    overlay.result.rebalances,
                    strict=True,
                ):
                    if (
                        record.target.signal_date != target.as_of_date
                        or record.target.stock_codes != target.stock_codes
                        or record.target.policy_id != target.policy_id
                        or record.target.target_weights != target.target_weights
                        or record.target.target_equity_weight != target.target_equity_weight
                    ):
                        raise InvalidVolatilityOverlayDomainError(
                            "overlay backtest target이 exact Decimal overlay target과 "
                            "일치하지 않습니다."
                        )
                if self.source_trial.price_panel is not None:
                    first_execution = self.source_trial.execution_dates[0]
                    first_index = self.source_trial.price_panel.dates.index(first_execution)
                    if overlay.result.dates != self.source_trial.price_panel.dates[first_index:]:
                        raise InvalidVolatilityOverlayDomainError(
                            "overlay 평가일이 source 공통 가격 패널과 일치하지 않습니다."
                        )

    @property
    def stock_codes(self) -> tuple[str, ...]:
        """Expose the unchanged source universe order."""

        return self.source_trial.stock_codes

    @property
    def signal_dates(self) -> tuple[date, ...]:
        """Expose the unchanged causal source signal schedule."""

        return self.source_trial.signal_dates

    @property
    def execution_dates(self) -> tuple[date, ...]:
        """Expose the unchanged next-common-open source execution schedule."""

        return self.source_trial.execution_dates


def _validate_fingerprint(value: object, label: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise InvalidVolatilityOverlayDomainError(
            f"{label} fingerprint는 64자리 소문자 SHA-256이어야 합니다."
        )


__all__ = [
    "VolatilityOverlayFailure",
    "VolatilityOverlayOutcomeStatus",
    "VolatilityOverlayPolicyOutcome",
    "VolatilityOverlayResearchStatus",
    "VolatilityOverlayResearchTrial",
]

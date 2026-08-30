from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import cast

import pytest

from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    CovarianceScenario,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
)
from phalanx.portfolio.errors import (
    RiskModelConfigurationError,
    RiskModelNumericalError,
)

_DATES = (date(2026, 1, 2), date(2026, 1, 3))
_FINGERPRINT = "a" * 64


def _diagnostics(*, condition: float | None = 1.0) -> PsdDiagnostics:
    return PsdDiagnostics(
        minimum_eigenvalue_before=0.04,
        minimum_eigenvalue_after=0.04,
        maximum_eigenvalue_after=0.04,
        numerical_tolerance=1e-12,
        rank=1,
        condition_number=condition,
        frobenius_repair_norm=0.0,
        relative_repair_norm=0.0,
        repaired=False,
    )


def _metadata(
    kind: CovarianceScenarioKind,
) -> LedoitWolfMetadata | IewmaMetadata | DownsideStressMetadata:
    if kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF:
        return LedoitWolfMetadata(shrinkage=0.2)
    if kind in (CovarianceScenarioKind.FAST_IEWMA, CovarianceScenarioKind.SLOW_IEWMA):
        return IewmaMetadata(
            volatility_half_life=21 if kind is CovarianceScenarioKind.FAST_IEWMA else 63,
            correlation_half_life=63 if kind is CovarianceScenarioKind.FAST_IEWMA else 125,
            volatility_seed_count=20,
            correlation_observation_count=484,
            volatility_effective_sample_size=40.0,
            correlation_effective_sample_size=80.0,
            clip_threshold=4.2,
            clipped_scalar_count=0,
            correlation_psd_diagnostics=_diagnostics(),
        )
    return DownsideStressMetadata(
        downside_fraction=Decimal("0.20"),
        selected_count=2,
        cutoff_equal_weight_return=Decimal("-0.01"),
        selected_dates=tuple(reversed(_DATES)),
        selected_dates_fingerprint="b" * 64,
        shrinkage=0.3,
    )


def _scenario(kind: CovarianceScenarioKind) -> CovarianceScenario:
    return CovarianceScenario(
        kind=kind,
        stock_codes=("005930",),
        observation_dates=_DATES,
        annualized_covariance=((0.04,),),
        annualized_volatilities=(0.2,),
        correlation_matrix=((1.0,),),
        metadata=_metadata(kind),
        psd_diagnostics=_diagnostics(),
    )


def _snapshot() -> DynamicRiskModelSnapshot:
    return DynamicRiskModelSnapshot(
        as_of_date=_DATES[-1],
        consumed_start_date=_DATES[0],
        consumed_end_date=_DATES[-1],
        consumed_observation_count=2,
        stock_codes=("005930",),
        consumed_dates=_DATES,
        scenarios=tuple(_scenario(kind) for kind in SCENARIO_KIND_ORDER),
        consumed_input_fingerprint=_FINGERPRINT,
    )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"minimum_observations": 0}, "양의 정수"),
        ({"minimum_observations": 757}, "최소 관측치"),
        ({"fast_volatility_half_life": 63}, "fast IEWMA"),
        ({"slow_volatility_half_life": 125}, "slow IEWMA"),
        (
            {"fast_volatility_half_life": 63, "fast_correlation_half_life": 100},
            "fast 변동성",
        ),
        ({"fast_correlation_half_life": 126}, "fast 상관관계"),
        ({"downside_fraction": Decimal("0")}, "하방 비율"),
        ({"standardized_return_clip": float("inf")}, "clip"),
        ({"psd_relative_eigen_tolerance": 1.0}, "상대 고윳값"),
        ({"psd_absolute_eigen_tolerance": 1.0}, "절대 고윳값"),
        ({"maximum_relative_psd_repair": 1e-12}, "보정 상한"),
    ],
)
def test_config_rejects_invalid_v1_ranges(changes: dict[str, object], message: str) -> None:
    with pytest.raises(RiskModelConfigurationError, match=message):
        DynamicRiskModelConfig(**changes)  # type: ignore[arg-type]


def test_scenario_rejects_empty_and_duplicate_stock_codes() -> None:
    scenario = _scenario(CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF)

    with pytest.raises(RiskModelNumericalError, match="최소 1개"):
        replace(
            scenario,
            stock_codes=(),
            annualized_covariance=(),
            annualized_volatilities=(),
            correlation_matrix=(),
        )
    with pytest.raises(RiskModelNumericalError, match="중복"):
        replace(
            scenario,
            stock_codes=("005930", "005930"),
            annualized_covariance=((0.04, 0.0), (0.0, 0.04)),
            annualized_volatilities=(0.2, 0.2),
            correlation_matrix=((1.0, 0.0), (0.0, 1.0)),
        )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"annualized_covariance": ()}, "행 수"),
        ({"annualized_covariance": ((0.04, 0.01),)}, "N x N"),
        ({"annualized_covariance": ((float("nan"),),)}, "유한"),
        ({"annualized_covariance": ((-0.04,),)}, "음수"),
        ({"correlation_matrix": ((float("inf"),),)}, "유한"),
        ({"correlation_matrix": ((0.9,),)}, "대각"),
    ],
)
def test_scenario_rejects_bad_dimensions_and_values(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RiskModelNumericalError, match=message):
        replace(_scenario(CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF), **changes)


def test_scenario_rejects_asymmetric_covariance() -> None:
    scenario = CovarianceScenario(
        kind=CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
        stock_codes=("005930", "000660"),
        observation_dates=_DATES,
        annualized_covariance=((0.04, 0.01), (0.01, 0.09)),
        annualized_volatilities=(0.2, 0.3),
        correlation_matrix=((1.0, 0.2), (0.2, 1.0)),
        metadata=LedoitWolfMetadata(shrinkage=0.1),
        psd_diagnostics=replace(_diagnostics(), rank=2),
    )

    with pytest.raises(RiskModelNumericalError, match="대칭"):
        replace(scenario, annualized_covariance=((0.04, 0.01), (0.02, 0.09)))


def test_scenario_rejects_metadata_kind_mismatch() -> None:
    with pytest.raises(RiskModelNumericalError, match="metadata"):
        replace(
            _scenario(CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF),
            metadata=_metadata(CovarianceScenarioKind.FAST_IEWMA),
        )


def test_snapshot_requires_exact_fixed_scenario_order_without_duplicates() -> None:
    snapshot = _snapshot()

    with pytest.raises(RiskModelNumericalError, match="고정 순서"):
        replace(snapshot, scenarios=snapshot.scenarios[:-1])
    with pytest.raises(RiskModelNumericalError, match="고정 순서"):
        replace(snapshot, scenarios=tuple(reversed(snapshot.scenarios)))
    with pytest.raises(RiskModelNumericalError, match="고정 순서"):
        replace(snapshot, scenarios=(snapshot.scenarios[0],) * 4)


def test_snapshot_rejects_bad_dates_and_observation_count() -> None:
    snapshot = _snapshot()

    with pytest.raises(RiskModelNumericalError, match="종료일"):
        replace(snapshot, as_of_date=_DATES[0])
    with pytest.raises(RiskModelNumericalError, match="관측치 수"):
        replace(snapshot, consumed_observation_count=3)
    with pytest.raises(RiskModelNumericalError, match="오름차순"):
        replace(snapshot, consumed_dates=tuple(reversed(_DATES)))


def test_get_scenario_is_explicit_and_preserves_registration_order() -> None:
    snapshot = _snapshot()

    selected = snapshot.get_scenario(CovarianceScenarioKind.SLOW_IEWMA)

    assert selected.kind is CovarianceScenarioKind.SLOW_IEWMA
    assert selected.stock_codes == ("005930",)


def test_models_are_frozen_and_condition_none_is_valid() -> None:
    diagnostics = _diagnostics(condition=None)
    snapshot = _snapshot()

    assert diagnostics.condition_number is None
    with pytest.raises(FrozenInstanceError):
        snapshot.as_of_date = date(2026, 1, 4)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.scenarios[0].annualized_covariance = ((1.0,),)  # type: ignore[misc]


def test_downside_selected_dates_keep_rank_order_not_calendar_order() -> None:
    metadata = cast(
        DownsideStressMetadata,
        _metadata(CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF),
    )

    assert metadata.selected_dates == tuple(reversed(_DATES))


def test_observation_dates_reject_duplicate_and_reverse_order() -> None:
    scenario = _scenario(CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF)
    duplicate = (_DATES[0], _DATES[0])
    reverse = tuple(reversed(_DATES))

    with pytest.raises(RiskModelNumericalError, match="오름차순"):
        replace(scenario, observation_dates=duplicate)
    with pytest.raises(RiskModelNumericalError, match="오름차순"):
        replace(scenario, observation_dates=reverse)


def test_psd_diagnostics_reject_nonfinite_and_invalid_rank() -> None:
    with pytest.raises(RiskModelNumericalError, match="유한"):
        replace(_diagnostics(), maximum_eigenvalue_after=float("nan"))
    with pytest.raises(RiskModelNumericalError, match="rank"):
        replace(_diagnostics(), rank=-1)


def test_dates_fixture_is_strictly_increasing() -> None:
    assert _DATES[1] - _DATES[0] == timedelta(days=1)

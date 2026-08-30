from __future__ import annotations

import numpy as np
import pytest

from phalanx.domain import DynamicRiskModelConfig
from phalanx.portfolio.dynamic_risk_model import repair_numerical_psd
from phalanx.portfolio.errors import (
    MateriallyIndefiniteCovarianceError,
    RiskModelQualityError,
)


def test_normal_psd_input_is_not_unnecessarily_changed() -> None:
    matrix = np.asarray(((2.0, 0.25), (0.25, 1.0)), dtype=np.float64)

    repaired, diagnostics = repair_numerical_psd(matrix, DynamicRiskModelConfig())

    assert np.array_equal(repaired, matrix)
    assert diagnostics.repaired is False
    assert diagnostics.frobenius_repair_norm == 0.0
    assert diagnostics.relative_repair_norm == 0.0
    assert diagnostics.rank == 2
    assert diagnostics.condition_number is not None


def test_tiny_negative_eigenvalue_is_projected_to_zero_only() -> None:
    matrix = np.asarray(((1.0, 0.0), (0.0, -1e-12)), dtype=np.float64)

    repaired, diagnostics = repair_numerical_psd(matrix, DynamicRiskModelConfig())

    assert np.linalg.eigvalsh(repaired)[0] >= 0
    assert repaired[0, 0] == pytest.approx(1.0)
    assert repaired[1, 1] == pytest.approx(0.0)
    assert diagnostics.repaired is True
    assert diagnostics.rank == 1
    assert diagnostics.condition_number is None
    assert diagnostics.minimum_eigenvalue_before == pytest.approx(-1e-12)
    assert diagnostics.frobenius_repair_norm == pytest.approx(1e-12)


def test_material_negative_eigenvalue_is_rejected() -> None:
    matrix = np.asarray(((1.0, 0.0), (0.0, -1e-4)), dtype=np.float64)

    with pytest.raises(MateriallyIndefiniteCovarianceError, match="음의 고윳값"):
        repair_numerical_psd(matrix, DynamicRiskModelConfig())


def test_repair_result_is_symmetric_psd_and_idempotent() -> None:
    matrix = np.asarray(((1.0, 1.0 + 1e-12), (1.0 + 1e-12, 1.0)), dtype=np.float64)

    repaired, first_diagnostics = repair_numerical_psd(matrix, DynamicRiskModelConfig())
    second, second_diagnostics = repair_numerical_psd(repaired, DynamicRiskModelConfig())

    np.testing.assert_allclose(repaired, repaired.T, atol=0.0)
    assert np.linalg.eigvalsh(repaired)[0] >= -first_diagnostics.numerical_tolerance
    np.testing.assert_allclose(second, repaired, atol=1e-15)
    assert second_diagnostics.relative_repair_norm <= 1e-15


def test_zero_matrix_remains_zero_without_artificial_ridge() -> None:
    matrix = np.zeros((3, 3), dtype=np.float64)

    repaired, diagnostics = repair_numerical_psd(matrix, DynamicRiskModelConfig())

    assert np.array_equal(repaired, matrix)
    assert diagnostics.rank == 0
    assert diagnostics.condition_number is None
    assert diagnostics.repaired is False


def test_correlation_repair_restores_unit_diagonal_and_psd() -> None:
    matrix = np.asarray(((1.0, 1.0 + 1e-12), (1.0 + 1e-12, 1.0)), dtype=np.float64)

    repaired, diagnostics = repair_numerical_psd(
        matrix,
        DynamicRiskModelConfig(),
        correlation=True,
    )

    np.testing.assert_allclose(np.diag(repaired), (1.0, 1.0), atol=0.0)
    np.testing.assert_allclose(repaired, repaired.T, atol=0.0)
    assert np.linalg.eigvalsh(repaired)[0] >= -diagnostics.numerical_tolerance
    assert np.max(np.abs(repaired)) <= 1.0 + 1e-12


def test_repair_above_relative_quality_ceiling_is_rejected() -> None:
    config = DynamicRiskModelConfig(
        psd_absolute_eigen_tolerance=1e-8,
        maximum_relative_psd_repair=1e-4,
    )
    matrix = np.asarray(((1e-12, 0.0), (0.0, -5e-9)), dtype=np.float64)

    with pytest.raises(RiskModelQualityError, match="품질 상한"):
        repair_numerical_psd(matrix, config)


def test_rank_and_condition_are_reported_only_for_numerically_full_rank() -> None:
    full = np.asarray(((4.0, 0.0), (0.0, 1.0)), dtype=np.float64)
    singular = np.asarray(((1.0, 1.0), (1.0, 1.0)), dtype=np.float64)

    _, full_diagnostics = repair_numerical_psd(full, DynamicRiskModelConfig())
    _, singular_diagnostics = repair_numerical_psd(singular, DynamicRiskModelConfig())

    assert full_diagnostics.rank == 2
    assert full_diagnostics.condition_number == pytest.approx(4.0)
    assert singular_diagnostics.rank == 1
    assert singular_diagnostics.condition_number is None

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from phalanx.domain import AlignedReturnMatrix
from phalanx.portfolio.errors import InvalidAlignedReturnMatrixError


def _matrix(**overrides: object) -> AlignedReturnMatrix:
    values: dict[str, object] = {
        "stock_codes": ("005930", "000660"),
        "dates": (date(2026, 8, 4), date(2026, 8, 5)),
        "values": (
            (Decimal("0.1"), Decimal("-0.2")),
            (Decimal("0.05"), Decimal("0.3")),
        ),
    }
    values.update(overrides)
    return AlignedReturnMatrix(**values)  # type: ignore[arg-type]


def test_aligned_return_matrix_preserves_decimal_values_and_is_frozen() -> None:
    matrix = _matrix()

    assert matrix.stock_codes == ("005930", "000660")
    assert matrix.values[0][0] == Decimal("0.1")
    assert all(isinstance(value, Decimal) for row in matrix.values for value in row)
    with pytest.raises(FrozenInstanceError):
        matrix.dates = ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"stock_codes": ("005930", "005930")}, "중복"),
        (
            {"dates": (date(2026, 8, 4), date(2026, 8, 4))},
            "중복",
        ),
        (
            {"dates": (date(2026, 8, 5), date(2026, 8, 4))},
            "오름차순",
        ),
        (
            {"values": ((Decimal("0.1"), Decimal("0.2")),)},
            "행 수",
        ),
        (
            {
                "values": (
                    (Decimal("0.1"),),
                    (Decimal("0.2"),),
                )
            },
            "열 수",
        ),
        (
            {
                "values": (
                    (Decimal("NaN"), Decimal("0.2")),
                    (Decimal("0.1"), Decimal("0.2")),
                )
            },
            "유한한 Decimal",
        ),
        (
            {
                "values": (
                    (0.1, Decimal("0.2")),
                    (Decimal("0.1"), Decimal("0.2")),
                )
            },
            "유한한 Decimal",
        ),
    ),
)
def test_aligned_return_matrix_rejects_invalid_dimensions_dates_codes_and_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InvalidAlignedReturnMatrixError, match=message):
        _matrix(**overrides)

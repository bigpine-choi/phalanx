from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import (
    MAX_PREC,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_UP,
    BasicContext,
    Context,
    Decimal,
    DefaultContext,
    DivisionByZero,
    ExtendedContext,
    InvalidOperation,
    Overflow,
    getcontext,
    setcontext,
)
from importlib.util import resolve_name
from inspect import Parameter, Signature, signature
from pathlib import Path
from threading import Barrier, get_ident

import numpy as np
import pytest

import phalanx.portfolio.self_financing as self_financing_module
from phalanx.portfolio.errors import AllocationSelfFinancingError
from phalanx.portfolio.self_financing import (
    SelfFinancingTransitionError,
    SelfFinancingTransitionInput,
    SelfFinancingTransitionResult,
    apply_fractional_self_financing_transition,
)

ROOT = Path(__file__).resolve().parents[1]

_EXPECTED_MIXED_RESULT = SelfFinancingTransitionResult(
    quantities_after=(Decimal("3.2"), Decimal("1.6")),
    actual_values_after=(Decimal(32), Decimal(16)),
    actual_stock_total_after=Decimal(48),
    buy_notional=Decimal(16),
    sell_notional=Decimal(48),
    buy_gross_turnover=Decimal("0.16"),
    sell_gross_turnover=Decimal("0.48"),
    transaction_cost=Decimal(20),
    transaction_cost_rate=Decimal("0.2"),
    pre_trade_nav=Decimal(100),
    post_trade_nav=Decimal(80),
    cash_after=Decimal(32),
    realized_weights=(Decimal("0.4"), Decimal("0.2")),
    realized_cash_weight=Decimal("0.4"),
)

_EXPECTED_ANCHOR_RESULT = SelfFinancingTransitionResult(
    quantities_after=(
        Decimal("0.16666666666666666666666666666666666666666666666667"),
        Decimal("0.16666666666666666666666666666666666666666666666666"),
        Decimal(0),
    ),
    actual_values_after=(
        Decimal("0.50000000000000000000000000000000000000000000000001"),
        Decimal("0.49999999999999999999999999999999999999999999999998"),
        Decimal(0),
    ),
    actual_stock_total_after=Decimal(
        "0.99999999999999999999999999999999999999999999999999"
    ),
    buy_notional=Decimal("1.0"),
    sell_notional=Decimal(0),
    buy_gross_turnover=Decimal("1.0"),
    sell_gross_turnover=Decimal(0),
    transaction_cost=Decimal("0.0"),
    transaction_cost_rate=Decimal("0.0"),
    pre_trade_nav=Decimal(1),
    post_trade_nav=Decimal(1),
    cash_after=Decimal("1E-50"),
    realized_weights=(
        Decimal("0.50000000000000000000000000000000000000000000000001"),
        Decimal("0.49999999999999999999999999999999999999999999999998"),
        Decimal(0),
    ),
    realized_cash_weight=Decimal("1E-50"),
)


def _transition_input(**overrides: object) -> SelfFinancingTransitionInput:
    values: dict[str, object] = {
        "current_quantities": (Decimal(8), Decimal(0)),
        "cash_before": Decimal(20),
        "valuation_prices": (Decimal(10), Decimal(10)),
        "target_weights": (Decimal("0.4"), Decimal("0.2")),
        "target_equity_weight": Decimal("0.6"),
        "buy_cost_rate": Decimal("0.5"),
        "sell_cost_rate": Decimal("0.25"),
    }
    values.update(overrides)
    return SelfFinancingTransitionInput(**values)  # type: ignore[arg-type]


def _anchor_transition_input() -> SelfFinancingTransitionInput:
    return SelfFinancingTransitionInput(
        current_quantities=(Decimal(0), Decimal(0), Decimal(0)),
        cash_before=Decimal(1),
        valuation_prices=(Decimal(3), Decimal(3), Decimal(11)),
        target_weights=(Decimal("0.5"), Decimal("0.5"), Decimal(0)),
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )


def _trusted_transition_input(**overrides: object) -> SelfFinancingTransitionInput:
    values: dict[str, object] = {
        "current_quantities": (Decimal(8), Decimal(0)),
        "cash_before": Decimal(20),
        "valuation_prices": (Decimal(10), Decimal(10)),
        "target_weights": (Decimal("0.4"), Decimal("0.2")),
        "target_equity_weight": Decimal("0.6"),
        "buy_cost_rate": Decimal("0.5"),
        "sell_cost_rate": Decimal("0.25"),
    }
    values.update(overrides)
    return SelfFinancingTransitionInput._from_validated_values(  # type: ignore[arg-type]
        **values
    )


def _context_state(context: Context) -> tuple[object, ...]:
    return (
        context.prec,
        context.rounding,
        context.Emin,
        context.Emax,
        context.capitals,
        context.clamp,
        dict(context.traps),
        dict(context.flags),
    )


def _restore_context(target: Context, snapshot: Context) -> None:
    target.prec = snapshot.prec
    target.rounding = snapshot.rounding
    target.Emin = snapshot.Emin
    target.Emax = snapshot.Emax
    target.capitals = snapshot.capitals
    target.clamp = snapshot.clamp
    for signal in target.traps:
        target.traps[signal] = snapshot.traps[signal]
        target.flags[signal] = snapshot.flags[signal]


def _direct_imports_from_tree(
    tree: ast.AST,
    module_name: str,
) -> set[tuple[str, str | None, str | None]]:
    package = module_name.rpartition(".")[0]
    imports: set[tuple[str, str | None, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update((alias.name, None, alias.asname) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is None:
                    raise AssertionError("absolute ImportFrom has no module")
                resolved_module = node.module
                imports.update(
                    (resolved_module, alias.name, alias.asname) for alias in node.names
                )
            elif node.module is not None:
                resolved_module = resolve_name(
                    f"{'.' * node.level}{node.module}",
                    package,
                )
                imports.update(
                    (resolved_module, alias.name, alias.asname) for alias in node.names
                )
            else:
                for alias in node.names:
                    resolved_module = resolve_name(
                        f"{'.' * node.level}{alias.name}",
                        package,
                    )
                    imports.add((resolved_module, None, alias.asname))
    return imports


def _direct_imports(
    path: Path,
    module_name: str,
) -> set[tuple[str, str | None, str | None]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _direct_imports_from_tree(tree, module_name)


def test_public_kernel_returns_the_exact_mixed_transition() -> None:
    transition_input = _transition_input()

    result = apply_fractional_self_financing_transition(transition_input)

    assert result == _EXPECTED_MIXED_RESULT
    assert result.actual_values_after == tuple(
        quantity * price
        for quantity, price in zip(
            result.quantities_after,
            transition_input.valuation_prices,
            strict=True,
        )
    )
    assert result.post_trade_nav == result.pre_trade_nav - result.transaction_cost
    assert result.cash_after == result.post_trade_nav - result.actual_stock_total_after
    assert sum(result.realized_weights, Decimal(0)) + result.realized_cash_weight == Decimal(1)


def test_public_input_and_result_are_frozen_slotted_and_leave_inputs_unchanged() -> None:
    transition_input = _transition_input()
    input_snapshot = tuple(
        getattr(transition_input, field.name)
        for field in fields(SelfFinancingTransitionInput)
    )

    result = apply_fractional_self_financing_transition(transition_input)

    with pytest.raises(FrozenInstanceError):
        transition_input.cash_before = Decimal(0)
    with pytest.raises(FrozenInstanceError):
        result.cash_after = Decimal(0)
    assert not hasattr(transition_input, "__dict__")
    assert not hasattr(result, "__dict__")
    assert tuple(
        getattr(transition_input, field.name)
        for field in fields(SelfFinancingTransitionInput)
    ) == input_snapshot
    assert transition_input.current_quantities == (Decimal(8), Decimal(0))
    assert transition_input.valuation_prices == (Decimal(10), Decimal(10))
    assert transition_input.target_weights == (Decimal("0.4"), Decimal("0.2"))


def test_public_contract_shape_exposes_only_immutable_decimal_values() -> None:
    assert tuple(field.name for field in fields(SelfFinancingTransitionInput)) == (
        "current_quantities",
        "cash_before",
        "valuation_prices",
        "target_weights",
        "target_equity_weight",
        "buy_cost_rate",
        "sell_cost_rate",
    )
    assert tuple(field.type for field in fields(SelfFinancingTransitionInput)) == (
        "tuple[Decimal, ...]",
        "Decimal",
        "tuple[Decimal, ...]",
        "tuple[Decimal, ...]",
        "Decimal",
        "Decimal",
        "Decimal",
    )
    assert tuple(field.name for field in fields(SelfFinancingTransitionResult)) == (
        "quantities_after",
        "actual_values_after",
        "actual_stock_total_after",
        "buy_notional",
        "sell_notional",
        "buy_gross_turnover",
        "sell_gross_turnover",
        "transaction_cost",
        "transaction_cost_rate",
        "pre_trade_nav",
        "post_trade_nav",
        "cash_after",
        "realized_weights",
        "realized_cash_weight",
    )
    assert set(field.type for field in fields(SelfFinancingTransitionResult)) == {
        "Decimal",
        "tuple[Decimal, ...]",
    }

    kernel_signature = signature(apply_fractional_self_financing_transition)
    assert kernel_signature.return_annotation == "SelfFinancingTransitionResult"
    assert tuple(kernel_signature.parameters) == ("transition_input",)
    parameter = kernel_signature.parameters["transition_input"]
    assert parameter.annotation == "SelfFinancingTransitionInput"
    assert parameter.default is Signature.empty
    assert parameter.kind is Parameter.POSITIONAL_OR_KEYWORD


@pytest.mark.parametrize(
    "overrides",
    (
        pytest.param({"current_quantities": []}, id="mutable-quantities"),
        pytest.param({"valuation_prices": [Decimal(10), Decimal(10)]}, id="mutable-prices"),
        pytest.param({"target_weights": [Decimal("0.4"), Decimal("0.2")]}, id="mutable-weights"),
        pytest.param({"current_quantities": ()}, id="empty-quantities"),
        pytest.param({"current_quantities": (Decimal(8),)}, id="quantity-price-mismatch"),
        pytest.param({"target_weights": (Decimal("0.6"),)}, id="target-price-mismatch"),
        pytest.param({"cash_before": True}, id="bool-cash"),
        pytest.param({"cash_before": 20.0}, id="float-cash"),
        pytest.param({"cash_before": np.float64(20)}, id="numpy-cash"),
        pytest.param({"cash_before": Decimal("NaN")}, id="nonfinite-cash"),
        pytest.param({"cash_before": Decimal(-1)}, id="negative-cash"),
        pytest.param({"current_quantities": (True, Decimal(0))}, id="bool-quantity"),
        pytest.param({"current_quantities": (8.0, Decimal(0))}, id="float-quantity"),
        pytest.param(
            {"current_quantities": (np.float64(8), Decimal(0))},
            id="numpy-quantity",
        ),
        pytest.param({"current_quantities": (date(2026, 1, 1), Decimal(0))}, id="date"),
        pytest.param({"current_quantities": (lambda: None, Decimal(0))}, id="callback"),
        pytest.param({"current_quantities": (object(), Decimal(0))}, id="client-provider"),
        pytest.param(
            {"current_quantities": (Decimal("Infinity"), Decimal(0))},
            id="nonfinite-quantity",
        ),
        pytest.param(
            {"current_quantities": (Decimal(-1), Decimal(0))},
            id="negative-quantity",
        ),
        pytest.param({"valuation_prices": (Decimal(0), Decimal(10))}, id="zero-price"),
        pytest.param(
            {"valuation_prices": (Decimal("NaN"), Decimal(10))},
            id="nonfinite-price",
        ),
        pytest.param(
            {"target_weights": (Decimal("0.3"), Decimal("0.2"))},
            id="target-sum",
        ),
        pytest.param(
            {"target_weights": (Decimal("-0.1"), Decimal("0.7"))},
            id="negative-weight",
        ),
        pytest.param({"target_equity_weight": Decimal(0)}, id="zero-equity"),
        pytest.param({"target_equity_weight": 0.6}, id="float-equity"),
        pytest.param({"buy_cost_rate": Decimal("-0.1")}, id="negative-buy-cost"),
        pytest.param({"buy_cost_rate": Decimal(1)}, id="unit-buy-cost"),
        pytest.param({"sell_cost_rate": True}, id="bool-sell-cost"),
        pytest.param({"sell_cost_rate": Decimal("NaN")}, id="nonfinite-sell-cost"),
    ),
)
def test_public_input_rejects_mutable_provider_or_non_decimal_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SelfFinancingTransitionError):
        _transition_input(**overrides)


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    (
        pytest.param(
            {"current_quantities": []},
            "current_quantities은 Decimal tuple이어야 합니다.",
            id="mutable-quantities",
        ),
        pytest.param(
            {"valuation_prices": [Decimal(10), Decimal(10)]},
            "valuation_prices은 Decimal tuple이어야 합니다.",
            id="mutable-prices",
        ),
        pytest.param(
            {"target_weights": [Decimal("0.4"), Decimal("0.2")]},
            "target_weights은 Decimal tuple이어야 합니다.",
            id="mutable-weights",
        ),
        pytest.param(
            {"current_quantities": ()},
            "자기금융 전환에는 최소 1개 종목이 필요합니다.",
            id="empty-quantities",
        ),
        pytest.param(
            {"current_quantities": (Decimal(8),)},
            "보유수량과 평가가격의 종목 수가 일치하지 않습니다.",
            id="quantity-price-mismatch",
        ),
        pytest.param(
            {"target_weights": (Decimal("0.6"),)},
            "목표가치와 체결가격의 종목 수가 일치하지 않습니다.",
            id="target-price-mismatch",
        ),
        pytest.param(
            {"current_quantities": (8.0, Decimal(0))},
            "current_quantities은 Decimal 값만 포함해야 합니다.",
            id="float-quantity",
        ),
        pytest.param(
            {"valuation_prices": (10.0, Decimal(10))},
            "valuation_prices은 Decimal 값만 포함해야 합니다.",
            id="float-price",
        ),
        pytest.param(
            {"target_weights": (0.4, Decimal("0.2"))},
            "target_weights은 Decimal 값만 포함해야 합니다.",
            id="float-weight",
        ),
        pytest.param(
            {"cash_before": 20.0},
            "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다.",
            id="float-cash",
        ),
        pytest.param(
            {"cash_before": Decimal("NaN")},
            "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다.",
            id="nan-cash",
        ),
        pytest.param(
            {"cash_before": Decimal(-1)},
            "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다.",
            id="negative-cash",
        ),
        pytest.param(
            {"current_quantities": (Decimal("NaN"), Decimal(0))},
            "보유수량은 0 이상의 유한한 Decimal이어야 합니다.",
            id="nan-quantity",
        ),
        pytest.param(
            {"current_quantities": (Decimal(-1), Decimal(0))},
            "보유수량은 0 이상의 유한한 Decimal이어야 합니다.",
            id="negative-quantity",
        ),
        pytest.param(
            {"valuation_prices": (Decimal("NaN"), Decimal(10))},
            "평가가격은 양의 유한한 Decimal이어야 합니다.",
            id="nan-price",
        ),
        pytest.param(
            {"valuation_prices": (Decimal(0), Decimal(10))},
            "평가가격은 양의 유한한 Decimal이어야 합니다.",
            id="zero-price",
        ),
        pytest.param(
            {"valuation_prices": (Decimal(-1), Decimal(10))},
            "평가가격은 양의 유한한 Decimal이어야 합니다.",
            id="negative-price",
        ),
        pytest.param(
            {"target_weights": (Decimal("NaN"), Decimal("0.2"))},
            "목표비중은 0 이상의 유한한 Decimal이어야 합니다.",
            id="nan-weight",
        ),
        pytest.param(
            {"target_weights": (Decimal("-0.1"), Decimal("0.7"))},
            "목표비중은 0 이상의 유한한 Decimal이어야 합니다.",
            id="negative-weight",
        ),
        pytest.param(
            {"target_equity_weight": 0.6},
            "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.",
            id="float-equity",
        ),
        pytest.param(
            {"target_equity_weight": Decimal("NaN")},
            "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.",
            id="nan-equity",
        ),
        pytest.param(
            {"target_equity_weight": Decimal(-1)},
            "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.",
            id="negative-equity",
        ),
        pytest.param(
            {"target_equity_weight": Decimal(0)},
            "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.",
            id="zero-equity",
        ),
        pytest.param(
            {"target_equity_weight": Decimal("1.1")},
            "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.",
            id="above-one-equity",
        ),
        pytest.param(
            {"buy_cost_rate": 0.5},
            "매수비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="float-buy-cost",
        ),
        pytest.param(
            {"buy_cost_rate": Decimal("NaN")},
            "매수비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="nan-buy-cost",
        ),
        pytest.param(
            {"buy_cost_rate": Decimal("-0.1")},
            "매수비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="negative-buy-cost",
        ),
        pytest.param(
            {"buy_cost_rate": Decimal(1)},
            "매수비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="unit-buy-cost",
        ),
        pytest.param(
            {"buy_cost_rate": Decimal("1.1")},
            "매수비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="above-one-buy-cost",
        ),
        pytest.param(
            {"sell_cost_rate": 0.25},
            "매도비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="float-sell-cost",
        ),
        pytest.param(
            {"sell_cost_rate": Decimal("NaN")},
            "매도비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="nan-sell-cost",
        ),
        pytest.param(
            {"sell_cost_rate": Decimal("-0.1")},
            "매도비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="negative-sell-cost",
        ),
        pytest.param(
            {"sell_cost_rate": Decimal(1)},
            "매도비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="unit-sell-cost",
        ),
        pytest.param(
            {"sell_cost_rate": Decimal("1.1")},
            "매도비용률은 0 이상 1 미만의 유한한 Decimal이어야 합니다.",
            id="above-one-sell-cost",
        ),
    ),
)
def test_trusted_constructor_rejects_every_non_sum_contract_violation(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(SelfFinancingTransitionError) as caught:
        _trusted_transition_input(**overrides)

    assert str(caught.value) == expected_message
    assert caught.value.__cause__ is None


def test_trusted_constructor_skips_only_exact_target_sum_and_preserves_raw_values() -> None:
    target_weights = (Decimal("0.444"), Decimal("0.555"))

    trusted = _trusted_transition_input(
        target_weights=target_weights,
        target_equity_weight=Decimal(1),
    )

    assert trusted.target_weights is target_weights
    with pytest.raises(SelfFinancingTransitionError) as caught:
        SelfFinancingTransitionInput(
            current_quantities=trusted.current_quantities,
            cash_before=trusted.cash_before,
            valuation_prices=trusted.valuation_prices,
            target_weights=trusted.target_weights,
            target_equity_weight=trusted.target_equity_weight,
            buy_cost_rate=trusted.buy_cost_rate,
            sell_cost_rate=trusted.sell_cost_rate,
        )
    assert str(caught.value) == "목표비중 합계는 목표 주식비중과 정확히 일치해야 합니다."


def test_trusted_constructor_retains_downstream_negative_residual_validation() -> None:
    transition_input = _trusted_transition_input(
        target_weights=(Decimal("0.7"), Decimal(0)),
        target_equity_weight=Decimal("0.6"),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )

    with pytest.raises(SelfFinancingTransitionError) as caught:
        apply_fractional_self_financing_transition(transition_input)

    assert str(caught.value) == "목표 종목가치는 0 이상의 유한한 Decimal이어야 합니다."


@pytest.mark.parametrize(
    "zero",
    (
        pytest.param(Decimal(0), id="positive-zero"),
        pytest.param(Decimal("-0"), id="negative-zero"),
        pytest.param(Decimal((0, (0, 0, 0), 73)), id="encoded-zero"),
        pytest.param(Decimal((0, (0,), MAX_PREC)), id="extreme-positive-exponent-zero"),
        pytest.param(Decimal((0, (0,), -MAX_PREC)), id="extreme-negative-exponent-zero"),
    ),
)
def test_exact_target_sum_treats_every_zero_encoding_as_neutral(zero: Decimal) -> None:
    transition_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(0), Decimal(0)),
        cash_before=Decimal(1),
        valuation_prices=(Decimal(1), Decimal(1)),
        target_weights=(Decimal(1), zero),
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )

    result = apply_fractional_self_financing_transition(transition_input)

    assert transition_input.target_weights[1].as_tuple() == zero.as_tuple()
    assert result.quantities_after == (Decimal(1), Decimal(0))
    assert result.realized_weights == (Decimal(1), Decimal(0))
    assert result.cash_after == Decimal(0)


@pytest.mark.parametrize(
    "target_weights",
    (
        pytest.param(
            (Decimal(1), Decimal((0, (1,), -MAX_PREC))),
            id="precision-above-platform-limit",
        ),
        pytest.param(
            (Decimal((0, (1,), MAX_PREC)), Decimal(0)),
            id="positive-exponent-outside-kernel-range",
        ),
        pytest.param(
            (Decimal("1E+999999"), Decimal("1E-999999")),
            id="precision-cap-within-kernel-range",
        ),
        pytest.param(
            (Decimal("0.5"), Decimal("1E-1000050")),
            id="precision-outside-kernel-range",
        ),
    ),
)
def test_exact_target_sum_rejects_unreconcilable_nonzero_terms_with_typed_error(
    target_weights: tuple[Decimal, ...],
) -> None:
    original_state = _context_state(getcontext())

    with pytest.raises(SelfFinancingTransitionError) as caught:
        _transition_input(
            current_quantities=(Decimal(0), Decimal(0)),
            cash_before=Decimal(1),
            valuation_prices=(Decimal(1), Decimal(1)),
            target_weights=target_weights,
            target_equity_weight=Decimal(1),
            buy_cost_rate=Decimal(0),
            sell_cost_rate=Decimal(0),
        )

    assert str(caught.value) == "목표비중 합계를 유한한 Decimal로 정확히 계산하지 못했습니다."
    assert caught.value.__cause__ is None
    assert _context_state(getcontext()) == original_state


def test_exact_target_sum_rejects_a_lone_unrepresentable_nonzero_term() -> None:
    value = Decimal((0, (1,), -MAX_PREC))

    with pytest.raises(SelfFinancingTransitionError) as caught:
        SelfFinancingTransitionInput(
            current_quantities=(Decimal(0),),
            cash_before=Decimal(1),
            valuation_prices=(Decimal(1),),
            target_weights=(value,),
            target_equity_weight=value,
            buy_cost_rate=Decimal(0),
            sell_cost_rate=Decimal(0),
        )

    assert str(caught.value) == "목표비중 합계를 유한한 Decimal로 정확히 계산하지 못했습니다."
    assert caught.value.__cause__ is None


def test_public_kernel_rejects_non_contract_objects() -> None:
    for value in (object(), lambda: None, date(2026, 1, 1)):
        with pytest.raises(SelfFinancingTransitionError, match="SelfFinancingTransitionInput"):
            apply_fractional_self_financing_transition(value)  # type: ignore[arg-type]


def test_fixed_point_cycle_and_iteration_exhaustion_are_naturally_fail_closed() -> None:
    cycle_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(0), Decimal(0)),
        cash_before=Decimal("0.1"),
        valuation_prices=(Decimal(1), Decimal(1)),
        target_weights=(Decimal("0.1"), Decimal("0.1")),
        target_equity_weight=Decimal("0.2"),
        buy_cost_rate=Decimal("0.4"),
        sell_cost_rate=Decimal(0),
    )
    exhaustion_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(0),),
        cash_before=Decimal(1),
        valuation_prices=(Decimal(1),),
        target_weights=(Decimal(1),),
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal("0.9"),
        sell_cost_rate=Decimal(0),
    )

    with pytest.raises(SelfFinancingTransitionError) as cycle_error:
        apply_fractional_self_financing_transition(cycle_input)
    with pytest.raises(SelfFinancingTransitionError) as exhaustion_error:
        apply_fractional_self_financing_transition(exhaustion_input)

    assert str(cycle_error.value) == "비대칭 거래비용 자기금융 계산이 순환하여 수렴하지 않았습니다."
    assert str(exhaustion_error.value) == (
        "비대칭 거래비용 자기금융 계산이 허용 횟수 안에 수렴하지 않았습니다."
    )


def test_zero_nav_and_cost_infeasibility_fail_with_typed_exact_errors() -> None:
    zero_nav_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(0),),
        cash_before=Decimal(0),
        valuation_prices=(Decimal(1),),
        target_weights=(Decimal(1),),
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal(0),
        sell_cost_rate=Decimal(0),
    )
    infeasible_cost_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(1), Decimal(0)),
        cash_before=Decimal(0),
        valuation_prices=(Decimal(1), Decimal(1)),
        target_weights=(Decimal(0), Decimal(1)),
        target_equity_weight=Decimal(1),
        buy_cost_rate=Decimal("0.9"),
        sell_cost_rate=Decimal("0.9"),
    )

    with pytest.raises(SelfFinancingTransitionError) as zero_nav_error:
        apply_fractional_self_financing_transition(zero_nav_input)
    with pytest.raises(SelfFinancingTransitionError) as infeasible_cost_error:
        apply_fractional_self_financing_transition(infeasible_cost_input)

    assert str(zero_nav_error.value) == "자기금융 체결 전 NAV는 양의 유한한 Decimal이어야 합니다."
    assert zero_nav_error.value.as_of_date is None
    assert str(infeasible_cost_error.value) == (
        "거래비용 차감 후 NAV가 0 이하이므로 자기금융 체결이 불가능합니다."
    )
    assert infeasible_cost_error.value.as_of_date is None


def test_fully_invested_anchor_is_last_positive_and_trailing_zero_stays_zero() -> None:
    transition_input = _anchor_transition_input()

    first = apply_fractional_self_financing_transition(transition_input)
    second = apply_fractional_self_financing_transition(transition_input)

    assert first == _EXPECTED_ANCHOR_RESULT
    assert first == second
    assert first.quantities_after == (
        Decimal("0.16666666666666666666666666666666666666666666666667"),
        Decimal("0.16666666666666666666666666666666666666666666666666"),
        Decimal(0),
    )
    assert first.actual_values_after == (
        Decimal("0.50000000000000000000000000000000000000000000000001"),
        Decimal("0.49999999999999999999999999999999999999999999999998"),
        Decimal(0),
    )
    assert first.realized_weights[-1] == Decimal(0)
    assert first.actual_stock_total_after == Decimal(
        "0.99999999999999999999999999999999999999999999999999"
    )
    assert first.cash_after == Decimal("1E-50")
    assert sum(first.realized_weights, Decimal(0)) + first.realized_cash_weight == Decimal(1)


def test_failed_underflow_does_not_mutate_input_or_leak_flags_to_the_next_call() -> None:
    underflow_input = SelfFinancingTransitionInput(
        current_quantities=(Decimal(0), Decimal(0)),
        cash_before=Decimal(1),
        valuation_prices=(
            Decimal((0, (1,), 1_000_050)),
            Decimal((0, (1,), 1_000_050)),
        ),
        target_weights=(Decimal("0.4"), Decimal("0.4")),
        target_equity_weight=Decimal("0.8"),
        buy_cost_rate=Decimal("0.001"),
        sell_cost_rate=Decimal("0.0025"),
    )
    snapshot = tuple(
        getattr(underflow_input, field.name)
        for field in fields(SelfFinancingTransitionInput)
    )

    original = getcontext().copy()
    hostile = Context(
        prec=4,
        rounding=ROUND_DOWN,
        Emin=-9,
        Emax=9,
        capitals=0,
        clamp=1,
    )
    for signal in hostile.traps:
        hostile.traps[signal] = True
        hostile.flags[signal] = True

    try:
        setcontext(hostile)
        expected_state = _context_state(getcontext())
        with pytest.raises(SelfFinancingTransitionError, match="underflow"):
            apply_fractional_self_financing_transition(underflow_input)
        actual_state = _context_state(getcontext())
    finally:
        setcontext(original)

    assert tuple(
        getattr(underflow_input, field.name)
        for field in fields(SelfFinancingTransitionInput)
    ) == snapshot
    assert actual_state == expected_state
    assert apply_fractional_self_financing_transition(_transition_input()) == (
        apply_fractional_self_financing_transition(_transition_input())
    )


def test_decimal_context_factory_returns_fresh_pinned_standard_contexts() -> None:
    first = self_financing_module._new_decimal_context(50)
    second = self_financing_module._new_decimal_context(50)

    assert first is not second
    assert first.prec == second.prec == 50
    assert first.rounding == second.rounding == ROUND_HALF_EVEN
    assert first.Emin == second.Emin == -999_999
    assert first.Emax == second.Emax == 999_999
    assert first.capitals == second.capitals == 1
    assert first.clamp == second.clamp == 0
    assert {signal for signal, enabled in first.traps.items() if enabled} == {
        InvalidOperation,
        DivisionByZero,
        Overflow,
    }
    assert not any(first.flags.values())
    assert _context_state(first) == _context_state(second)


def test_public_and_trusted_paths_ignore_and_preserve_hostile_default_context() -> None:
    original_default = DefaultContext.copy()
    caller_state = _context_state(getcontext())
    basic_state = _context_state(BasicContext)
    extended_state = _context_state(ExtendedContext)
    try:
        DefaultContext.prec = 2
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.Emin = -9
        DefaultContext.Emax = 9
        DefaultContext.capitals = 0
        DefaultContext.clamp = 1
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
            DefaultContext.flags[signal] = True
        hostile_default_state = _context_state(DefaultContext)

        public_result = apply_fractional_self_financing_transition(
            _anchor_transition_input()
        )
        trusted_result = apply_fractional_self_financing_transition(
            _trusted_transition_input()
        )
        with pytest.raises(SelfFinancingTransitionError) as caught:
            apply_fractional_self_financing_transition(object())  # type: ignore[arg-type]
        default_state_after = _context_state(DefaultContext)
        caller_state_after = _context_state(getcontext())
    finally:
        _restore_context(DefaultContext, original_default)

    assert public_result == _EXPECTED_ANCHOR_RESULT
    assert trusted_result == _EXPECTED_MIXED_RESULT
    assert str(caught.value) == (
        "자기금융 전환 입력은 SelfFinancingTransitionInput이어야 합니다."
    )
    assert default_state_after == hostile_default_state
    assert caller_state_after == caller_state
    assert _context_state(DefaultContext) == _context_state(original_default)
    assert _context_state(BasicContext) == basic_state
    assert _context_state(ExtendedContext) == extended_state


def test_public_kernel_ignores_and_preserves_hostile_global_decimal_context() -> None:
    original = getcontext().copy()
    hostile = Context(
        prec=4,
        rounding=ROUND_DOWN,
        Emin=-9,
        Emax=9,
        capitals=0,
        clamp=1,
    )
    for signal in hostile.traps:
        hostile.traps[signal] = True
        hostile.flags[signal] = True

    try:
        setcontext(hostile)
        expected_state = _context_state(getcontext())
        transition_input = _anchor_transition_input()
        after_input_state = _context_state(getcontext())
        with pytest.raises(SelfFinancingTransitionError):
            _transition_input(cash_before=Decimal("NaN"))
        after_failed_public_input_state = _context_state(getcontext())
        with pytest.raises(SelfFinancingTransitionError):
            _trusted_transition_input(cash_before=Decimal("NaN"))
        after_failed_trusted_input_state = _context_state(getcontext())
        result = apply_fractional_self_financing_transition(transition_input)
        actual_state = _context_state(getcontext())
    finally:
        setcontext(original)

    assert result == _EXPECTED_ANCHOR_RESULT
    assert after_input_state == expected_state
    assert after_failed_public_input_state == expected_state
    assert after_failed_trusted_input_state == expected_state
    assert actual_state == expected_state


def test_public_kernel_is_deterministic_across_concurrent_invocations() -> None:
    barrier = Barrier(4)
    parent_state = _context_state(getcontext())
    hostile_contexts = (
        Context(prec=2, rounding=ROUND_DOWN, Emin=-5, Emax=5, capitals=0, clamp=1),
        Context(prec=3, rounding=ROUND_UP, Emin=-6, Emax=6, capitals=1, clamp=0),
        Context(prec=4, rounding=ROUND_FLOOR, Emin=-7, Emax=7, capitals=0, clamp=0),
        Context(prec=5, rounding=ROUND_CEILING, Emin=-8, Emax=8, capitals=1, clamp=1),
    )
    for hostile in hostile_contexts:
        for signal in hostile.traps:
            hostile.traps[signal] = True
            hostile.flags[signal] = True

    def run_with_hostile_context(
        hostile: Context,
    ) -> tuple[
        int,
        SelfFinancingTransitionResult,
        tuple[object, ...],
        tuple[object, ...],
        tuple[object, ...],
        tuple[object, ...],
        tuple[object, ...],
    ]:
        original = getcontext().copy()
        try:
            setcontext(hostile.copy())
            hostile_state = _context_state(getcontext())
            transition_input = _anchor_transition_input()
            after_input_state = _context_state(getcontext())
            barrier.wait(timeout=10)
            result = apply_fractional_self_financing_transition(transition_input)
            after_apply_state = _context_state(getcontext())
        finally:
            setcontext(original)
        restored_state = _context_state(getcontext())
        return (
            get_ident(),
            result,
            hostile_state,
            after_input_state,
            after_apply_state,
            _context_state(original),
            restored_state,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(run_with_hostile_context, hostile_contexts))

    assert len({item[0] for item in results}) == 4
    assert len({item[2][:6] for item in results}) == 4
    for (
        _,
        result,
        hostile_state,
        after_input_state,
        after_apply_state,
        original_state,
        restored_state,
    ) in results:
        assert result == _EXPECTED_ANCHOR_RESULT
        assert after_input_state == hostile_state
        assert after_apply_state == hostile_state
        assert restored_state == original_state
    assert _context_state(getcontext()) == parent_state


def test_error_identity_exports_and_dependency_direction_are_stable() -> None:
    assert SelfFinancingTransitionError is AllocationSelfFinancingError
    assert self_financing_module.__all__ == [
        "SelfFinancingTransitionError",
        "SelfFinancingTransitionInput",
        "SelfFinancingTransitionResult",
        "apply_fractional_self_financing_transition",
    ]

    kernel_path = ROOT / "src" / "phalanx" / "portfolio" / "self_financing.py"
    backtest_path = ROOT / "src" / "phalanx" / "portfolio" / "allocation_backtest.py"
    kernel_imports = _direct_imports(
        kernel_path,
        "phalanx.portfolio.self_financing",
    )
    backtest_imports = _direct_imports(
        backtest_path,
        "phalanx.portfolio.allocation_backtest",
    )

    assert kernel_imports == {
        ("__future__", "annotations", None),
        ("dataclasses", "dataclass", None),
        ("decimal", "MAX_PREC", None),
        ("decimal", "ROUND_HALF_EVEN", None),
        ("decimal", "Clamped", None),
        ("decimal", "Context", None),
        ("decimal", "Decimal", None),
        ("decimal", "DecimalException", None),
        ("decimal", "DivisionByZero", None),
        ("decimal", "Inexact", None),
        ("decimal", "InvalidOperation", None),
        ("decimal", "Overflow", None),
        ("decimal", "Rounded", None),
        ("decimal", "Subnormal", None),
        ("decimal", "Underflow", None),
        ("decimal", "localcontext", None),
        (
            "phalanx.portfolio.errors",
            "AllocationSelfFinancingError",
            "SelfFinancingTransitionError",
        ),
    }
    kernel_modules = {module for module, _, _ in kernel_imports}
    backtest_modules = {module for module, _, _ in backtest_imports}
    assert "phalanx.portfolio.allocation_backtest" not in kernel_modules
    assert "phalanx.portfolio.self_financing" in backtest_modules

    relative_tree = ast.parse(
        "from . import allocation_backtest\nfrom ..domain import AllocationTarget\n"
    )
    assert _direct_imports_from_tree(
        relative_tree,
        "phalanx.portfolio.self_financing",
    ) == {
        ("phalanx.portfolio.allocation_backtest", None, None),
        ("phalanx.domain", "AllocationTarget", None),
    }

    kernel_tree = ast.parse(kernel_path.read_text(encoding="utf-8"), filename=str(kernel_path))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "__import__"
        for node in ast.walk(kernel_tree)
    )
    assert not any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id in {"Context", "_new_decimal_context"}
        for node in kernel_tree.body
    )

    trusted_constructor_callers: list[Path] = []
    for source_path in (ROOT / "src").rglob("*.py"):
        source_tree = ast.parse(
            source_path.read_text(encoding="utf-8"),
            filename=str(source_path),
        )
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_from_validated_values"
            for node in ast.walk(source_tree)
        ):
            trusted_constructor_callers.append(source_path.relative_to(ROOT))
    assert trusted_constructor_callers == [
        Path("src/phalanx/portfolio/allocation_backtest.py")
    ]

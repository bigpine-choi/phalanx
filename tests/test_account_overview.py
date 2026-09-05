from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from phalanx.account_overview import (
    AccountOverviewError,
    build_account_overview,
    calculate_asset_reconciliation,
)
from phalanx.account_overview_storage import serialize_account_overview
from phalanx.domain import (
    AccountPosition,
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    CurrentPriceMarket,
    CurrentPriceObservation,
    SnapshotEvidence,
    ValuationPriceBundle,
)
from phalanx.domain.account_overview import AccountOverview

START = datetime(2026, 9, 5, tzinfo=UTC)
CODES = ("000660", "000270")


@pytest.fixture
def snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_number_masked="0000****-**",
        query_started_at=START,
        query_completed_at=START + timedelta(seconds=1),
        summary=AccountSummary(
            deposit_total=Decimal(50),
            securities_evaluation_amount=Decimal(520),
            purchase_amount_total=Decimal(480),
            evaluation_amount_total=Decimal(520),
            profit_loss_total=Decimal(40),
            total_assets=Decimal(600),
            net_assets=Decimal(580),
        ),
        positions=tuple(
            AccountPosition(
                stock_code=code,
                product_name=f"합성종목 {i}",
                holding_quantity=Decimal(quantity),
                sellable_quantity=Decimal(quantity),
                purchase_amount=Decimal(amount),
                evaluation_amount=Decimal(amount),
                profit_loss=Decimal(0),
            )
            for i, (code, quantity, amount) in enumerate(
                zip(CODES, (1, 3), (200, 300), strict=True)
            )
        ),
        evidence=SnapshotEvidence(
            pages=(
                ApiPageEvidence(
                    received_at=START + timedelta(seconds=1),
                    http_status=200,
                    tr_cont="",
                    ctx_area_fk100="",
                    ctx_area_nk100="",
                    rt_cd="0",
                    msg_cd="SYNTHETIC",
                    msg1="Synthetic only",
                    response_body_sha256="a" * 64,
                ),
            )
        ),
    )


def prices(
    *,
    codes: tuple[str, ...] = CODES,
    start: int = 1,
    end_microseconds: int = 3_000_000,
    market: CurrentPriceMarket = CurrentPriceMarket.KRX,
) -> ValuationPriceBundle:
    return ValuationPriceBundle(
        stock_codes=codes,
        currency="KRW",
        observations=tuple(
            CurrentPriceObservation(
                stock_code=code,
                current_price=Decimal(210 if code == CODES[0] else 110),
                market=market,
                request_started_at=START + timedelta(seconds=start),
                received_at=START + timedelta(microseconds=end_microseconds),
            )
            for code in codes
        ),
    )


def test_overview_uses_held_stock_denominator_and_preserves_broker_nav(
    snapshot: AccountSnapshot,
) -> None:
    before = snapshot.model_dump_json()
    result = build_account_overview(snapshot, prices())
    assert [p.stock_code for p in result.positions] == list(CODES)
    assert [p.observed_evaluation_amount for p in result.positions] == [Decimal(210), Decimal(330)]
    assert result.totals.observed_positions_evaluation_amount == Decimal(540)
    assert result.totals.broker_positions_evaluation_amount == Decimal(500)
    assert result.totals.broker_summary_minus_positions == Decimal(20)
    assert result.totals.observed_minus_broker_positions == Decimal(40)
    assert result.totals.broker_other_assets_and_settlement_adjustments == Decimal(30)
    assert result.totals.broker_liabilities_and_deductions == Decimal(20)
    assert result.snapshot.summary.net_assets == Decimal(580)
    assert result.snapshot.summary.orderable_cash is None
    with localcontext() as context:
        context.prec = 50
        assert result.positions[0].observed_stock_weight == Decimal(210) / Decimal(540)
    assert result.weight_basis == "observed_positive_holdings_value"
    assert snapshot.model_dump_json() == before


def test_global_decimal_context_does_not_change_results(snapshot: AccountSnapshot) -> None:
    expected = serialize_account_overview(build_account_overview(snapshot, prices()))
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        actual = serialize_account_overview(build_account_overview(snapshot, prices()))
    assert actual == expected


def test_serialized_result_is_repeatable_and_reloadable_by_a_gui(snapshot: AccountSnapshot) -> None:
    overview = build_account_overview(snapshot, prices())
    serialized = serialize_account_overview(overview)
    assert serialized == serialize_account_overview(build_account_overview(snapshot, prices()))
    assert AccountOverview.model_validate_json(serialized) == overview
    assert b'"observed_price": "210"' in serialized
    assert b'"report_type": "account_overview"' in serialized
    assert b'"orderable_cash": null' in serialized


def test_empty_holdings_skip_prices_without_fabricating_nav(snapshot: AccountSnapshot) -> None:
    empty = snapshot.model_copy(update={"positions": ()})
    overview = build_account_overview(empty, None)
    assert overview.positions == ()
    assert overview.totals.observed_positions_evaluation_amount == 0
    assert overview.snapshot.summary.net_assets == 580
    assert overview.observation_span_microseconds == 1_000_000


def test_nonpositive_nav_does_not_change_stock_only_weights(snapshot: AccountSnapshot) -> None:
    changed = snapshot.model_copy(
        update={"summary": snapshot.summary.model_copy(update={"net_assets": Decimal(-10)})}
    )
    assert (
        build_account_overview(changed, prices()).positions
        == build_account_overview(snapshot, prices()).positions
    )


@pytest.mark.parametrize(
    "bundle",
    [
        None,
        prices(codes=CODES[::-1]),
        prices(codes=(CODES[0],)),
        prices(market=CurrentPriceMarket.NXT),
    ],
)
def test_mismatched_price_bundle_is_rejected(
    snapshot: AccountSnapshot, bundle: ValuationPriceBundle | None
) -> None:
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(snapshot, bundle)
    assert caught.value.code == "price_mismatch"


def test_empty_holdings_reject_unrelated_prices(snapshot: AccountSnapshot) -> None:
    with pytest.raises(AccountOverviewError, match="일치하지"):
        build_account_overview(snapshot.model_copy(update={"positions": ()}), prices())


def test_prices_cannot_precede_the_account_observation(snapshot: AccountSnapshot) -> None:
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(snapshot, prices(start=0))
    assert caught.value.code == "price_precedes_snapshot"


def test_total_span_includes_balance_query_and_has_exact_microsecond_boundary(
    snapshot: AccountSnapshot,
) -> None:
    accepted = build_account_overview(snapshot, prices(), max_observation_span_seconds=3)
    assert accepted.observation_span_microseconds == 3_000_000
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(
            snapshot, prices(end_microseconds=3_000_001), max_observation_span_seconds=3
        )
    assert caught.value.code == "observation_span_exceeded"


@pytest.mark.parametrize("seconds", [0, -1, True, 1.5, "60", 10**30])
def test_span_validation(snapshot: AccountSnapshot, seconds: int) -> None:
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(snapshot, prices(), max_observation_span_seconds=seconds)
    assert caught.value.code == "invalid_span"


def test_account_summary_warning_requires_a_new_observation(snapshot: AccountSnapshot) -> None:
    changed = snapshot.model_copy(
        update={
            "evidence": snapshot.evidence.model_copy(
                update={"summary_consistency_warnings": ("Synthetic change",)}
            )
        }
    )
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(changed, prices())
    assert caught.value.code == "inconsistent_snapshot"


def test_unsupported_positive_holding_is_not_silently_excluded(snapshot: AccountSnapshot) -> None:
    changed = snapshot.model_copy(
        update={"positions": (snapshot.positions[0].model_copy(update={"stock_code": "ABC123"}),)}
    )
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(changed, prices())
    assert caught.value.code == "unsupported_holding"


def test_zero_quantity_balances_do_not_enter_quote_request_or_weights(
    snapshot: AccountSnapshot,
) -> None:
    zero = snapshot.positions[0].model_copy(
        update={
            "stock_code": "ZERO",
            "holding_quantity": Decimal(0),
            "sellable_quantity": Decimal(0),
        }
    )
    changed = snapshot.model_copy(update={"zero_quantity_balances": (zero,)})
    assert (
        build_account_overview(changed, prices()).positions
        == build_account_overview(snapshot, prices()).positions
    )


def test_reverse_derived_amounts_use_shared_fixed_context(snapshot: AccountSnapshot) -> None:
    with localcontext() as context:
        context.prec = 1
        assert calculate_asset_reconciliation(snapshot.summary) == (Decimal(30), Decimal(20))


def test_extreme_arithmetic_range_fails_without_a_result(snapshot: AccountSnapshot) -> None:
    huge = snapshot.positions[0].model_copy(update={"holding_quantity": Decimal("1e999999")})
    changed = snapshot.model_copy(update={"positions": (huge, snapshot.positions[1])})
    with pytest.raises(AccountOverviewError) as caught:
        build_account_overview(changed, prices())
    assert caught.value.code == "calculation_range"

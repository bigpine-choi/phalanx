from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, Inexact, Rounded, getcontext, localcontext
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from phalanx.account_performance import AccountPerformanceError, calculate_account_performance
from phalanx.domain.account import (
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    SnapshotEvidence,
)
from phalanx.domain.account_performance import CashFlowLedger

T0 = datetime(2026, 9, 1, tzinfo=UTC)
T1 = T0 + timedelta(seconds=10)


def _snapshot(net_assets: str, observed_at: datetime) -> AccountSnapshot:
    return AccountSnapshot(
        account_number_masked="1234****-**",
        query_started_at=(observed_at.astimezone(UTC) - timedelta(microseconds=1)).astimezone(
            observed_at.tzinfo
        ),
        query_completed_at=observed_at,
        summary=AccountSummary(
            deposit_total=Decimal("999"),
            securities_evaluation_amount=Decimal("888"),
            purchase_amount_total=Decimal("777"),
            evaluation_amount_total=Decimal("666"),
            profit_loss_total=Decimal("555"),
            total_assets=Decimal("444"),
            net_assets=Decimal(net_assets),
        ),
        evidence=SnapshotEvidence(
            pages=(
                ApiPageEvidence(
                    received_at=observed_at,
                    http_status=200,
                    tr_cont="",
                    ctx_area_fk100="",
                    ctx_area_nk100="",
                    rt_cd="0",
                    msg_cd="SYNTHETIC",
                    msg1="합성 데이터",
                    response_body_sha256="a" * 64,
                ),
            )
        ),
    )


def _ledger_payload(
    events: list[tuple[str, datetime, Any]] | None = None,
    start: datetime = T0,
    end: datetime = T1,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "same_account_confirmed": True,
        "external_flows_complete": True,
        "no_in_kind_transfers": True,
        "events": [
            {"event_id": event_id, "occurred_at": instant.isoformat(), "amount": amount}
            for event_id, instant, amount in (events or [])
        ],
    }


def _ledger(
    events: list[tuple[str, datetime, Any]] | None = None,
    start: datetime = T0,
    end: datetime = T1,
) -> CashFlowLedger:
    return CashFlowLedger.model_validate(_ledger_payload(events, start, end))


@pytest.mark.parametrize(
    ("ending", "flow", "profit", "capital", "rate"),
    [
        ("110", None, "10", "100", "0.1"),
        ("200", "+100", "0", "150", "0"),
        ("220", "+100", "20", "150", "0." + "13" + "3" * 48),
        ("68", "-40", "8", "80", "0.1"),
    ],
)
def test_hand_checked_modified_dietz_examples(
    ending: str, flow: str | None, profit: str, capital: str, rate: str
) -> None:
    events = [] if flow is None else [("midpoint", T0 + timedelta(seconds=5), flow)]

    result = calculate_account_performance(
        _snapshot("100", T0), _snapshot(ending, T1), _ledger(events)
    )

    assert result.beginning_net_assets == Decimal("100")
    assert result.ending_net_assets == Decimal(ending)
    assert result.profit_loss == Decimal(profit)
    assert result.average_invested_capital == Decimal(capital)
    assert result.estimated_return == Decimal(rate)
    assert result.return_unavailable_reasons == ()


def test_equal_opposite_flows_at_distinct_times_are_weighted_separately() -> None:
    result = calculate_account_performance(
        _snapshot("100", T0),
        _snapshot("112", T1),
        _ledger(
            [
                ("withdrawal", T0 + timedelta(seconds=7), "-50"),
                ("deposit", T0 + timedelta(seconds=3), "+50"),
            ]
        ),
    )

    assert result.total_deposits == result.total_withdrawals == Decimal("50")
    assert result.net_cash_flow == 0
    assert result.profit_loss == Decimal("12")
    assert result.average_invested_capital == Decimal("120")
    assert result.estimated_return == Decimal("0.1")
    assert [flow.weight for flow in result.weighted_cash_flows] == [Decimal("0.7"), Decimal("0.3")]
    assert [flow.weighted_amount for flow in result.weighted_cash_flows] == [
        Decimal("35"),
        Decimal("-15"),
    ]


def test_distinct_events_at_same_instant_are_allowed_and_keep_gross_totals() -> None:
    midpoint = T0 + timedelta(seconds=5)
    result = calculate_account_performance(
        _snapshot("100", T0),
        _snapshot("110", T1),
        _ledger([("in", midpoint, "50"), ("out", midpoint, "-50")]),
    )

    assert len(result.weighted_cash_flows) == 2
    assert result.total_deposits == result.total_withdrawals == Decimal("50")
    assert result.average_invested_capital == Decimal("100")
    assert result.estimated_return == Decimal("0.1")


def test_dividend_and_already_reflected_fee_remain_in_net_assets_once() -> None:
    # NAV 100 + cash dividend 10 - account fee 1 = 109; none is external CF.
    result = calculate_account_performance(_snapshot("100", T0), _snapshot("109", T1), _ledger())

    assert result.net_cash_flow == 0
    assert result.profit_loss == Decimal("9")
    assert result.estimated_return == Decimal("0.09")
    assert "배당" in result.assumptions.internal_cash_flow_treatment
    assert "다시 차감하지" in result.assumptions.internal_cash_flow_treatment


def test_only_external_withdrawal_after_cash_dividend_is_counted() -> None:
    # Dividend 10 is earned, then withdrawn: ending NAV is still 100.
    result = calculate_account_performance(
        _snapshot("100", T0),
        _snapshot("100", T1),
        _ledger([("dividend-cash-out", T0 + timedelta(seconds=5), "-10")]),
    )

    assert result.profit_loss == Decimal("10")
    assert result.average_invested_capital == Decimal("95")
    assert result.total_withdrawals == Decimal("10")


@pytest.mark.parametrize(
    ("beginning", "ending", "flow", "capital", "reasons"),
    [
        ("0", "15", "20", "10", ("기초 순자산",)),
        ("-1", "15", "20", "9", ("기초 순자산",)),
        ("100", "10", "-200", "0", ("평균투하자본",)),
        ("100", "10", "-300", "-50", ("평균투하자본",)),
        ("0", "10", None, "0", ("기초 순자산", "평균투하자본")),
        ("-10", "10", None, "-10", ("기초 순자산", "평균투하자본")),
    ],
)
def test_unavailable_return_keeps_profit_and_explains_each_reason(
    beginning: str, ending: str, flow: str | None, capital: str, reasons: tuple[str, ...]
) -> None:
    events = [] if flow is None else [("midpoint", T0 + timedelta(seconds=5), flow)]
    result = calculate_account_performance(
        _snapshot(beginning, T0), _snapshot(ending, T1), _ledger(events)
    )

    assert result.estimated_return is None
    assert result.average_invested_capital == Decimal(capital)
    assert result.profit_loss == Decimal(ending) - Decimal(beginning) - Decimal(flow or "0")
    assert len(result.return_unavailable_reasons) == len(reasons)
    for expected, actual in zip(reasons, result.return_unavailable_reasons, strict=True):
        assert expected in actual


@pytest.mark.parametrize("field", ["schema_version", "coverage_start", "coverage_end", "events"])
def test_ledger_requires_explicit_schema_period_and_events(field: str) -> None:
    payload = _ledger_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        CashFlowLedger.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["same_account_confirmed", "external_flows_complete", "no_in_kind_transfers"]
)
@pytest.mark.parametrize("value", [False, None, "true", 1, "missing"])
def test_declarations_must_all_be_explicit_boolean_true(field: str, value: Any) -> None:
    payload = _ledger_payload()
    if value == "missing":
        del payload[field]
    else:
        payload[field] = value
    with pytest.raises(ValidationError):
        CashFlowLedger.model_validate(payload)


@pytest.mark.parametrize(
    "amount",
    [
        "0",
        "-0",
        "+0.00",
        1.0,
        True,
        1,
        Decimal("1"),
        None,
        "NaN",
        "Infinity",
        "1e3",
        " 1",
        "+1.",
        ".1",
        "1,000",
        "",
    ],
)
def test_cash_flow_amount_rejects_non_decimal_strings_and_zero(amount: Any) -> None:
    with pytest.raises(ValidationError):
        _ledger([("event", T0 + timedelta(seconds=5), amount)])


@pytest.mark.parametrize("amount", ["+1.25", "1.25", "001.25", "-1.25"])
def test_signed_decimal_amount_strings_are_accepted(amount: str) -> None:
    ledger = _ledger([("event", T0 + timedelta(seconds=5), amount)])
    assert ledger.events[0].amount == Decimal(amount)
    assert isinstance(json.loads(ledger.model_dump_json())["events"][0]["amount"], str)


@pytest.mark.parametrize("instant", [T0 - timedelta(seconds=1), T1 + timedelta(microseconds=1)])
def test_outside_ledger_period_is_rejected(instant: datetime) -> None:
    with pytest.raises(AccountPerformanceError, match="두 관측시각 사이"):
        calculate_account_performance(
            _snapshot("100", T0), _snapshot("110", T1), _ledger([("outside", instant, "1")])
        )


def test_duplicate_ids_are_rejected_even_with_distinct_timestamps() -> None:
    with pytest.raises(ValidationError, match="중복 event_id"):
        _ledger(
            [
                ("duplicate", T0 + timedelta(seconds=2), "1"),
                ("duplicate", T0 + timedelta(seconds=8), "-1"),
            ]
        )


@pytest.mark.parametrize("field", ["coverage_start", "coverage_end", "occurred_at"])
@pytest.mark.parametrize("invalid", ["2026-09-01T00:00:00", 1788220800, True])
def test_ledger_timestamps_require_explicit_timezone(field: str, invalid: Any) -> None:
    payload = _ledger_payload([("event", T0 + timedelta(seconds=5), "1")])
    if field == "occurred_at":
        payload["events"][0][field] = invalid
    else:
        payload[field] = invalid
    with pytest.raises(ValidationError):
        CashFlowLedger.model_validate(payload)


@pytest.mark.parametrize("identifier", ["", "   ", 1, None])
def test_event_id_must_be_nonblank_text(identifier: Any) -> None:
    payload = _ledger_payload([("event", T0 + timedelta(seconds=5), "1")])
    payload["events"][0]["event_id"] = identifier
    with pytest.raises(ValidationError):
        CashFlowLedger.model_validate(payload)


def test_unknown_ledger_fields_are_rejected() -> None:
    payload = _ledger_payload()
    payload["internal_dividends"] = "10"
    with pytest.raises(ValidationError):
        CashFlowLedger.model_validate(payload)


@pytest.mark.parametrize("observed_at", [T0, T0 - timedelta(seconds=1)])
def test_reversed_or_equal_observations_are_rejected(observed_at: datetime) -> None:
    with pytest.raises(AccountPerformanceError, match="시작 관측시각"):
        calculate_account_performance(
            _snapshot("100", T0), _snapshot("110", observed_at), _ledger()
        )


@pytest.mark.parametrize("query_start", [T0, T0 - timedelta(microseconds=1)])
def test_touching_or_overlapping_query_intervals_are_rejected(query_start: datetime) -> None:
    end = _snapshot("110", T1).model_copy(update={"query_started_at": query_start})
    with pytest.raises(AccountPerformanceError, match="조회구간이 겹치거나"):
        calculate_account_performance(_snapshot("100", T0), end, _ledger())


@pytest.mark.parametrize("field", ["provider", "currency", "account_number_masked"])
def test_snapshot_identity_components_must_match(field: str) -> None:
    changed = "4321****-**" if field == "account_number_masked" else "different"
    end = _snapshot("110", T1).model_copy(update={field: changed})
    with pytest.raises(AccountPerformanceError, match="일치해야"):
        calculate_account_performance(_snapshot("100", T0), end, _ledger())


@pytest.mark.parametrize("warning_side", ["start", "end"])
def test_summary_consistency_warnings_reject_either_snapshot(warning_side: str) -> None:
    start, end = _snapshot("100", T0), _snapshot("110", T1)
    target = start if warning_side == "start" else end
    target = target.model_copy(
        update={
            "evidence": target.evidence.model_copy(
                update={"summary_consistency_warnings": ("changed during pagination",)}
            )
        }
    )
    if warning_side == "start":
        start = target
    else:
        end = target
    with pytest.raises(AccountPerformanceError, match="summary_consistency_warnings"):
        calculate_account_performance(start, end, _ledger())


@pytest.mark.parametrize("field", ["coverage_start", "coverage_end"])
def test_ledger_coverage_must_match_observation_instants(field: str) -> None:
    payload = _ledger_payload()
    original = T0 if field == "coverage_start" else T1
    payload[field] = (original + timedelta(microseconds=1)).isoformat()
    with pytest.raises(AccountPerformanceError, match="coverage_start/end"):
        calculate_account_performance(
            _snapshot("100", T0), _snapshot("110", T1), CashFlowLedger.model_validate(payload)
        )


@pytest.mark.parametrize("offset", [0, 8, 9, 10])
def test_query_interval_and_both_boundaries_reject_ambiguous_cash_flow(offset: int) -> None:
    end = _snapshot("110", T1).model_copy(update={"query_started_at": T0 + timedelta(seconds=8)})
    with pytest.raises(AccountPerformanceError, match=r"순자산\(NAV\) 반영 여부가 모호"):
        calculate_account_performance(
            _snapshot("100", T0), end, _ledger([("ambiguous", T0 + timedelta(seconds=offset), "1")])
        )


@pytest.mark.parametrize("offset", [-2, -1, 0])
def test_start_query_interval_and_boundaries_explain_nav_ambiguity(offset: int) -> None:
    start = _snapshot("100", T0).model_copy(update={"query_started_at": T0 - timedelta(seconds=2)})
    with pytest.raises(AccountPerformanceError, match=r"순자산\(NAV\) 반영 여부가 모호"):
        calculate_account_performance(
            start,
            _snapshot("110", T1),
            _ledger([("ambiguous", T0 + timedelta(seconds=offset), "1")]),
        )


def test_same_instant_in_another_timezone_matches_coverage() -> None:
    kst = timezone(timedelta(hours=9))
    ledger = _ledger(start=T0.astimezone(kst), end=T1.astimezone(kst))
    result = calculate_account_performance(_snapshot("100", T0), _snapshot("110", T1), ledger)
    assert result.estimated_return == Decimal("0.1")
    assert result.start_observed_at.tzinfo == UTC


def test_microsecond_weights_use_exact_integer_durations() -> None:
    end_time = T0 + timedelta(microseconds=3)
    end = _snapshot("101", end_time).model_copy(update={"query_started_at": end_time})
    result = calculate_account_performance(
        _snapshot("100", T0),
        end,
        _ledger([("one-microsecond", T0 + timedelta(microseconds=1), "1")], end=end_time),
    )
    assert result.period_microseconds == 3
    assert result.weighted_cash_flows[0].remaining_microseconds == 2
    assert result.weighted_cash_flows[0].weight == Decimal("0." + "6" * 49 + "7")


def test_utc_duration_handles_repeated_wall_clock_hour() -> None:
    zone = ZoneInfo("America/New_York")
    start_time = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    end_time = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    midpoint = start_time.astimezone(UTC) + timedelta(minutes=30)
    result = calculate_account_performance(
        _snapshot("100", start_time),
        _snapshot("220", end_time),
        _ledger([("midpoint", midpoint, "100")], start_time, end_time),
    )
    assert result.period_microseconds == 3600_000_000
    assert result.weighted_cash_flows[0].weight == Decimal("0.5")
    assert result.average_invested_capital == Decimal("150")


def test_calculation_and_json_ignore_global_decimal_context_and_preserve_it() -> None:
    start, end = _snapshot("100", T0), _snapshot("220", T1)
    ledger = _ledger([("deposit", T0 + timedelta(seconds=5), "100")])
    expected = calculate_account_performance(start, end, ledger).model_dump_json()
    with localcontext() as hostile:
        hostile.prec = 2
        hostile.rounding = ROUND_FLOOR
        hostile.Emin = -2
        hostile.Emax = 2
        hostile.clamp = 1
        hostile.capitals = 0
        hostile.traps[Inexact] = True
        hostile.traps[Rounded] = True
        hostile.flags[Inexact] = True
        before = repr(hostile)

        actual = calculate_account_performance(start, end, ledger).model_dump_json()

        assert actual == expected
        assert repr(getcontext()) == before
    result = json.loads(actual)
    assert result["scope"] == "whole_account"
    assert result["method"] == "modified_dietz"
    assert result["decimal_context"]["precision"] == 50
    assert result["decimal_context"]["emax"] == 999999
    assert result["assumptions"]["ledger_schema_version"] == "1"
    assert result["assumptions"]["same_account_confirmed"] is True
    assert "확정 종가시각" in result["assumptions"]["observation_time_caveat"]


def test_decimal_overflow_is_a_safe_calculation_error() -> None:
    with pytest.raises(AccountPerformanceError, match="고정 Decimal context의 지원 범위"):
        calculate_account_performance(_snapshot("100", T0), _snapshot("1e1000000", T1), _ledger())


def test_ledger_rejects_datetime_that_overflows_when_converted_to_utc() -> None:
    payload = _ledger_payload()
    payload["coverage_start"] = "0001-01-01T00:00:00+14:00"
    with pytest.raises(ValidationError, match="UTC로 변환 가능한 날짜 범위"):
        CashFlowLedger.model_validate(payload)


def test_snapshot_utc_conversion_overflow_is_a_safe_calculation_error() -> None:
    minimum_time = datetime.fromisoformat("0001-01-01T00:00:00+14:00")
    start = _snapshot("100", T0).model_copy(
        update={"query_started_at": minimum_time, "query_completed_at": minimum_time}
    )
    with pytest.raises(AccountPerformanceError, match="UTC로 변환 가능한 날짜 범위"):
        calculate_account_performance(start, _snapshot("110", T1), _ledger())


def test_result_evidence_is_deeply_immutable() -> None:
    result = calculate_account_performance(_snapshot("100", T0), _snapshot("110", T1), _ledger())
    with pytest.raises(ValidationError):
        result.profit_loss = Decimal("0")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.assumptions.same_account_confirmed = False  # type: ignore[misc, assignment]

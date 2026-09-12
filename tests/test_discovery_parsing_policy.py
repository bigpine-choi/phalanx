from __future__ import annotations

import pytest
from discovery_helpers import master

from phalanx.discovery.policy import POLICY_VERSION, evaluate
from phalanx.domain.discovery import Eligibility, Market
from phalanx.kis.master_parsing import parse_master

# Absolute byte offsets independently counted from the official C headers.
# These values do not come from the production FIELDS or serializer.
_POLICY_OFFSETS = {
    Market.KOSPI: {
        "group": 61,
        "preferred": 219,
        "etp": 83,
        "spac": 90,
        "halted": 121,
        "liquidation": 122,
        "managed": 123,
    },
    Market.KOSDAQ: {
        "group": 61,
        "preferred": 214,
        "etp": 79,
        "spac": 85,
        "halted": 116,
        "liquidation": 117,
        "managed": 118,
    },
}


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_independent_fixed_positions_and_newlines(market: Market, ending: bytes) -> None:
    row = master(market)
    result = parse_master(market, row + ending)
    assert result.total_lines == 1
    assert result.issues == ()
    record = result.records[0]
    assert record.short_code == ("005930" if market == Market.KOSPI else "035900")
    assert record.standard_code == ("KR7005930003" if market == Market.KOSPI else "KR7035900000")
    assert record.name == ("삼성전자" if market == Market.KOSPI else "한글우스팩보통주")
    assert record.security_group == "ST"
    assert record.etp_class == "0"
    assert record.preferred_class == "0"
    assert record.spac is False
    assert record.trading_halted is False
    assert record.liquidation_trading is False
    assert record.managed is False
    assert record.issuer_id is None
    assert record.raw_fields["mksc_shrn_iscd"].endswith("   ")
    assert record.raw_fields["short_over_cls_code"] == "3"
    assert record.raw_fields["mrkt_alrm_cls_code"] == ("02" if market == Market.KOSPI else "03")
    assert record.raw_fields["stck_lstn_date"] == (
        "19750611" if market == Market.KOSPI else "20010830"
    )
    assert record.raw_fields["base_date"] == ("20251231" if market == Market.KOSPI else "20250930")
    assert record.raw_fields["grp_code"] == ("123" if market == Market.KOSPI else "456")
    assert record.raw_fields["stln_able_yn"] == ("N" if market == Market.KOSPI else "Y")
    if market == Market.KOSDAQ:
        assert record.raw_fields["invt_alrm_yn"] == "Y"
    # Name fragments and warning/financial fields never add unrequested exclusions.
    assert evaluate(record).status == Eligibility.ELIGIBLE


@pytest.mark.parametrize("market", list(Market))
def test_mixed_line_endings_preserve_each_record(market: Market) -> None:
    row = master(market)
    parsed = parse_master(market, row + b"\r\n" + row + b"\n" + row)
    assert parsed.issues == ()
    assert [r.line_number for r in parsed.records] == [1, 2, 3]
    assert len({r.name for r in parsed.records}) == 1


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize("broken", [b"", b"short", b"\xff", b"\r", b"\n"])
def test_bad_rows_are_reported_and_not_silently_dropped(market: Market, broken: bytes) -> None:
    result = parse_master(market, master(market) + b"\n" + broken + b"\n")
    assert result.total_lines >= 2
    assert len(result.records) == 1
    assert result.issues[0].line_number == 2
    assert result.issues[0].code == "RECORD_WIDTH"


@pytest.mark.parametrize("market", list(Market))
def test_truncation_invalid_encoding_and_empty_master(market: Market) -> None:
    assert parse_master(market, master(market)[:-1]).issues[0].code == "RECORD_WIDTH"
    for patches in ({21: b"\xff"}, {61: b"\xff"}, {50: b"\x00"}, {80: b"\r"}):
        assert parse_master(market, master(market, patches)).issues[0].code == "RECORD_ENCODING"
    assert parse_master(market, b"").issues[0].code == "EMPTY_MASTER"


@pytest.mark.parametrize(
    ("offset", "value", "reason"),
    [
        (61, b"EF", "NON_DOMESTIC_ORDINARY_EQUITY"),
        (61, b"FS", "NON_DOMESTIC_ORDINARY_EQUITY"),
        (61, b"DR", "NON_DOMESTIC_ORDINARY_EQUITY"),
        (61, b"RT", "NON_DOMESTIC_ORDINARY_EQUITY"),
        (219, b"1", "PREFERRED_STOCK"),
        (219, b"2", "PREFERRED_STOCK"),
        (83, b"2", "ETP"),
        (83, b"3", "ETP"),
        (83, b"4", "ETP"),
        (83, b"5", "ETP"),
        (90, b"Y", "SPAC"),
        (121, b"Y", "TRADING_HALTED"),
        (122, b"Y", "LIQUIDATION_TRADING"),
        (123, b"Y", "MANAGED_ISSUE"),
    ],
)
def test_explicit_kospi_exclusions(offset: int, value: bytes, reason: str) -> None:
    decision = evaluate(parse_master(Market.KOSPI, master(patches={offset: value})).records[0])
    assert decision.status == Eligibility.EXCLUDED
    assert reason in {r.code for r in decision.reasons}
    assert all(r.description for r in decision.reasons)
    assert decision.policy_version == POLICY_VERSION


@pytest.mark.parametrize(
    ("offset", "value", "reason"),
    [
        (214, b"1", "PREFERRED_STOCK"),
        (79, b"3", "ETP"),
        (85, b"Y", "SPAC"),
        (116, b"Y", "TRADING_HALTED"),
        (117, b"Y", "LIQUIDATION_TRADING"),
        (118, b"Y", "MANAGED_ISSUE"),
    ],
)
def test_kosdaq_exclusion_mapping(offset: int, value: bytes, reason: str) -> None:
    decision = evaluate(
        parse_master(Market.KOSDAQ, master(Market.KOSDAQ, {offset: value})).records[0]
    )
    assert decision.status == Eligibility.EXCLUDED
    assert reason in {r.code for r in decision.reasons}


@pytest.mark.parametrize(
    ("offset", "width"),
    [(0, 9), (9, 12), (21, 40), (61, 2), (90, 1), (121, 1), (122, 1), (123, 1), (219, 1)],
)
@pytest.mark.parametrize("fill", [b" ", b"?"])
def test_missing_and_unsupported_required_information_never_passes(
    offset: int, width: int, fill: bytes
) -> None:
    # '?' is a valid company name, so only the missing name case is invalid.
    if offset == 21 and fill == b"?":
        return
    parsed = parse_master(Market.KOSPI, master(patches={offset: fill * width}))
    assert not parsed.issues  # semantic unknown, not a structurally damaged row
    decision = evaluate(parsed.records[0])
    assert decision.status == Eligibility.UNKNOWN
    assert ("MISSING_REQUIRED_FIELD" if fill == b" " else "UNSUPPORTED_CODE") in {
        r.code for r in decision.reasons
    }


def test_exclusions_win_but_preserve_missing_unsupported_and_conflicting_information() -> None:
    record = parse_master(Market.KOSPI, master(patches={83: b"3", 90: b"?", 219: b" "})).records[0]
    decision = evaluate(record)
    assert decision.status == Eligibility.EXCLUDED
    assert {r.code for r in decision.reasons} == {
        "ETP",
        "UNSUPPORTED_CODE",
        "MISSING_REQUIRED_FIELD",
        "CLASSIFICATION_CONFLICT",
    }


@pytest.mark.parametrize("value", [b"8", b"9", b"?"])
def test_observed_undocumented_etp_codes_remain_unknown(value: bytes) -> None:
    record = parse_master(Market.KOSPI, master(patches={83: value})).records[0]
    assert evaluate(record).status == Eligibility.UNKNOWN


def test_full_market_identifiers_are_not_forced_into_manual_six_digit_model() -> None:
    record = parse_master(Market.KOSPI, master(patches={0: b"F70100030", 61: b"BC"})).records[0]
    assert record.short_code == "F70100030"
    assert record.issuer_id is None
    assert evaluate(record).status == Eligibility.EXCLUDED


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize("etp", [b" ", b"0"])
def test_st_uses_independent_group_evidence_without_rewriting_etp(
    market: Market, etp: bytes
) -> None:
    record = parse_master(market, master(market, {_POLICY_OFFSETS[market]["etp"]: etp})).records[0]
    before = record.model_dump_json()
    decision = evaluate(record)
    assert decision.policy_version == "domestic-common-stock-v2"
    assert decision.status == Eligibility.ELIGIBLE
    assert record.raw_fields["etp_prod_cls_code"] == etp.decode()
    assert record.etp_class == (None if etp == b" " else "0")
    assert record.model_dump_json() == before
    assert {r.code for r in decision.reasons} == (
        {"NON_ETP_BY_ST_GROUP", "V2_PASSED"} if etp == b" " else {"V2_PASSED"}
    )
    assert not any(r.kind == "unknown" for r in decision.reasons)


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize(
    ("group", "etp", "expected", "required_reasons"),
    [
        (b"ST", b"2", "excluded", {"ETP", "CLASSIFICATION_CONFLICT"}),
        (b"EF", b"0", "excluded", {"NON_DOMESTIC_ORDINARY_EQUITY", "CLASSIFICATION_CONFLICT"}),
        (b"FE", b"0", "excluded", {"NON_DOMESTIC_ORDINARY_EQUITY", "CLASSIFICATION_CONFLICT"}),
        (b"ST", b"8", "unknown", {"UNSUPPORTED_CODE"}),
        (b"ST", b"?", "unknown", {"UNSUPPORTED_CODE"}),
        (b"EF", b" ", "excluded", {"NON_DOMESTIC_ORDINARY_EQUITY", "MISSING_REQUIRED_FIELD"}),
        (b"  ", b" ", "unknown", {"MISSING_REQUIRED_FIELD"}),
        (b"  ", b"0", "unknown", {"MISSING_REQUIRED_FIELD"}),
        (b"??", b" ", "unknown", {"UNSUPPORTED_CODE", "MISSING_REQUIRED_FIELD"}),
        (b"EN", b"3", "excluded", {"ETP", "UNSUPPORTED_CODE"}),
    ],
)
def test_etp_applicability_never_suppresses_conflicts_or_nonblank_unknowns(
    market: Market, group: bytes, etp: bytes, expected: str, required_reasons: set[str]
) -> None:
    positions = _POLICY_OFFSETS[market]
    record = parse_master(
        market, master(market, {positions["group"]: group, positions["etp"]: etp})
    ).records[0]
    decision = evaluate(record)
    assert decision.status == expected
    assert required_reasons <= {r.code for r in decision.reasons}
    assert "NON_ETP_BY_ST_GROUP" not in {r.code for r in decision.reasons}


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize(
    "field", ["group", "preferred", "spac", "halted", "liquidation", "managed"]
)
@pytest.mark.parametrize("value", [b" ", b"?"])
def test_blank_etp_does_not_excuse_other_required_unknowns(
    market: Market, field: str, value: bytes
) -> None:
    positions = _POLICY_OFFSETS[market]
    patches = {positions["etp"]: b" ", positions[field]: value * (2 if field == "group" else 1)}
    record = parse_master(market, master(market, patches)).records[0]
    decision = evaluate(record)
    assert decision.status == Eligibility.UNKNOWN
    assert any(r.kind == "unknown" for r in decision.reasons)
    assert record.etp_class is None


@pytest.mark.parametrize("market", list(Market))
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("preferred", b"1", "PREFERRED_STOCK"),
        ("preferred", b"2", "PREFERRED_STOCK"),
        ("spac", b"Y", "SPAC"),
        ("halted", b"Y", "TRADING_HALTED"),
        ("liquidation", b"Y", "LIQUIDATION_TRADING"),
        ("managed", b"Y", "MANAGED_ISSUE"),
    ],
)
def test_st_evidence_cannot_override_exclusions_or_other_missing_information(
    market: Market, field: str, value: bytes, code: str
) -> None:
    positions = _POLICY_OFFSETS[market]
    record = parse_master(
        market, master(market, {positions["etp"]: b" ", positions[field]: value, 9: b" " * 12})
    ).records[0]
    decision = evaluate(record)
    assert decision.status == Eligibility.EXCLUDED
    assert {code, "MISSING_REQUIRED_FIELD", "NON_ETP_BY_ST_GROUP"} <= {
        r.code for r in decision.reasons
    }
    assert {r.kind for r in decision.reasons} == {"exclude", "unknown", "evidence"}


def test_group_evidence_alone_is_not_a_complete_eligibility_decision() -> None:
    from pydantic import ValidationError

    from phalanx.domain.discovery import Decision, Reason

    with pytest.raises(ValidationError, match="decision reasons and status disagree"):
        Decision(
            policy_version="domestic-common-stock-v2",
            status=Eligibility.ELIGIBLE,
            reasons=(
                Reason(code="NON_ETP_BY_ST_GROUP", description="분류 근거만 존재", kind="evidence"),
            ),
        )

"""Versioned candidate screening with security-group evidence and conditional ETP checks."""

from __future__ import annotations

import re

from phalanx.domain.discovery import Candidate, Decision, Eligibility, Reason

POLICY_VERSION = "domestic-common-stock-v2"
# Meanings verified in the pinned KIS headers; newer undocumented codes remain unknown.
SECURITY_GROUPS = frozenset(
    {"ST", "MF", "RT", "SC", "IF", "DR", "EW", "EF", "SW", "SR", "BC", "FE", "FS"}
)


def evaluate(record: Candidate, *, conflicts: tuple[Reason, ...] = ()) -> Decision:
    reasons = list(conflicts)

    def unknown(field: str, value: str | None) -> None:
        missing = value is None or not value.strip()
        reasons.append(
            Reason(
                code="MISSING_REQUIRED_FIELD" if missing else "UNSUPPORTED_CODE",
                description=("필수 정보 누락" if missing else "지원하지 않는 값") + f": {field}",
                field=field,
                kind="unknown",
            )
        )

    def exclude(code: str, description: str, field: str) -> None:
        reasons.append(Reason(code=code, description=description, field=field, kind="exclude"))

    for field, value, pattern in (
        ("short_code", record.short_code, r"[A-Z0-9]{6,9}"),
        ("standard_code", record.standard_code, r"[A-Z0-9]{12}"),
        ("name", record.name, r".+"),
    ):
        if value is None or re.fullmatch(pattern, value) is None:
            unknown(field, value)

    if record.security_group not in SECURITY_GROUPS:
        unknown("scrt_grp_cls_code", record.security_group)
    elif record.security_group != "ST":
        exclude(
            "NON_DOMESTIC_ORDINARY_EQUITY", "국내 일반 주권 이외의 증권그룹", "scrt_grp_cls_code"
        )

    if record.preferred_class in {"1", "2"}:
        exclude("PREFERRED_STOCK", "우선주", "prst_cls_code")
    elif record.preferred_class != "0":
        unknown("prst_cls_code", record.preferred_class)

    etp_codes = {"1", "2", "3", "4", "5"} if record.market == "KOSPI" else {"1", "2", "3", "4"}
    if record.etp_class in etp_codes:
        exclude("ETP", "ETP 상품", "etp_prod_cls_code")
    elif record.etp_class is None and record.security_group == "ST":
        # ST is an independent official security category (distinct from EF/FE).
        # This scopes the policy requirement; it does not decode a blank as zero.
        # Nonblank unsupported codes and explicit ETP positives still take precedence.
        reasons.append(
            Reason(
                code="NON_ETP_BY_ST_GROUP",
                description=(
                    "ETP 공백을 보존하고 공식 ST 주권 분류를 비ETP의 독립 근거로 사용합니다."
                ),
                field="scrt_grp_cls_code",
                kind="evidence",
            )
        )
    elif record.etp_class != "0":
        unknown("etp_prod_cls_code", record.etp_class)

    for flag_value, field, code, description in (
        (record.spac, "etpr_undt_objt_co_yn", "SPAC", "기업인수목적회사(SPAC)"),
        (record.trading_halted, "trht_yn", "TRADING_HALTED", "거래정지"),
        (record.liquidation_trading, "sltr_yn", "LIQUIDATION_TRADING", "정리매매"),
        (record.managed, "mang_issu_yn", "MANAGED_ISSUE", "관리종목"),
    ):
        if flag_value is True:
            exclude(code, description, field)
        elif flag_value is None:
            unknown(field, record.raw_fields.get(field))

    if (record.security_group == "ST" and record.etp_class in etp_codes) or (
        record.security_group in {"EF", "FE"} and record.etp_class == "0"
    ):
        reasons.append(
            Reason(
                code="CLASSIFICATION_CONFLICT",
                description="증권그룹과 ETP 분류가 충돌합니다.",
                kind="unknown",
            )
        )
    if any(r.kind == "exclude" for r in reasons):
        status = Eligibility.EXCLUDED
    elif any(r.kind == "unknown" for r in reasons):
        status = Eligibility.UNKNOWN
    else:
        status = Eligibility.ELIGIBLE
        reasons.append(
            Reason(code="V2_PASSED", description="v2 필수 조건을 모두 확인했습니다.", kind="pass")
        )
    return Decision(policy_version=POLICY_VERSION, status=status, reasons=tuple(reasons))

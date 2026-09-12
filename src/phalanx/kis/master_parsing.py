"""Strict CP949 byte parsing, with one observable outcome for every physical record."""

from phalanx.domain.discovery import Candidate, Market, ParsedMaster, ParseIssue
from phalanx.kis.master_schema import FIELDS


def parse_master(market: Market, payload: bytes) -> ParsedMaster:
    fields = FIELDS[market]
    expected_size = sum(width for _, width in fields)
    lines = payload.split(b"\n") if payload else []
    if lines and lines[-1] == b"":
        lines.pop()
    records: list[Candidate] = []
    issues: list[ParseIssue] = []
    if not lines:
        issues.append(ParseIssue(code="EMPTY_MASTER", description="마스터 파일이 비어 있습니다."))
    for number, line in enumerate(lines, 1):
        if line.endswith(b"\r"):
            line = line[:-1]
        if len(line) != expected_size:
            issues.append(
                ParseIssue(
                    code="RECORD_WIDTH",
                    description=f"레코드 길이 오류: 기대 {expected_size}, 실제 {len(line)} 바이트",
                    line_number=number,
                )
            )
            continue
        offset = 0
        raw: dict[str, str] = {}
        try:
            for name, width in fields:
                encoding = "cp949" if name == "hts_kor_isnm" else "ascii"
                decoded = line[offset : offset + width].decode(encoding)
                if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
                    raise ValueError("control character")
                raw[name] = decoded
                offset += width
        except (UnicodeError, ValueError):
            issues.append(
                ParseIssue(
                    code="RECORD_ENCODING",
                    description="CP949·ASCII 인코딩 또는 제어문자 오류",
                    line_number=number,
                )
            )
            continue

        def value(name: str, fields: dict[str, str] = raw) -> str | None:
            return fields[name].strip() or None

        def flag(name: str, fields: dict[str, str] = raw) -> bool | None:
            return {"Y": True, "N": False}.get(fields[name])

        records.append(
            Candidate(
                market=market,
                line_number=number,
                short_code=value("mksc_shrn_iscd"),
                standard_code=value("stnd_iscd"),
                name=value("hts_kor_isnm"),
                security_group=value("scrt_grp_cls_code"),
                preferred_class=value("prst_cls_code"),
                etp_class=value("etp_prod_cls_code"),
                spac=flag("etpr_undt_objt_co_yn"),
                trading_halted=flag("trht_yn"),
                liquidation_trading=flag("sltr_yn"),
                managed=flag("mang_issu_yn"),
                raw_fields=raw,
            )
        )
    return ParsedMaster(total_lines=len(lines), records=tuple(records), issues=tuple(issues))

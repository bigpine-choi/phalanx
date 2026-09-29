"""Godot snapshot adapter to the existing Phalanx Python calculation engine.

No KIS/account calls or persisted research jobs. HistoryJob here is an ephemeral
adapter input explicitly marked godot_snapshot, not a market discovery result.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import math
import re
from urllib.parse import urlparse

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.discovery import Market
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_history import HistoryJob, HistoryResult, HistoryTarget, SymbolHistory, SymbolStatus, price_data_hash
from phalanx.market_data.features.calculation import calculate_price_features

CODES = {"005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차", "035420": "NAVER", "069500": "KODEX 200"}
ALLOWED_HOSTS = {"images.samsung.com", "dart.fss.or.kr", "github.com"}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(value):
        raise ValueError("invalid number")
    return Decimal(str(value))


def public_url(url):
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS and not parsed.username and not parsed.password and parsed.port in (None, 443) else ""


def pct(value):
    return f"{value * 100:+.2f}%"


def volume(value):
    result = number(value)
    if result != result.to_integral_value():
        raise ValueError("fractional volume")
    return int(result)


def build_report(context, now=None):
    now = now or datetime.now(UTC)
    code = context.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9A-Z]{6}", code) or context.get("mode") not in {"brief", "counter", "review"}:
        raise ValueError("invalid selection")
    name = CODES.get(code, context.get("name", code))
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError("invalid security name")
    note = context.get("note", "")
    draft = context.get("draft", {})
    if not isinstance(note, str) or len(note) > 8000 or not isinstance(draft, dict):
        raise ValueError("invalid text")
    if any(not isinstance(draft.get(k, ""), str) or len(draft.get(k, "")) > limit for k, limit in [("title", 80), ("rationale", 2000), ("risk", 2000)]):
        raise ValueError("invalid draft")
    report = {"version": 1, "code": code, "name": name, "mode": context["mode"],
              "created_at": now.isoformat(), "facts": [], "sources": [], "missing": [],
              "analysis": [], "ai_state": "not_requested", "calculator": "Phalanx Python · Decimal 50자리"}

    def source(identifier, label, as_of, detail, kind, url=""):
        report["sources"].append({"id": identifier, "label": label, "as_of": as_of, "detail": detail, "kind": kind, "url": public_url(url) if url else ""})

    def fact(title, text, refs):
        report["facts"].append({"title": title, "text": text, "source_ids": refs})

    quote = context.get("quote", {})
    with localcontext(financial_decimal_context()):
        if quote:
            if quote.get("code") != code or quote.get("currency") != "KRW" or not 2 <= len(quote.get("candles", [])) <= 300:
                raise ValueError("invalid quote")
            bars = tuple(DailyBar(stock_code=code, trade_date=date.fromisoformat(row["date"]),
                                 open_price=number(row["open"]), high_price=number(row["high"]),
                                 low_price=number(row["low"]), close_price=number(row["close"]), volume=volume(row["volume"])) for row in quote["candles"])
            fetched = number(quote["fetched_at"])
            if fetched <= 0 or fetched > Decimal(str(now.timestamp() + 60)) or quote.get("as_of") != bars[-1].trade_date.isoformat() or bars[-1].trade_date > now.date():
                raise ValueError("invalid quote date")
            digest = price_data_hash(bars)
            history = HistoryResult(bars=bars, row_count=len(bars), first_trade_date=bars[0].trade_date, last_trade_date=bars[-1].trade_date, sha256=digest)
            job = HistoryJob(job_id=digest[:32], created_at=now, discovery_run_id="godot_snapshot_no_discovery",
                             discovery_started_at=now, discovery_completed_at=now,
                             start=bars[0].trade_date, end=bars[-1].trade_date,
                             targets=(HistoryTarget(market=Market.KOSPI, short_code=code, standard_code=None, name=name, policy_version="godot_research_snapshot_v1", source_files=()),))
            features = calculate_price_features(job, (SymbolHistory(ordinal=0, status=SymbolStatus.COMPLETED, result=history),), as_of=bars[-1].trade_date, calculated_at=now)
            symbol = features.symbols[0]
            report["price_features"] = features.model_dump(mode="json")
            # The legacy pure calculator requires an exchange enum but does not use
            # it in arithmetic. Never publish that placeholder as verified metadata.
            if code not in CODES:
                report["price_features"]["symbols"][0]["target"].pop("market", None)
                report["price_features"]["market_classification"] = "not_verified"
            received = datetime.fromtimestamp(float(fetched), timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
            source("Q", "KIS 수정주가 일봉", quote["as_of"], f"전체 {len(bars)}개 일봉 중 각 지표에 필요한 기간을 사용\n수신 {received}\n배당 제외 가격 수익률 · 거래일 누락 미검증", "quote", quote.get("source_url", ""))
            fact("마지막 관측 종가", f"{bars[-1].close_price:,.0f}원 · 이전 관측 대비 {pct(bars[-1].close_price / bars[-2].close_price - 1)}", ["Q"])
            names = {"price_return": "가격 수익률", "annualized_volatility": "연환산 변동성", "maximum_drawdown": "최대 낙폭"}
            for metric in symbol.metrics:
                if (metric.name, metric.intervals) not in {("price_return", 20), ("price_return", 60), ("annualized_volatility", 20), ("maximum_drawdown", 60)}:
                    continue
                title = f"{metric.intervals}관측 구간 {names[metric.name]}"
                if metric.available:
                    fact(title, f"{pct(metric.value)} · {metric.window_start} → {metric.window_end}", ["Q"])
                else:
                    report["missing"].append(title + ": " + metric.reason)
            if (now.date() - bars[-1].trade_date).days > 4 or now.timestamp() - float(fetched) > 86400:
                report["missing"].append("오래된 일봉/캐시입니다. 최신 거래일 반영 여부를 확인하세요.")
        else:
            report["missing"].append("일봉 자료 없음 · 가격 수익률·변동성·낙폭 미산출")

        financials = context.get("financials", {})
        if financials:
            rows = financials.get("rows", [])
            if financials.get("code") != code or financials.get("currency") != "KRW" or not 1 <= len(rows) <= 10:
                raise ValueError("invalid financials")
            years = [row["year"] for row in rows]
            if years != sorted(set(years)) or any(not 1990 <= y <= now.year for y in years):
                raise ValueError("invalid financial years")
            for row in rows:
                sid = "F" + str(row["year"])
                parts = []
                for key, label in [("revenue", "매출"), ("operating_profit", "영업이익"), ("operating_cash_flow", "영업현금흐름")]:
                    if row.get(key) is not None:
                        parts.append(f"{label} {number(row[key]) / Decimal('1e12'):.2f}조원")
                source(sid, f"{row['year']}년 연결 재무", str(row["year"]), " · ".join(parts) + "\n" + str(financials.get("source", "")) + " · 연간 자료", "financial", row.get("source_url", ""))
                if row.get("cash_flow_url"):
                    source(sid + "C", f"{row['year']}년 현금흐름", str(row["year"]), "영업현금흐름 " + (f"{number(row['operating_cash_flow']) / Decimal('1e12'):.2f}조원" if row.get("operating_cash_flow") is not None else "자료 없음"), "financial", row["cash_flow_url"])
            last = rows[-1]
            refs = ["F" + str(last["year"])]
            if last.get("revenue") is not None and last.get("operating_profit") is not None and number(last["revenue"]) > 0:
                fact(f"{last['year']}년 영업이익률", f"{number(last['operating_profit']) / number(last['revenue']) * 100:.2f}% · 연간 연결 기준", refs)
            if len(rows) >= 2 and rows[-2]["year"] == last["year"] - 1:
                previous = rows[-2]
                for key, label in [("revenue", "매출"), ("operating_profit", "영업이익")]:
                    if last.get(key) is not None and previous.get(key) is not None and number(previous[key]) > 0:
                        fact(f"{last['year']}년 {label} 변화", pct(number(last[key]) / number(previous[key]) - 1) + " · 전년 연간 대비", [*refs, "F" + str(previous["year"])])
            report["missing"].append("재무는 연간 자료입니다. 최신 분기·공시·뉴스·컨센서스·PER/PBR은 포함하지 않습니다.")
        else:
            report["missing"].append("기업 재무자료 없음 · 실적과 가치평가 해석에 제한")

        if note.strip():
            source("N", "내 투자 가설", "요청 시점", note, "note")
        elif context["mode"] == "counter":
            report["missing"].append("반박할 투자 가설이 없습니다. 리서치 노트를 먼저 작성하세요.")
        if context["mode"] == "review":
            plan = context.get("plan", {})
            if plan:
                rows = plan.get("rows", [])
                if plan.get("source") != "실계좌 조회 기반 모의 계획 · 실제 주문 미연결" or not 1 <= len(rows) <= 100:
                    raise ValueError("invalid live plan")
                codes = [r.get("code") for r in rows]
                if any(not isinstance(c, str) or not c or len(c)>32 for c in codes) or len(set(codes))!=len(codes):
                    raise ValueError("invalid plan codes")
                if any(not isinstance(r.get("name"),str) or not 1<=len(r["name"])<=200 for r in rows):
                    raise ValueError("invalid plan names")
                total = sum((number(r["target"]) for r in rows), Decimal(0))
                if any(not 0 <= number(r["target"]) <= 100 for r in rows) or total > Decimal('100.0001'):
                    raise ValueError("invalid weights")
                source("P", "실계좌 기반 모의 목표 배분", str(plan.get("observed_at", "조회 시점")), "\n".join(f"{r['name']} ({r['code']}) {number(r['target']):.2f}%" for r in rows) + "\n투입 현금은 사용자 가정 · 금액·수량·계좌번호 제외 · 실제 주문 미연결", "plan")
                fact("목표 주식 / 잔여 비중", f"주식 {total:.2f}% · 잔여 목표 {100-total:.2f}% (정수주 계획 후 현금 비중과 다를 수 있음)", ["P"])
            else:
                report["missing"].append("적용한 실계좌 변경안이 없습니다. 포트폴리오에서 계산 후 명령서에 적용하세요.")
            source("D", "작성 중인 명령서", "요청 시점", "\n".join(f"{k}: {draft.get(k, '')}" for k in ("title", "rationale", "risk")), "draft")
        report["missing"].append("공시/뉴스를 자동 검색하지 않습니다. 제공된 자료 밖의 가격 변동 원인은 확인할 수 없습니다.")
    return report

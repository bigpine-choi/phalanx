"""Read-only, single-observation allocation planning; no broker or orders."""
from decimal import Decimal, ROUND_FLOOR, localcontext
import hashlib
import json
import re

from phalanx.decimal_math import financial_decimal_context
from phalanx.portfolio.self_financing import (
    SelfFinancingTransitionInput, apply_fractional_self_financing_transition,
)

LIVE_SOURCE = "실계좌 조회 기반 모의 계획 · 실제 주문 미연결"


class PlanError(ValueError):
    pass


def number(value, low=Decimal(0), high=Decimal("1000000000000")):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PlanError("INPUT_INVALID")
    try:
        result = Decimal(str(value))
    except Exception:
        raise PlanError("INPUT_INVALID") from None
    if not result.is_finite() or not low <= result <= high:
        raise PlanError("INPUT_INVALID")
    return result


def simulate(context):
    with localcontext(financial_decimal_context()):
        return _simulate(context)


def _simulate(context):
    account = context.get("account", {})
    if account.get("source") != "kis_account" or account.get("currency") != "KRW":
        raise PlanError("INPUT_INVALID")
    rows = account.get("rows")
    targets = context.get("targets")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100 or not isinstance(targets, dict):
        raise PlanError("NO_HOLDINGS")
    codes = [r.get("code") for r in rows]
    if any(not isinstance(c, str) or not re.fullmatch(r"[A-Za-z0-9]{1,32}", c) for c in codes) or len(set(codes)) != len(codes) or set(targets) != set(codes):
        raise PlanError("INPUT_INVALID")
    quantities = tuple(number(r.get("quantity")) for r in rows)
    prices = tuple(number(r.get("price"), Decimal("0.0001")) for r in rows)
    sellable = tuple(number(r.get("sellable")) for r in rows)
    if any(q != q.to_integral_value() or s != s.to_integral_value() or s > q for q, s in zip(quantities, sellable)):
        raise PlanError("QUANTITY_INVALID")
    if any(not isinstance(r.get("name"), str) or not 1 <= len(r["name"]) <= 200 for r in rows):
        raise PlanError("INPUT_INVALID")
    weights = tuple(number(targets[c], high=Decimal(100)) / 100 for c in codes)
    equity = sum(weights)
    if equity > 1:
        raise PlanError("OVER_ALLOCATED")
    cash = number(context.get("cash_assumption"))
    holdings_value = sum(q * p for q, p in zip(quantities, prices))
    nav = holdings_value + cash
    if nav <= 0 or nav > Decimal("1000000000000"):
        raise PlanError("INPUT_INVALID")
    keep = context.get("keep_holdings", False)
    if type(keep) is not bool:
        raise PlanError("INPUT_INVALID")
    if keep:
        exact = tuple(q*p/nav for q,p in zip(quantities,prices))
        if any(abs(w-e)>Decimal("0.000101") for w,e in zip(weights,exact)):
            raise PlanError("INPUT_INVALID")
        # The shared kernel requires an exact Decimal sum. Recurring ratios at
        # the full 50-digit precision can lose a final digit when added, so
        # reserve addition headroom before reconciling the cash-free residual.
        weights = tuple(w.quantize(Decimal("1e-30"), rounding=ROUND_FLOOR) for w in exact)
        equity = sum(weights)
        # Preserve an exact 100% sum at the Decimal boundary.
        if cash==0:
            weights = (*weights[:-1], Decimal(1)-sum(weights[:-1]))
            equity = Decimal(1)
    # Reuse the existing public accounting kernel. It computes a continuous
    # target; the adapter reconciles the displayed one-share plan separately.
    if keep:
        # A hold decision is an exact no-op, not a fractional rebalance.
        after = tuple(int(q) for q in quantities)
        engine = "portfolio adapter · 현재 보유량 유지"
    elif equity > 0:
        transition = apply_fractional_self_financing_transition(SelfFinancingTransitionInput(
            current_quantities=quantities, cash_before=cash, valuation_prices=prices,
            target_weights=weights, target_equity_weight=equity,
            buy_cost_rate=Decimal(0), sell_cost_rate=Decimal(0)))
        if transition.pre_trade_nav != nav or transition.post_trade_nav != nav:
            raise PlanError("ACCOUNTING_FAILED")
        # The no-cost target notionals are exact finite Decimals, avoiding a
        # fractional quantity just below an integer due to division rounding.
        after = tuple(int((nav * w / p).to_integral_value(rounding=ROUND_FLOOR)) for w, p in zip(weights, prices))
        engine = "phalanx.portfolio.self_financing.apply_fractional_self_financing_transition"
    else:
        after = tuple(0 for _ in rows)
        engine = "portfolio adapter · 전량 현금 시나리오"
    differences = tuple(Decimal(a) - q for a, q in zip(after, quantities))
    if any(-d > s for d, s in zip(differences, sellable)):
        raise PlanError("SELLABLE_EXCEEDED")
    buys = sum(d*p for d,p in zip(differences,prices) if d > 0)
    sells = sum(-d*p for d,p in zip(differences,prices) if d < 0)
    remaining = cash + sells - buys
    values_after = tuple(Decimal(a)*p for a,p in zip(after,prices))
    if remaining < 0 or remaining + sum(values_after) != nav:
        raise PlanError("ACCOUNTING_FAILED")
    result_rows = []
    for i, row in enumerate(rows):
        before_weight = quantities[i]*prices[i]/nav*100
        after_weight = values_after[i]/nav*100
        result_rows.append({"code":row["code"], "name":row["name"], "price":float(prices[i]),
            "quantity":int(quantities[i]), "result_quantity":after[i], "delta":int(differences[i]),
            "amount":float(abs(differences[i])*prices[i]), "target":float(weights[i]*100),
            "before_weight":float(before_weight), "after_weight":float(after_weight),
            "before_value":float(quantities[i]*prices[i]), "after_value":float(values_after[i])})
    input_hash = hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    warnings = ["조회 가격 고정 · 수수료·세금·체결 오차 제외", "투입 현금은 사용자 가정이며 주문가능금액이 아닙니다."]
    largest_before = max(r["before_weight"] for r in result_rows)
    largest_after = max(r["after_weight"] for r in result_rows)
    if largest_after > 30:
        warnings.append("단일 종목 비중이 30%를 넘습니다. 집중도를 검토하세요.")
    if remaining/nav < Decimal("0.05"):
        warnings.append("계획상 현금 비중이 5% 미만입니다.")
    if buys > cash:
        warnings.append("모의 매도 대금을 재사용하는 가정입니다. 결제·주문가능금액은 별도 확인이 필요합니다.")
    plan = {"source":LIVE_SOURCE,
        "base_cash":float(cash),"base_assets":float(nav),"planned_cash":float(remaining),
        "target_total":float(equity*100),"rows":result_rows,
        "snapshot_id":account.get("snapshot_id","demo"),"observed_at":account.get("observed_at","샘플"),
        "cash_basis":"사용자 입력 가정 · 주문가능현금 미확인"}
    return {"version":1,"input_hash":input_hash,"plan":plan,"engine":engine,
        "buy_total":float(buys),"sell_total":float(sells),
        "before_cash_weight":float(cash/nav*100),"after_cash_weight":float(remaining/nav*100),
        "largest_before":largest_before,"largest_after":largest_after,
        "gross_turnover":float((buys+sells)/nav*100),"warnings":warnings,
        "analysis":[],"ai_state":"not_requested"}


def review_report(result):
    """Only holdings names/codes and percentage changes leave the computer."""
    plan = result["plan"]
    facts = [{"title":"비중 변경안", "text":"\n".join(
        f'{r["name"]} ({r["code"]}): {r["before_weight"]:.2f}% → {r["after_weight"]:.2f}%'
        for r in plan["rows"]),"source_ids":["P"]},
        {"title":"현금과 집중도", "text":f'계획 현금 비중 {result["before_cash_weight"]:.2f}% → {result["after_cash_weight"]:.2f}%. 최대 단일종목 비중 {result["largest_before"]:.2f}% → {result["largest_after"]:.2f}%.',"source_ids":["P"]}]
    return {"code":"PORTFOLIO", "facts":facts,
        "sources":[{"id":"P","label":"사용자가 작성한 모의 배분안","as_of":"요청 시점",
                    "detail":"실계좌 조회 비중을 바탕으로 한 모의 변경안. 현금은 사용자 가정. 금액·수량·계좌번호는 제공하지 않음."}],
        "missing":result["warnings"]+["기간 수익률·변동성·상관관계·ETF 내부 구성은 계산하지 않았습니다. 비중 변화만 검토하세요."]}

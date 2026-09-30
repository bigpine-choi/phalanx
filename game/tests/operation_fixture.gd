extends RefCounted
## Isolated test data only. Never loaded by the game.

const Record = preload("res://scripts/operation_record.gd")
const SOURCE = Record.SOURCE
const CASH := 30930000.0
const STOCKS := [
	{"code": "005930", "name": "삼성전자", "sector": "반도체 · KOSPI", "price": 72000.0, "change": 1.69, "quantity": 200, "average": 68000.0, "target": 18.0, "score": 82, "thesis": "메모리 업황 회복과 현금 창출력을 관찰합니다.", "risk": "수요 회복 속도와 설비투자 부담을 점검합니다."},
	{"code": "000660", "name": "SK하이닉스", "sector": "반도체 · KOSPI", "price": 172000.0, "change": 2.38, "quantity": 80, "average": 164000.0, "target": 16.0, "score": 88, "thesis": "고부가 메모리 제품의 매출 비중을 관찰합니다.", "risk": "고객 집중도와 높은 가격 변동성을 점검합니다."},
	{"code": "005380", "name": "현대차", "sector": "자동차 · KOSPI", "price": 245000.0, "change": -0.81, "quantity": 100, "average": 252000.0, "target": 22.0, "score": 76, "thesis": "제품 구성 개선과 주주환원 흐름을 관찰합니다.", "risk": "환율 변동과 지역별 수요 둔화를 점검합니다."},
	{"code": "035420", "name": "NAVER", "sector": "인터넷 · KOSPI", "price": 192000.0, "change": -1.03, "quantity": 30, "average": 186000.0, "target": 8.0, "score": 73, "thesis": "광고와 커머스의 수익성 변화를 관찰합니다.", "risk": "경쟁 심화와 신규 사업 투자 부담을 점검합니다."},
	{"code": "069500", "name": "KODEX 200", "sector": "시장지수 · ETF", "price": 35500.0, "change": 0.57, "quantity": 300, "average": 34200.0, "target": 14.0, "score": 79, "thesis": "국내 대형주에 분산되는 포트폴리오 역할을 확인합니다.", "risk": "시장 전체 하락과 대형주 편중을 점검합니다."}
]

static func total_assets() -> float:
	var total := CASH
	for stock in STOCKS:
		total += stock.price * stock.quantity
	return total

static func profit() -> float:
	var total := 0.0
	for stock in STOCKS:
		total += (stock.price - stock.average) * stock.quantity
	return total

static func money(value: float) -> String:
	var digits := str(absi(roundi(value)))
	var result := ""
	for i in range(digits.length()):
		if i > 0 and (digits.length() - i) % 3 == 0:
			result += ","
		result += digits[i]
	return ("-" if value < 0 else "") + result

static func plan(targets: Array) -> Dictionary:
	var target_total := 0.0
	for target in targets:
		target_total += float(target)
	if targets.size() != STOCKS.size() or target_total > 100.0001:
		return {"valid": false, "reason": "목표 비중 합계가 100%를 초과했습니다."}
	var rows: Array = []
	var remaining := CASH
	for i in range(STOCKS.size()):
		var stock: Dictionary = STOCKS[i]
		var target := float(targets[i])
		if not is_finite(target) or target < 0.0 or target > 100.0:
			return {"valid": false, "reason": "목표 비중은 0~100%여야 합니다."}
		var desired := floori(total_assets() * target / 100.0 / stock.price)
		var delta: int = desired - int(stock.quantity)
		remaining -= delta * stock.price
		rows.append({"name": stock.name, "delta": delta, "amount": absf(delta * stock.price), "target": target, "result_quantity": desired})
	return {"valid": remaining >= 0.0, "rows": rows, "cash": remaining, "target_total": target_total}


static func snapshot(targets: Array) -> Dictionary:
	var plan: Dictionary = plan(targets)
	if not plan.valid:
		return {}
	var rows: Array = []
	for i: int in STOCKS.size():
		var stock: Dictionary = STOCKS[i]
		var row: Dictionary = plan.rows[i].duplicate(true)
		row.code = stock.code
		row.price = stock.price
		row.quantity = stock.quantity
		rows.append(row)
	return {"source":SOURCE, "base_cash":CASH, "base_assets":total_assets(), "planned_cash":plan.cash, "target_total":plan.target_total, "rows":rows}

static func create(targets: Array, draft: Dictionary) -> Dictionary:
	return Record.from_snapshot(live_plan(targets),draft)


static func live_plan(targets: Array = [18,16,22,8,14]) -> Dictionary:
	var plan := snapshot(targets)
	if plan.is_empty(): return {}
	plan.source = Record.LIVE_SOURCE
	plan.snapshot_id = "a".repeat(64)
	plan.observed_at = "2026-09-29T12:00:00+00:00"
	plan.cash_basis = "사용자 입력 가정 · 주문가능현금 미확인"
	return plan

static func install(view: Control, target := 20.0) -> void:
	view.simulation_plan = live_plan([target,16,22,8,14])
	view._queue_profile_save()
	view._sync_advisor()

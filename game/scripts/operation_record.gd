extends RefCounted
## Immutable live-account simulation records; old sample records are read-only history.
const MAX_OPERATIONS := 200
const MAX_TEXT := 2000
const SOURCE := "가상 계좌 · 샘플 시세 / 실제 주문 미연결"
const LIVE_SOURCE := "실계좌 조회 기반 모의 계획 · 실제 주문 미연결"

static func empty_draft() -> Dictionary:
	return {"title":"포트폴리오 재배치", "rationale":"", "risk":""}

static func valid_draft(value: Variant, required := false) -> bool:
	if not value is Dictionary:
		return false
	for key: String in ["title","rationale","risk"]:
		if not value.get(key) is String or value[key].length() > (80 if key == "title" else MAX_TEXT):
			return false
		if required and value[key].strip_edges().is_empty():
			return false
	return true

static func number(value: Variant, minimum := 0.0, maximum := 1e15) -> bool:
	return (value is float or value is int) and is_finite(float(value)) and float(value) >= minimum and float(value) <= maximum

static func valid_targets(value: Variant) -> bool:
	if not value is Dictionary or value.size() > 1000:
		return false
	for code: Variant in value:
		if not code is String or code.is_empty() or code.length() > 32 or not number(value[code],0,100):
			return false
	return true

static func from_snapshot(plan: Dictionary, draft: Dictionary) -> Dictionary:
	if plan.get("source") != LIVE_SOURCE or not valid_draft(draft,true):
		return {}
	var result := plan.duplicate(true)
	if result.is_empty():
		return {}
	result.id = Crypto.new().generate_random_bytes(16).hex_encode()
	result.created_at = int(Time.get_unix_time_from_system())
	result.local_time = Time.get_datetime_string_from_system(false,true)
	result.utc_offset = int(Time.get_time_zone_from_system().bias)
	for key: String in ["title","rationale","risk"]:
		result[key] = draft[key].strip_edges()
	return result if validate(result) else {}

static func validate(value: Variant) -> bool:
	if not valid_draft(value,true):
		return false
	if not value.get("id") is String or value.id.length() != 32 or not value.id.is_valid_hex_number():
		return false
	if not number(value.get("created_at"),1,1e12) or not number(value.get("utc_offset"),-840,840):
		return false
	if not value.get("local_time") is String or value.local_time.length() != 19 or value.get("source") not in [SOURCE,LIVE_SOURCE]:
		return false
	if value.source==LIVE_SOURCE:
		if not value.get("snapshot_id") is String or value.snapshot_id.length()!=64 or not value.snapshot_id.is_valid_hex_number(): return false
		if not value.get("observed_at") is String or value.observed_at.length()>64 or value.observed_at.length()<19: return false
		if value.get("cash_basis")!="사용자 입력 가정 · 주문가능현금 미확인": return false
	for key: String in ["base_cash","base_assets","planned_cash","target_total"]:
		if not number(value.get(key)):
			return false
	if value.target_total > 100.0001 or not value.get("rows") is Array or value.rows.is_empty() or value.rows.size() > 100:
		return false
	var seen := {}
	var cash: float = value.base_cash
	var assets: float = value.base_cash
	var target_sum := 0.0
	for row: Variant in value.rows:
		if not row is Dictionary or not row.get("code") is String or row.code.is_empty() or row.code.length() > 32 or seen.has(row.code):
			return false
		seen[row.code] = true
		if not row.get("name") is String or row.name.is_empty() or row.name.length() > 200:
			return false
		for key: String in ["price","quantity","result_quantity","amount","target"]:
			if not number(row.get(key)):
				return false
		if row.price <= 0 or row.target > 100 or not number(row.get("delta"),-1e12,1e12):
			return false
		for key: String in ["quantity","result_quantity","delta"]:
			if float(row[key]) != floorf(float(row[key])):
				return false
		if absf(row.result_quantity-row.quantity-row.delta) > 0.001 or absf(absf(row.delta)*row.price-row.amount) > 0.01:
			return false
		cash -= row.delta * row.price
		assets += row.quantity * row.price
		target_sum += row.target
	return absf(cash-value.planned_cash) <= 0.01 and absf(assets-value.base_assets) <= 0.01 and absf(target_sum-value.target_total) <= 0.0001

static func dated_label(record: Dictionary) -> String:
	var bias := int(record.utc_offset)
	return "%s  UTC%s%02d:%02d" % [record.local_time,"+" if bias>=0 else "-",absi(bias)/60,absi(bias)%60]

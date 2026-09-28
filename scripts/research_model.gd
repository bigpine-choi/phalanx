extends RefCounted
## Public research data only. Never used to value or trade the demo account.
const CODES := ["005930","000660","005380","035420","069500"]
const CORPS := {"005930":"00126380","000660":"00164779","005380":"00164742","035420":"00266961"}
const IR_ROOT := "https://images.samsung.com/is/content/samsung/assets/global/ir/docs/"
const KIS_SOURCE := "https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_daily_itemchartprice"

static func parse_kis(payload: Variant, code: String, now: int) -> Dictionary:
	if not payload is Dictionary or not code in CODES or payload.get("code")!=code or payload.get("provider")!="KIS" or payload.get("currency")!="KRW" or payload.get("market")!="KRX" or payload.get("adjusted")!=true:
		return {}
	if not numeric(payload.get("fetched_at")) or payload.fetched_at<=0 or payload.fetched_at>now+60:
		return {}
	var rows: Variant = payload.get("candles")
	if not rows is Array or rows.size()<2 or rows.size()>300:
		return {}
	var start: Variant = payload.get("requested_start")
	var end: Variant = payload.get("requested_end")
	if not valid_date(start) or not valid_date(end) or start>end or end>=kst_date(int(payload.fetched_at)):
		return {}
	var candles: Array = []
	var previous := ""
	for input: Variant in rows:
		if not input is Dictionary or not valid_date(input.get("date")):
			return {}
		var date: String = input.date
		if date<=previous or date<start or date>end:
			return {}
		previous = date
		for key: String in ["open","high","low","close","volume"]:
			if not numeric(input.get(key)):
				return {}
		if input.low<=0 or input.high<input.low or input.open<input.low or input.open>input.high or input.close<input.low or input.close>input.high or input.volume<0 or floorf(input.volume)!=input.volume:
			return {}
		candles.append({"date":date,"open":input.open,"high":input.high,"low":input.low,"close":input.close,"volume":input.volume})
	return {"code":code,"currency":"KRW","candles":candles,"fetched_at":int(payload.fetched_at),"as_of":candles[-1].date,"source":"한국투자증권 KIS","source_url":KIS_SOURCE,"adjustment":"KRX · 수정주가 일봉 · 당일 제외 · 거래일 누락 미검증"}

static func valid_date(value: Variant) -> bool:
	if not value is String or value.length()!=10 or value[4]!="-" or value[7]!="-":
		return false
	var compact: String = value.replace("-","")
	if compact.length()!=8 or not compact.is_valid_int() or int(value.left(4))<1990:
		return false
	var year := int(value.left(4))
	var month := int(value.substr(5,2))
	var day := int(value.right(2))
	if month<1 or month>12:
		return false
	var days := [31,29 if year%400==0 or (year%4==0 and year%100!=0) else 28,31,30,31,30,31,31,30,31,30,31]
	return day>=1 and day<=days[month-1]

static func numeric(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))

static func kst_date(timestamp: int) -> String:
	return Time.get_datetime_string_from_unix_time(timestamp+9*3600).left(10)

static func amount(value: Variant) -> Variant:
	if not value is String:
		return null
	var cleaned: String = value.strip_edges().replace(",","")
	if cleaned.begins_with("(") and cleaned.ends_with(")"):
		cleaned = "-"+cleaned.substr(1,cleaned.length()-2)
	return float(cleaned) if cleaned.is_valid_int() else null

static func parse_dart(payload: Variant, code: String, year: int) -> Dictionary:
	if not payload is Dictionary or payload.get("status")!="000" or not payload.get("list") is Array or not CORPS.has(code):
		return {}
	var row := {"year":year,"revenue":null,"operating_profit":null,"operating_cash_flow":null,"receipt":""}
	var identifiers := {"ifrs-full_Revenue":"revenue","ifrs_Revenue":"revenue","dart_OperatingIncomeLoss":"operating_profit","ifrs-full_CashFlowsFromUsedInOperatingActivities":"operating_cash_flow","ifrs_CashFlowsFromUsedInOperatingActivities":"operating_cash_flow"}
	var names := {"매출액":"revenue","수익(매출액)":"revenue","영업이익":"operating_profit","영업이익(손실)":"operating_profit","영업활동현금흐름":"operating_cash_flow","영업활동으로인한현금흐름":"operating_cash_flow"}
	var priority := {}
	for entry: Variant in payload.list:
		if not entry is Dictionary or entry.get("corp_code")!=CORPS[code] or str(entry.get("bsns_year"))!=str(year) or entry.get("reprt_code")!="11011":
			return {}
		var receipt: String = str(entry.get("rcept_no",""))
		if receipt.length()!=14 or not receipt.is_valid_int() or (not row.receipt.is_empty() and row.receipt!=receipt):
			return {}
		row.receipt = receipt
		var metric: String = identifiers.get(entry.get("account_id",""),names.get(str(entry.get("account_nm","")).replace(" ",""),""))
		if metric.is_empty() or entry.get("currency")!="KRW":
			continue
		if metric=="operating_cash_flow" and entry.get("sj_div")!="CF":
			continue
		if metric!="operating_cash_flow" and not entry.get("sj_div") in ["IS","CIS"]:
			continue
		var score := (2 if identifiers.has(entry.get("account_id","")) else 0)+(1 if entry.get("sj_div")=="IS" else 0)
		if not priority.has(metric) or score>priority[metric]:
			row[metric] = amount(entry.get("thstrm_amount"))
			priority[metric] = score
	if row.revenue==null and row.operating_profit==null and row.operating_cash_flow==null:
		return {}
	row["source_url"] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+row.receipt
	return row

static func official_snapshot(code: String) -> Dictionary:
	if code!="005930":
		return {}
	# KRW millions transcribed from Samsung's consolidated financial statements;
	# 2023 comparative values: 2024 statements, 2024/25 values: 2025 statements.
	var rows: Array = []
	for input: Array in [[2023,258935494,6566976,44137427,2024],[2024,300870903,32725961,72982621,2025],[2025,333605938,43601051,85315148,2025]]:
		rows.append({"year":input[0],"source_year":input[4],"revenue":input[1]*1000000.0,"operating_profit":input[2]*1000000.0,"operating_cash_flow":input[3]*1000000.0,"source_url":IR_ROOT+str(input[4])+"_con_quarter04_soi.pdf","cash_flow_url":IR_ROOT+str(input[4])+"_con_quarter04_cf.pdf"})
	return {"code":code,"currency":"KRW","basis":"연결 · 연간","source":"삼성전자 공식 IR","mode":"verified_snapshot","verified_on":"2026-09-28","rows":rows}

static func trillion(value: Variant) -> String:
	return "자료 없음" if value==null else "%.2f조" % (float(value)/1e12)

static func margin(row: Dictionary) -> String:
	if row.get("revenue")==null or row.get("operating_profit")==null or row.revenue<=0:
		return "자료 없음"
	return "%.1f%%" % (row.operating_profit/row.revenue*100)

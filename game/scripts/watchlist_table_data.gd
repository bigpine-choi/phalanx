extends RefCounted
## Read-only presentation rows. Group membership and selection belong elsewhere.

static func build(securities: Array, account: Dictionary, gateway: Node, catalog_items: Array) -> Array:
	var catalogue := {}
	var duplicate_codes := {}
	for item: Dictionary in catalog_items:
		var code: String = item.get("code", "")
		if catalogue.has(code) or item.get("collision", false):
			duplicate_codes[code] = true
		catalogue[code] = item
	var holdings := {}
	for position: Dictionary in account.get("rows", []):
		holdings[position.code] = position
	var rows: Array = []
	for security: Dictionary in securities:
		var code: String = security.code
		var metadata: Dictionary = catalogue.get(code, {})
		var identity_conflict: bool = security.has("account_identity_conflict")
		if duplicate_codes.has(code) or (not metadata.is_empty() and metadata.get("name") != security.name):
			metadata = {} # Do not attach another identity's descriptive fields.
		var market: String = str(security.get("market", metadata.get("market", "—")))
		var kind: String = str(security.get("kind", metadata.get("kind", "—")))
		var held: bool = holdings.has(code) and not identity_conflict and holdings[code].get("name") == security.name
		var status := "미조회"
		var reason := "이 종목의 일봉은 아직 조회하지 않았습니다."
		if identity_conflict:
			status = "식별자 확인"
			reason = "같은 코드의 종목 식별자가 충돌해 연결을 보류합니다."
			if holdings.has(code):
				reason += "\n잔고 종목명: " + str(holdings[code].get("name", "—"))
		elif is_instance_valid(gateway):
			var quote: Dictionary = gateway.memory_quotes.get(code, {})
			if gateway.code == code:
				quote = gateway.quote
				var states := {"loading":"일봉 조회 중", "unsupported":"일봉 미지원", "error":"일봉 조회 실패", "stale":"이전 일봉", "cached":"저장된 일봉", "ready":"일봉 조회됨"}
				status = states.get(gateway.quote_state, "미조회")
				reason = gateway.quote_message
			elif not quote.is_empty():
				status = "저장된 일봉"
				reason = "이전에 조회한 일봉을 보관하고 있습니다."
			if not quote.is_empty():
				reason += "\n일봉 기준일 " + str(quote.get("as_of", "—"))
		if holdings.has(code):
			if status == "미조회": status = "잔고 조회됨"
			reason += "\n잔고 관측 " + str(account.get("observed_at", "—"))
		rows.append({"code":code,"name":security.name,"market":market if not market.is_empty() else "—",
			"kind":kind if not kind.is_empty() else "—","held":held,"account_present":holdings.has(code),
			"identity_conflict":identity_conflict,"status":status,"status_reason":reason})
	return rows

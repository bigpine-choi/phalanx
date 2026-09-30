extends RefCounted
## Public, read-only current price; never mix it into the KIS daily chart.
const Data = preload("res://scripts/market_data.gd")

static func valid_code(code: String) -> bool:
	if not Data.valid_code(code) or code.length()!=6:
		return false
	for letter: String in code:
		if letter<"0" or letter>"9":
			return false
	return true

static func parse(payload: Variant, code: String, now: int) -> Dictionary:
	return _parse(payload,code,now,false)


static func parse_cached(payload: Variant, code: String, now: int) -> Dictionary:
	# A saved price is useful as historical context, even after many days.
	return _parse(payload,code,now,true)


static func _whole_number(value: Variant) -> bool:
	return value is int or (value is float and is_finite(value) and floorf(value)==value)


static func _parse(payload: Variant, code: String, now: int, allow_old: bool) -> Dictionary:
	if not payload is Dictionary or not valid_code(code):
		return {}
	if payload.get("provider")!="NHPLUG" or payload.get("code")!=code or payload.get("market")!="KRX" or payload.get("currency")!="KRW":
		return {}
	var price: Variant = payload.get("price")
	var fetched: Variant = payload.get("fetched_at")
	if not _whole_number(price) or price<=0 or price>1000000000000:
		return {}
	if not _whole_number(fetched) or fetched<=0 or fetched>now+60 or (not allow_old and fetched<now-300):
		return {}
	return {"code":code,"price":int(price),"fetched_at":int(fetched),"source":"NH투자증권 NHPLUG","market":"KRX"}

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
	if not payload is Dictionary or not valid_code(code):
		return {}
	if payload.get("provider")!="NHPLUG" or payload.get("code")!=code or payload.get("market")!="KRX" or payload.get("currency")!="KRW":
		return {}
	var price: Variant = payload.get("price")
	var fetched: Variant = payload.get("fetched_at")
	if not price is int or price<=0 or price>1000000000000:
		return {}
	if not fetched is int or fetched<now-300 or fetched>now+60:
		return {}
	return {"code":code,"price":price,"fetched_at":fetched,"source":"NH투자증권 NHPLUG","market":"KRX"}

extends RefCounted
## Public catalogue metadata only; prices always come from observations.
const STOCKS := [
	{"code":"005930","name":"삼성전자","sector":"반도체 · KOSPI"},
	{"code":"000660","name":"SK하이닉스","sector":"반도체 · KOSPI"},
	{"code":"005380","name":"현대차","sector":"자동차 · KOSPI"},
	{"code":"035420","name":"NAVER","sector":"인터넷 · KOSPI"},
	{"code":"069500","name":"KODEX 200","sector":"시장지수 · ETF"}
]

static func money(value: float) -> String:
	var digits := str(absi(roundi(value)))
	var result := ""
	for i in range(digits.length()):
		if i > 0 and (digits.length() - i) % 3 == 0:
			result += ","
		result += digits[i]
	return ("-" if value < 0 else "") + result

static func valid_code(value: Variant) -> bool:
	if not value is String or value.length()!=6: return false
	for character: String in value:
		if not character in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ": return false
	return true

extends Node
## Selected security requests are serialized; stale replies never paint another stock.
signal changed
const Model = preload("res://scripts/research_model.gd")
const KisProcess = preload("res://scripts/kis_research_process.gd")
var kis: Node
var code := ""
var quote: Dictionary = {}
var financials: Dictionary = {}
var quote_state := "empty"
var financial_state := "empty"
var quote_message := ""
var financial_message := ""
var finance_http: HTTPRequest
var generation := 0
var requested_codes := {}
var memory_quotes := {}
var memory_financials := {}
var online := OS.get_environment("PHALANX_RESEARCH_OFFLINE")!="1"
var cache_dir := OS.get_environment("PHALANX_RESEARCH_CACHE")

func _ready() -> void:
	if cache_dir.is_empty():
		cache_dir = "user://research_cache"
	finance_http = HTTPRequest.new()
	finance_http.timeout = 15
	finance_http.body_size_limit = 4*1024*1024
	finance_http.max_redirects = 2
	add_child(finance_http)
	kis = KisProcess.new()
	kis.directory = ProjectSettings.globalize_path(cache_dir)
	add_child(kis)
	kis.completed.connect(_kis_completed)

func select_stock(value: String) -> void:
	if not Model.Data.valid_code(value) or value==code:
		return
	if quote_state=="loading":
		# A queued lookup can be superseded. Returning to it must fetch again.
		requested_codes.erase(code)
	generation += 1
	finance_http.cancel_request()
	code = value
	quote = memory_quotes.get(code,{})
	if quote.is_empty():
		quote = _read_quote_cache(code)
	financials = memory_financials.get(code,Model.official_snapshot(code))
	quote_state = "cached" if not quote.is_empty() else "empty"
	financial_state = ("snapshot" if financials.get("mode")=="verified_snapshot" else "cached") if not financials.is_empty() else "empty"
	quote_message = "저장된 일봉 · 새로고침으로 다시 조회" if not quote.is_empty() else "일봉을 조회하면 표시됩니다."
	financial_message = ("공식 IR에서 확인한 연간 재무 · 고정 자료" if financial_state=="snapshot" else "이전에 조회한 연간 연결 재무") if not financials.is_empty() else ("ETF에는 기업 재무제표를 적용하지 않습니다." if code=="069500" else ("자료 없음 · OpenDART 연결 후 조회할 수 있습니다." if Model.CORPS.has(code) else "자료 없음 · 이 종목의 공시 연결은 아직 준비되지 않았습니다."))
	changed.emit()

func activate() -> void:
	if not requested_codes.has(code):
		refresh()

func refresh() -> void:
	if not Model.Data.valid_code(code):
		return
	if not online:
		quote_message = "오프라인 · 저장된 일봉" if not quote.is_empty() else "오프라인 · 일봉 자료 없음"
		changed.emit()
		return
	generation += 1
	finance_http.cancel_request()
	requested_codes[code] = true
	var request_generation := generation
	_fetch_quote(code,request_generation)
	_fetch_financials(code,request_generation)

func _fetch_quote(request_code: String, token: int) -> void:
	quote_state = "loading"
	quote_message = "한국투자증권 일봉 조회 중…"
	changed.emit()
	kis.request(request_code,token)

func _kis_completed(request_code: String, token: int, payload: Dictionary) -> void:
	if token!=generation or request_code!=code:
		return
	var result := Model.parse_kis(payload,request_code,int(Time.get_unix_time_from_system()))
	if result.is_empty():
		_quote_failed("KIS 조회 실패 · 기존 WSL 연동/인증 상태를 확인하고 다시 시도해주세요.")
		return
	quote = result
	memory_quotes[code] = result
	quote_state = "ready"
	quote_message = "조회 완료 · 한국투자증권 · 전일까지의 일봉"
	if not _write_cache("kis_"+code,{"code":code,"fetched_at":result.fetched_at,"payload":payload}):
		quote_message += " · 캐시 저장 실패"
	changed.emit()

func _quote_failed(message: String) -> void:
	quote_state = "error" if quote.is_empty() else "stale"
	quote_message = message+(" 이전 일봉을 유지합니다." if not quote.is_empty() else "")
	changed.emit()

func _dart_key() -> String:
	var key := OS.get_environment("PHALANX_DART_KEY").strip_edges()
	var key_path := OS.get_environment("PHALANX_DART_KEY_FILE")
	if key.is_empty() and not key_path.is_empty():
		var file := FileAccess.open(key_path,FileAccess.READ)
		if file!=null and file.get_length()<=256:
			key = file.get_as_text().strip_edges()
	return key if key.length()==40 and key.is_valid_hex_number(false) else ""

func _fetch_financials(request_code: String, token: int) -> void:
	if not Model.CORPS.has(request_code):
		return
	var key := _dart_key()
	if key.is_empty():
		financial_message = "공식 IR 확인본 · 2023–2025 연간 · 자동 갱신은 OpenDART 설정 후 사용" if not financials.is_empty() else "자료 없음 · 공시 자동 조회에 필요한 OpenDART 설정이 없습니다."
		changed.emit()
		return
	financial_state = "loading"
	financial_message = "연결 재무제표 조회 중…"
	changed.emit()
	# Verify the corporation mapping against the primary source before reading statements.
	var company: Dictionary = await _dart_request("company.json",{"corp_code":Model.CORPS[request_code]},key,token)
	if token!=generation:
		return
	if company.get("status")!="000" or company.get("stock_code")!=request_code:
		_finance_failed()
		return
	var year: int = Time.get_date_dict_from_system(true).year-1
	var rows: Array = []
	for requested_year: int in range(year-2,year+1):
		var response: Dictionary = await _dart_request("fnlttSinglAcntAll.json",{"corp_code":Model.CORPS[request_code],"bsns_year":str(requested_year),"reprt_code":"11011","fs_div":"CFS"},key,token)
		if token!=generation:
			return
		var row := Model.parse_dart(response,request_code,requested_year)
		if row.is_empty():
			_finance_failed()
			return
		rows.append(row)
	financials = {"code":request_code,"currency":"KRW","basis":"연결 · 연간","source":"금융감독원 OpenDART","mode":"api","fetched_at":int(Time.get_unix_time_from_system()),"rows":rows}
	memory_financials[request_code] = financials
	financial_state = "ready"
	financial_message = "공시 조회 완료 · 연간 연결 기준 · 분/반기 자료는 포함하지 않습니다."
	changed.emit()

func _dart_request(endpoint: String, parameters: Dictionary, key: String, token: int) -> Dictionary:
	var parts := PackedStringArray(["crtfc_key="+key.uri_encode()])
	for field: String in parameters:
		parts.append(field+"="+str(parameters[field]).uri_encode())
	var error := finance_http.request("https://opendart.fss.or.kr/api/"+endpoint+"?"+"&".join(parts))
	if error!=OK:
		return {}
	var response: Array = await finance_http.request_completed
	if token!=generation or response[0]!=HTTPRequest.RESULT_SUCCESS or response[1]!=200:
		return {}
	var parser := JSON.new()
	if parser.parse(response[3].get_string_from_utf8())!=OK or not parser.data is Dictionary:
		return {}
	return parser.data

func _finance_failed() -> void:
	financial_state = "error" if financials.is_empty() else "stale"
	financial_message = "공시 조회 실패 · 연결/인증/보고서 제공 여부를 확인해주세요."+(" 이전 자료를 유지합니다." if not financials.is_empty() else " 자료 없음")
	changed.emit()

func _write_cache(name: String, value: Dictionary) -> bool:
	var directory := ProjectSettings.globalize_path(cache_dir)
	if DirAccess.make_dir_recursive_absolute(directory)!=OK:
		return false
	var destination := directory.path_join(name+".json")
	var temp := destination+".pending-"+str(OS.get_process_id())
	var file := FileAccess.open(temp,FileAccess.WRITE)
	if file==null:
		return false
	file.store_string(JSON.stringify(value))
	file.flush()
	var error := file.get_error()
	file.close()
	return error==OK and DirAccess.rename_absolute(temp,destination)==OK

func _read_quote_cache(request_code: String) -> Dictionary:
	var path := cache_dir.path_join("kis_"+request_code+".json")
	if not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path,FileAccess.READ)
	if file==null or file.get_length()>4*1024*1024:
		return {}
	var parser := JSON.new()
	if parser.parse(file.get_as_text())!=OK or not parser.data is Dictionary:
		return {}
	var value: Dictionary = parser.data
	if value.get("code")!=request_code or not Model.numeric(value.get("fetched_at")) or value.fetched_at>Time.get_unix_time_from_system()+60:
		return {}
	return Model.parse_kis(value.get("payload"),request_code,int(Time.get_unix_time_from_system()))

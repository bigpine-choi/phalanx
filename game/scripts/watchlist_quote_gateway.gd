extends Node
## Manually refreshed NH current prices for the watchlist table and research.
## This cache is separate from the workspace, account, and KIS daily history.
signal changed
signal batch_finished

const Model = preload("res://scripts/nhplug_quote_model.gd")
const NhProcess = preload("res://scripts/nhplug_quote_process.gd")
const CACHE_VERSION := 1
const MAX_CACHE_BYTES := 256 * 1024
const MAX_CACHED_QUOTES := 1000
const MAX_BATCH := 20
const MIN_INTERVAL_MSEC := 300
const FRESH_SECONDS := 300

var process: Node
var cache_dir := ""
var busy := false
var summary := "NH 현재가는 수동으로 갱신합니다."
var quotes := {}
var states := {}
var reasons := {}

var _queue: Array[String] = []
var _active_code := ""
var _active_token := 0
var _token_sequence := 0
var _next_start_msec := 0
var _done := 0
var _succeeded := 0
var _failed := 0
var _omitted := 0
var _unsupported := 0
var _cancelled := false
var _next_age_check_sec := 0
var _aged_codes := {}


func _ready() -> void:
	if cache_dir.is_empty():
		cache_dir = default_cache_dir()
	load_cached()
	if process == null:
		process = NhProcess.new()
		process.directory = ProjectSettings.globalize_path(cache_dir).path_join("bridge")
	if process.get_parent() == null:
		add_child(process)
	process.completed.connect(_completed)


static func default_cache_dir() -> String:
	var override := OS.get_environment("PHALANX_NH_QUOTE_CACHE")
	if not override.is_empty():
		return override
	var research := OS.get_environment("PHALANX_RESEARCH_CACHE")
	return research.path_join("nh-quotes") if not research.is_empty() else "user://research_cache/nh-quotes"


func _now_msec() -> int:
	return Time.get_ticks_msec()


func _now_sec() -> int:
	return int(Time.get_unix_time_from_system())


func _cache_path() -> String:
	return cache_dir.path_join("quotes.json")


func load_cached() -> bool:
	var path := _cache_path()
	if not FileAccess.file_exists(path):
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_cache_invalid()
		return false
	if file.get_length() > MAX_CACHE_BYTES:
		file.close()
		_cache_invalid()
		return false
	var parser := JSON.new()
	var valid_json := parser.parse(file.get_as_text()) == OK
	file.close()
	if not valid_json or not parser.data is Dictionary or parser.data.get("version") != CACHE_VERSION or not parser.data.get("quotes") is Array:
		_cache_invalid()
		return false
	var rows: Array = parser.data.quotes
	if rows.size() > MAX_CACHED_QUOTES:
		_cache_invalid()
		return false
	var loaded := {}
	for raw: Variant in rows:
		if not raw is Dictionary or not raw.get("code") is String:
			_cache_invalid()
			return false
		var code: String = raw.code
		if loaded.has(code):
			_cache_invalid()
			return false
		var quote: Dictionary = Model.parse_cached(raw, code, _now_sec())
		if quote.is_empty():
			_cache_invalid()
			return false
		loaded[code] = quote
	quotes = loaded
	for code: String in loaded:
		states[code] = "cached"
		reasons[code] = "저장된 이전 수신 값입니다. 수동 갱신으로 확인해 주세요."
		_aged_codes[code] = _now_sec() - int(loaded[code].fetched_at) > FRESH_SECONDS
	if not loaded.is_empty():
		summary = "저장된 NH 시세 %d개 · 이전 수신 값을 복원했습니다." % loaded.size()
	changed.emit()
	return true


func _cache_invalid() -> void:
	summary = "NH 저장 시세를 읽지 못했습니다. 수동 갱신해 주세요."
	changed.emit()


func _write_cache() -> bool:
	var directory := ProjectSettings.globalize_path(cache_dir)
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		return false
	var values: Array = []
	var codes: Array = quotes.keys()
	codes.sort()
	for code: String in codes:
		var quote: Dictionary = quotes[code]
		values.append({"provider":"NHPLUG","code":code,"market":"KRX","currency":"KRW",
			"price":int(quote.price),"fetched_at":int(quote.fetched_at)})
	var destination := directory.path_join("quotes.json")
	var temporary := destination + ".pending-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()]
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify({"version":CACHE_VERSION,"quotes":values}))
	file.flush()
	var write_error := file.get_error()
	file.close()
	if write_error != OK or DirAccess.rename_absolute(temporary, destination) != OK:
		if FileAccess.file_exists(temporary):
			DirAccess.remove_absolute(temporary)
		return false
	return true


func _evict_oldest_if_full(incoming_code: String) -> void:
	if quotes.has(incoming_code) or quotes.size() < MAX_CACHED_QUOTES:
		return
	var oldest_code := ""
	var oldest_time := 9223372036854775807
	for code: String in quotes:
		var stamp := int(quotes[code].fetched_at)
		if stamp < oldest_time or (stamp == oldest_time and code < oldest_code):
			oldest_code = code
			oldest_time = stamp
	if not oldest_code.is_empty():
		quotes.erase(oldest_code)
		states.erase(oldest_code)
		reasons.erase(oldest_code)
		_aged_codes.erase(oldest_code)


func quote_for(code: String) -> Dictionary:
	return quotes.get(code, {}).duplicate(true)


func row_fields(code: String) -> Dictionary:
	if not Model.valid_code(code):
		return {"price":null,"quote_source":"","quote_time":"","quote_status":"미지원",
			"quote_reason":"NH 현재가는 숫자 6자리 KRX 종목코드만 지원합니다."}
	var quote := quote_for(code)
	var state: String = states.get(code, "empty")
	var status := "조회 전"
	match state:
		"loading": status = "갱신 중 · 이전 시세" if not quote.is_empty() else "조회 중"
		"ready": status = "조회 완료"
		"cached": status = "저장된 시세"
		"unsaved": status = "조회 완료 · 저장 실패"
		"stale": status = "갱신 실패 · 이전 시세"
		"error": status = "조회 실패"
		"offline": status = "오프라인 · 이전 시세" if not quote.is_empty() else "오프라인"
		"cancelled": status = "갱신 취소 · 이전 시세" if not quote.is_empty() else "갱신 취소"
	var reason: String = reasons.get(code, "")
	if not quote.is_empty():
		if _now_sec() - int(quote.fetched_at) > FRESH_SECONDS and state in ["ready", "cached", "unsaved"]:
			status = "오래된 시세 · 저장 실패" if state == "unsaved" else "오래된 시세"
		reason = "NH투자증권 NHPLUG · KRX · 표시 시각은 응답 수신 시각이며 거래소 관측 시각은 제공되지 않습니다." + (" " + reason if not reason.is_empty() else "")
	return {"price":quote.get("price", null),"quote_source":"NH · KRX" if not quote.is_empty() else "",
		"quote_time":_time_kst(int(quote.fetched_at)) if not quote.is_empty() else "",
		"quote_status":status,"quote_reason":reason}


func _time_kst(timestamp: int) -> String:
	return Time.get_datetime_string_from_unix_time(timestamp + 9 * 3600).replace("T", " ")


func refresh(codes: Array) -> bool:
	if busy:
		summary = "NH 시세 갱신 중입니다. 중복 요청을 건너뛰었습니다."
		changed.emit()
		return false
	if process == null:
		summary = "NH 시세 연결이 준비되지 않았습니다."
		changed.emit()
		return false
	var seen := {}
	var accepted: Array[String] = []
	_omitted = 0
	_unsupported = 0
	for raw: Variant in codes:
		var code := str(raw)
		if seen.has(code):
			continue
		seen[code] = true
		if not Model.valid_code(code):
			_unsupported += 1
			states[code] = "unsupported"
			reasons[code] = "NH 현재가는 숫자 6자리 KRX 종목코드만 지원합니다."
		elif accepted.size() < MAX_BATCH:
			accepted.append(code)
		else:
			_omitted += 1
	if accepted.is_empty():
		summary = "NH 조회 가능한 코드가 없습니다." + (" 미지원 %d개." % _unsupported if _unsupported > 0 else "")
		changed.emit()
		return false
	if OS.get_environment("PHALANX_NH_OFFLINE") == "1":
		for code: String in accepted:
			states[code] = "offline"
			reasons[code] = "NH 오프라인 설정 중입니다. 저장된 이전 값은 유지합니다."
		summary = "NH 오프라인 · 네트워크 요청 없이 이전 값을 유지합니다."
		changed.emit()
		return false
	_queue = accepted
	_active_code = ""
	_done = 0
	_succeeded = 0
	_failed = 0
	_cancelled = false
	busy = true
	for code: String in accepted:
		states[code] = "loading"
		reasons[code] = "NH 현재가 수신 대기 중입니다."
	summary = "NH 시세 %d개 수동 갱신 중…" % accepted.size()
	changed.emit()
	_kick()
	return true


func cancel() -> void:
	if not busy:
		return
	for code: String in _queue:
		states[code] = "cancelled"
		reasons[code] = "진행 전 갱신이 취소되었습니다. 이전 값은 유지합니다."
	_queue.clear()
	_cancelled = true
	summary = "NH 시세 갱신 중단 요청 · 진행 중인 코드의 응답까지만 반영합니다."
	changed.emit()
	if _active_code.is_empty():
		_finish_batch()


func _process(_delta: float) -> void:
	if busy and _active_code.is_empty() and not _queue.is_empty():
		_kick()
	var now := _now_sec()
	if now < _next_age_check_sec or quotes.is_empty():
		return
	_next_age_check_sec = now + 1
	var changed_age := false
	for code: String in quotes:
		var aged: bool = now - int(quotes[code].fetched_at) > FRESH_SECONDS
		if _aged_codes.get(code, aged) != aged:
			_aged_codes[code] = aged
			changed_age = true
	if changed_age:
		changed.emit()


func _kick() -> void:
	if not busy or not _active_code.is_empty():
		return
	if _queue.is_empty():
		_finish_batch()
		return
	if _now_msec() < _next_start_msec:
		return
	_active_code = _queue.pop_front()
	_token_sequence += 1
	_active_token = _token_sequence
	_next_start_msec = _now_msec() + MIN_INTERVAL_MSEC
	process.request(_active_code, _active_token)


func _completed(code: String, token: int, envelope: Dictionary) -> void:
	if not busy or code != _active_code or token != _active_token:
		return
	var quote: Dictionary = Model.parse(envelope.get("payload"), code, _now_sec()) if envelope.get("ok") == true else {}
	if not quote.is_empty():
		_evict_oldest_if_full(code)
		quotes[code] = quote
		_aged_codes[code] = false
		states[code] = "ready"
		reasons[code] = ""
		_succeeded += 1
		if not _write_cache():
			states[code] = "unsaved"
			reasons[code] = "이번 값의 로컬 저장에 실패했습니다."
	else:
		states[code] = "stale" if quotes.has(code) else "error"
		reasons[code] = _failure_reason(str(envelope.get("error", "NH_READ_FAILED")))
		_failed += 1
	_done += 1
	_active_code = ""
	summary = "NH 시세 %d개 처리 · 성공 %d개 · 실패 %d개" % [_done, _succeeded, _failed]
	changed.emit()
	if _queue.is_empty():
		_finish_batch()
	else:
		_kick()


func _failure_reason(error: String) -> String:
	match error:
		"NH_OFFLINE": return "NH 오프라인 설정 중입니다. 이전 값은 유지합니다."
		"NH_SDK_MISSING": return "WSL Python의 NH SDK를 확인해 주세요. 이전 값은 유지합니다."
		"NH_CONFIG_MISSING": return "WSL의 NH 인증 설정을 확인해 주세요. 이전 값은 유지합니다."
		"NH_BRIDGE_UNAVAILABLE": return "NH WSL 연결을 확인해 주세요. 이전 값은 유지합니다."
		_: return "NH 조회에 실패했습니다. 이전 정상 가격과 수신 시각은 유지합니다."


func _finish_batch() -> void:
	if not busy:
		return
	busy = false
	var suffix := " · 요청 20개 초과 %d개 제외" % _omitted if _omitted > 0 else ""
	if _unsupported > 0:
		suffix += " · 미지원 %d개" % _unsupported
	summary = ("NH 시세 갱신 중단" if _cancelled else "NH 시세 갱신 완료") + " · 성공 %d개 · 실패 %d개" % [_succeeded, _failed] + suffix
	changed.emit()
	batch_finished.emit()

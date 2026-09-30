extends Node
## Local searchable snapshot of Python discovery. Network access occurs only on refresh.
signal changed

const Data = preload("res://scripts/market_data.gd")
const CatalogProcess = preload("res://scripts/catalog_process.gd")
const CACHE_VERSION := 1
const MAX_CACHE_BYTES := 8 * 1024 * 1024
const MAX_ITEMS := 20000
const MAX_RESULTS := 100

var items: Array = []
var collisions: Array = []
var collected_at := ""
var fetched_at := "" # Alias for callers displaying the collection time.
var source := ""
var state := "empty" # empty, loading, ready, stale, error
var message := "최초 자료 없음 · 종목 목록을 가져와 주세요."
var cache_path := ""
var process: Node
var _cache_checked := false
var _pending_refresh := false

func _ready() -> void:
	if cache_path.is_empty():
		cache_path = default_cache_path()
	process = CatalogProcess.new()
	process.directory = ProjectSettings.globalize_path(cache_path).get_base_dir().path_join("market_catalog_bridge")
	add_child(process)
	process.completed.connect(_completed)
	if not _cache_checked:
		load_cached()
	if items.is_empty():
		load_stored()
	elif _pending_refresh:
		_pending_refresh = false
		refresh()

static func default_cache_path() -> String:
	var override := OS.get_environment("PHALANX_CATALOG_CACHE")
	return override if not override.is_empty() else "user://market_catalog.json"

func load_cached() -> bool:
	_cache_checked = true
	if cache_path.is_empty():
		cache_path = default_cache_path()
	var path := ProjectSettings.globalize_path(cache_path)
	if not FileAccess.file_exists(path):
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return false
	if file.get_length() > MAX_CACHE_BYTES:
		file.close()
		return false
	var parser := JSON.new()
	var parsed := parser.parse(file.get_as_text())
	file.close()
	if parsed != OK or not parser.data is Dictionary or parser.data.get("version") != CACHE_VERSION:
		return false
	return accept_snapshot(parser.data.get("payload"), false)

func load_stored() -> void:
	if not items.is_empty():
		return
	if process == null or not process.active.is_empty():
		return
	if OS.get_environment("PHALANX_CATALOG_OFFLINE") == "1":
		state = "empty"
		message = "최초 자료 없음 · 오프라인에서는 저장된 종목 목록이 필요합니다."
		changed.emit()
		return
	state = "loading"
	message = "저장된 종목 목록을 읽는 중…"
	changed.emit()
	if not process.request("load"):
		_failed("load")

func refresh() -> void:
	if OS.get_environment("PHALANX_CATALOG_OFFLINE") == "1":
		_pending_refresh = false
		_failed("refresh")
		return
	if process == null:
		_pending_refresh = true
		return
	if not process.active.is_empty():
		# A duplicate refresh joins the one in flight. Only an initial load
		# needs a subsequent network-capable refresh.
		if process.active.get("action") == "load":
			_pending_refresh = true
			message = "저장된 목록을 읽은 뒤 갱신합니다…"
			changed.emit()
		return
	_pending_refresh = false
	state = "loading"
	message = "시장 종목 목록을 갱신하는 중…"
	changed.emit()
	if not process.request("refresh"):
		_failed("refresh")

func _completed(action: String, envelope: Dictionary) -> void:
	var payload: Variant = envelope.get("payload")
	var normalized := _normalize_payload(payload)
	var failure_code: String = str(envelope.get("error", "")) if envelope.get("ok") == false else ""
	if envelope.get("ok") == true and not normalized.is_empty():
		if not normalized.items.is_empty():
			accept_snapshot(normalized, true)
		else:
			# An unexpectedly empty refresh must never replace a prior good list.
			if items.is_empty():
				state = "empty"
				message = "최초 자료 없음 · 종목 목록을 가져와 주세요."
				changed.emit()
			else:
				_failed(action, "EMPTY_RESULT")
	elif envelope.get("ok") == false and envelope.get("error") == "REFRESH_FAILED" and items.is_empty() and not normalized.is_empty() and not normalized.items.is_empty():
		# The Python repository can still provide its previous successful view.
		accept_snapshot(normalized, true)
		_failed(action, failure_code)
	else:
		_failed(action, failure_code)
	if _pending_refresh and action == "load":
		_pending_refresh = false
		refresh()

func _failed(action: String, reason := "") -> void:
	state = "stale" if not items.is_empty() else "error"
	if action == "refresh":
		message = "갱신 실패 · 이전 정상 목록과 수집 시각을 유지합니다." if state == "stale" else "갱신 실패 · 종목 목록을 가져오지 못했습니다."
	else:
		if state == "stale":
			message = "최근 갱신 실패 · 이전 정상 목록과 수집 시각을 유지합니다." if reason == "REFRESH_FAILED" else "저장된 종목 목록을 읽지 못했습니다. 이전 정상 목록과 수집 시각을 유지합니다."
		else:
			message = "최근 목록 갱신 실패 · 최초 정상 목록이 없습니다. 목록 갱신을 눌러주세요." if reason == "REFRESH_FAILED" else "저장된 종목 목록을 읽지 못했습니다. 다시 시도해 주세요."
	changed.emit()

func accept_snapshot(payload: Variant, persist := false) -> bool:
	var normalized := _normalize_payload(payload)
	if normalized.is_empty() or normalized.items.is_empty():
		return false
	items = normalized.items
	collisions = normalized.collisions
	collected_at = normalized.collected_at
	fetched_at = collected_at
	source = normalized.source
	state = "ready"
	message = "종목 %d개 · 수집 %s" % [items.size(), collected_at]
	if persist and not _write_cache(normalized):
		message += " · 로컬 목록 저장 실패"
	changed.emit()
	return true

func _normalize_payload(payload: Variant) -> Dictionary:
	if not payload is Dictionary or payload.get("state") not in ["ready", "empty"] or not payload.get("items") is Array:
		return {}
	var raw_items: Array = payload.items
	if raw_items.size() > MAX_ITEMS:
		return {}
	if payload.state == "empty":
		return {"state":"empty","items":[],"collisions":[],"collected_at":"","source":""} if raw_items.is_empty() else {}
	var stamp: Variant = payload.get("collected_at")
	var origin: Variant = payload.get("source")
	if not _field(stamp, 64) or not _field(origin, 120):
		return {}
	var raw_collisions: Variant = payload.get("collisions", [])
	if not raw_collisions is Array or raw_collisions.size() > MAX_ITEMS:
		return {}
	var collision_codes := {}
	var safe_collisions: Array = []
	for raw: Variant in raw_collisions:
		if not raw is Dictionary or not _field(raw.get("code"), 64) or not _field(raw.get("reason"), 200):
			return {}
		collision_codes[raw.code] = raw.reason
		safe_collisions.append({"code":raw.code,"reason":raw.reason})
	var safe_items: Array = []
	var counts := {}
	for raw: Variant in raw_items:
		if not raw is Dictionary:
			return {}
		for key: String in ["code", "name", "market", "kind", "source", "collected_at"]:
			var length := 64 if key == "code" or key == "collected_at" else 120
			if not _field(raw.get(key), length):
				return {}
		if not raw.get("collision") is bool or not raw.get("registration_supported") is bool or not raw.has("reason") or not raw.reason is String:
			return {}
		if raw.reason.length() > 200:
			return {}
		var code: String = raw.code
		counts[code] = int(counts.get(code, 0)) + 1
		safe_items.append({"code":code,"name":raw.name,"market":raw.market,"kind":raw.kind,"source":raw.source,"collected_at":raw.collected_at,"collision":raw.collision,"registration_supported":raw.registration_supported,"reason":raw.reason})
	if safe_items.is_empty():
		return {}
	for row: Dictionary in safe_items:
		if row.collision and not collision_codes.has(row.code):
			var reason: String = row.reason if not row.reason.is_empty() else "식별자 충돌로 등록할 수 없습니다."
			collision_codes[row.code] = reason
			safe_collisions.append({"code":row.code,"reason":reason})
	for code: String in counts:
		if counts[code] > 1 and not collision_codes.has(code):
			var reason := "동일 코드가 여러 종목에 연결되어 등록할 수 없습니다."
			collision_codes[code] = reason
			safe_collisions.append({"code":code,"reason":reason})
	for index: int in safe_items.size():
		var row: Dictionary = safe_items[index]
		var duplicate: bool = counts[row.code] > 1
		if duplicate or collision_codes.has(row.code):
			row.collision = true
			row.registration_supported = false
			row.reason = collision_codes.get(row.code, "동일 코드가 여러 종목에 연결되어 등록할 수 없습니다.")
		elif not Data.valid_code(row.code) or row.name.length() > 80:
			row.registration_supported = false
			if row.reason.is_empty():
				row.reason = "기존 워크스페이스가 이 종목 식별자를 저장할 수 없습니다."
		elif not row.registration_supported and row.reason.is_empty():
			row.reason = "이 종목은 관심종목으로 등록할 수 없습니다."
		safe_items[index] = row
	return {"state":"ready","items":safe_items,"collisions":safe_collisions,"collected_at":stamp,"source":origin}

static func _field(value: Variant, maximum: int) -> bool:
	return value is String and not value.is_empty() and value.length() <= maximum and value.strip_edges() == value

func _write_cache(payload: Dictionary) -> bool:
	var destination := ProjectSettings.globalize_path(cache_path)
	if DirAccess.make_dir_recursive_absolute(destination.get_base_dir()) != OK:
		return false
	var serialized := JSON.stringify({"version":CACHE_VERSION,"payload":payload})
	if serialized.to_utf8_buffer().size() > MAX_CACHE_BYTES:
		return false
	var temporary := destination + ".pending-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()]
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(serialized)
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK or DirAccess.rename_absolute(temporary, destination) != OK:
		if FileAccess.file_exists(temporary):
			DirAccess.remove_absolute(temporary)
		return false
	return true

func search(query: String, limit := 30) -> Dictionary:
	limit = clampi(limit, 1, MAX_RESULTS)
	var needle := query.strip_edges().to_lower()
	if needle.is_empty():
		return {"items":items.slice(0,mini(limit,items.size())),"total":items.size(),"truncated":items.size()>limit}
	var buckets: Array = [[], [], [], []]
	for row: Dictionary in items:
		var code: String = row.code.to_lower()
		var name: String = row.name.to_lower()
		var rank := -1
		if code == needle:
			rank = 0
		elif code.begins_with(needle):
			rank = 1
		elif name.begins_with(needle):
			rank = 2
		elif name.contains(needle) or code.contains(needle) or row.market.to_lower().contains(needle) or row.kind.to_lower().contains(needle):
			rank = 3
		if rank >= 0:
			buckets[rank].append(row)
	var found: Array = []
	var total := 0
	for bucket: Array in buckets:
		total += bucket.size()
		for row: Dictionary in bucket:
			if found.size() < limit:
				found.append(row)
	return {"items":found,"total":total,"truncated":total>limit}

static func can_register(item: Dictionary) -> bool:
	return item.get("collision") == false and item.get("registration_supported") == true and Data.valid_code(item.get("code")) and item.get("name") is String and item.name.length() <= 80

static func chart_support(item: Dictionary) -> Dictionary:
	if item.get("collision") == true:
		return {"supported":false,"reason":"종목 식별자가 충돌하여 일봉 대상을 확정할 수 없습니다."}
	if not Data.valid_code(item.get("code")):
		return {"supported":false,"reason":"기존 일봉 조회는 영문 대문자·숫자 6자리 국내 종목코드만 지원합니다."}
	return {"supported":true,"reason":""}

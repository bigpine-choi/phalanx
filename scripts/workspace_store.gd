extends RefCounted
## Versioned local preferences, independent of quotes, account and order models.
const Data = preload("res://scripts/demo_data.gd")
const VERSION := 1
const MAX_BYTES := 4 * 1024 * 1024
const MAX_NOTE_LENGTH := 100000
var path: String
var state: Dictionary
var blocked := false
var message := ""
var expected_fingerprint := ""

static func default_path() -> String:
	# Review/test runners can isolate their data without touching the real profile.
	var override := OS.get_environment("PHALANX_WORKSPACE_PATH")
	return override if not override.is_empty() else "user://investment_workspace.json"

func _init(file_path := "") -> void:
	path = ProjectSettings.globalize_path(default_path() if file_path.is_empty() else file_path)
	state = defaults()

static func defaults() -> Dictionary:
	var codes: Array = []
	for stock: Dictionary in Data.STOCKS:
		codes.append(stock.code)
	return {"version":VERSION,"watchlist":codes,"notes":{}}

static func valid_code(value: Variant) -> bool:
	return value is String and not value.is_empty() and value.length() <= 32 and value.strip_edges() == value

static func validate(value: Variant) -> bool:
	if not value is Dictionary or value.get("version") != VERSION:
		return false
	if not value.get("watchlist") is Array or not value.get("notes") is Dictionary:
		return false
	if value.watchlist.size() > 1000 or value.notes.size() > 1000:
		return false
	var seen := {}
	for code: Variant in value.watchlist:
		if not valid_code(code) or seen.has(code):
			return false
		seen[code] = true
	for code: Variant in value.notes:
		if not valid_code(code) or not value.notes[code] is String or value.notes[code].length() > MAX_NOTE_LENGTH:
			return false
	return true

func _read(source: String) -> Dictionary:
	if not FileAccess.file_exists(source):
		return {"kind":"missing"}
	var file := FileAccess.open(source,FileAccess.READ)
	if file == null:
		return {"kind":"unreadable"}
	if file.get_length() > MAX_BYTES:
		return {"kind":"invalid"}
	var parser := JSON.new()
	var error := parser.parse(file.get_as_text())
	file.close()
	if error != OK:
		return {"kind":"invalid"}
	var value: Variant = parser.data
	if value is Dictionary and value.get("version") != VERSION:
		return {"kind":"version"}
	if not validate(value):
		return {"kind":"invalid"}
	return {"kind":"ok","state":value}

func _fingerprint() -> String:
	return FileAccess.get_sha256(path) if FileAccess.file_exists(path) else "missing"

func load_profile() -> Dictionary:
	state = defaults()
	message = ""
	blocked = false
	expected_fingerprint = _fingerprint()
	var primary := _read(path)
	if primary.kind == "ok":
		state = primary.state
		return state.duplicate(true)
	# Never downgrade or silently replace a newer profile or inaccessible file.
	if primary.kind in ["version","unreadable"]:
		blocked = true
		message = "저장 파일을 읽을 수 없습니다. 원본을 보존하며 새 변경은 저장하지 않습니다."
		return state.duplicate(true)
	var backup := _read(path+".bak")
	if backup.kind == "ok":
		state = backup.state
		message = "이전 저장본을 복원했습니다. 최근 변경 일부는 없을 수 있습니다."
	elif primary.kind != "missing" or backup.kind != "missing":
		blocked = true
		message = "저장 파일 확인이 필요합니다. 원본을 보존하며 새 변경은 저장하지 않습니다."
	return state.duplicate(true)

func save_profile(watchlist: Array, notes: Dictionary) -> bool:
	if blocked:
		return false
	if _fingerprint() != expected_fingerprint:
		message = "다른 창에서 저장 내용이 바뀌었습니다. 현재 메모를 복사한 뒤 앱을 다시 열어주세요."
		return false
	# Preserve unknown fields/codes for future catalogue changes.
	var payload := state.duplicate(true)
	payload.watchlist = watchlist.duplicate()
	payload.notes = notes.duplicate(true)
	if not validate(payload):
		message = "저장할 내용이 너무 길거나 형식이 잘못되었습니다. 변경 내용은 화면에 유지됩니다."
		return false
	var serialized := JSON.stringify(payload,"\t")
	if serialized.to_utf8_buffer().size() > MAX_BYTES:
		message = "저장 용량을 초과했습니다. 메모를 줄인 뒤 다시 저장해주세요."
		return false
	if DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		return _write_error()
	var temporary := path+".pending-"+str(OS.get_process_id())
	var file := FileAccess.open(temporary,FileAccess.WRITE)
	if file == null:
		return _write_error()
	file.store_string(serialized)
	file.flush()
	var error := file.get_error()
	file.close()
	if error != OK or _read(temporary).kind != "ok":
		return _write_error()
	var existing := _read(path)
	if existing.kind == "ok":
		var backup_temp := temporary+".bak"
		if DirAccess.copy_absolute(path,backup_temp) != OK or DirAccess.rename_absolute(backup_temp,path+".bak") != OK:
			return _write_error()
	elif existing.kind != "missing":
		# Keep damaged primary bytes before publishing a recovered profile.
		var archive := path+".damaged-"+str(Time.get_unix_time_from_system()).replace(".","-")+"-"+str(OS.get_process_id())
		if DirAccess.copy_absolute(path,archive) != OK:
			return _write_error()
	if DirAccess.rename_absolute(temporary,path) != OK:
		return _write_error()
	expected_fingerprint = _fingerprint()
	state = payload
	message = ""
	return true

func _write_error() -> bool:
	message = "이 기기에 저장하지 못했습니다. 변경 내용은 화면에 유지됩니다. 저장을 다시 시도해주세요."
	return false

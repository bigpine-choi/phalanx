extends Node
## One bounded WSL request for the POSIX discovery catalogue.
signal completed(action: String, envelope: Dictionary)

const MAX_RESULT_BYTES := 8 * 1024 * 1024
var directory := ""
var pid := -1
var deadline := 0
var active: Dictionary = {}
var sequence := 0

func request(action: String) -> bool:
	if action not in ["load", "refresh"] or pid >= 0 or not active.is_empty():
		return false
	sequence += 1
	var identifier := "%d-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec(), sequence]
	active = {"action":action, "request_id":identifier, "file":directory.path_join("catalog-result-"+identifier+".json")}
	var distro := OS.get_environment("PHALANX_KIS_WSL_DISTRO")
	if distro.is_empty():
		distro = "Ubuntu-24.04"
	var python := OS.get_environment("PHALANX_KIS_WSL_PYTHON")
	if python.is_empty():
		python = "/home/hansol/projects/phalanx/.venv/bin/python"
	var script := _wsl_path(ProjectSettings.globalize_path("res://tools/market_catalog_bridge.py"))
	var output := _wsl_path(active.file)
	if OS.get_name() != "Windows" or script.is_empty() or output.is_empty() or DirAccess.make_dir_recursive_absolute(directory) != OK:
		_finish({"ok":false,"error":"BRIDGE_UNAVAILABLE"})
		return true
	pid = OS.create_process("wsl.exe", PackedStringArray(["-d",distro,"--exec","/usr/bin/timeout","85s",python,script,action,output,identifier]), false)
	deadline = Time.get_ticks_msec() + 90000
	if pid < 0:
		_finish({"ok":false,"error":"BRIDGE_UNAVAILABLE"})
	return true

func _wsl_path(path: String) -> String:
	path = path.replace("\\", "/")
	if path.length() < 3 or path[1] != ":":
		return ""
	return "/mnt/"+path[0].to_lower()+path.substr(2)

func _process(_delta: float) -> void:
	if pid < 0:
		return
	var running := OS.is_process_running(pid)
	if running and Time.get_ticks_msec() < deadline:
		return
	if running:
		OS.kill(pid)
	pid = -1
	var result: Dictionary = {"ok":false,"error":"BRIDGE_FAILED"}
	var file := FileAccess.open(active.file, FileAccess.READ)
	if file != null:
		if file.get_length() <= MAX_RESULT_BYTES:
			var parsed := JSON.new()
			if parsed.parse(file.get_as_text()) == OK:
				result = _validated_envelope(parsed.data, active.request_id)
		file.close()
	if FileAccess.file_exists(active.file):
		DirAccess.remove_absolute(active.file)
	_finish(result)

static func _validated_envelope(value: Variant, expected_id: String) -> Dictionary:
	if not value is Dictionary or value.get("request_id") != expected_id or not value.get("ok") is bool or not value.get("payload") is Dictionary:
		return {"ok":false,"error":"BRIDGE_FAILED"}
	if value.ok == false and (not value.get("error") is String or value.error.is_empty() or value.error.length() > 64):
		return {"ok":false,"error":"BRIDGE_FAILED"}
	return value

func _finish(envelope: Dictionary) -> void:
	var action: String = active.get("action", "")
	active = {}
	completed.emit(action, envelope)

func _exit_tree() -> void:
	if pid > 0:
		OS.kill(pid)

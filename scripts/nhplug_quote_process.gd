extends Node
## The Godot process receives a public quote; the NH SDK keeps keys inside WSL.
signal completed(code: String, token: int, envelope: Dictionary)
const Model = preload("res://scripts/nhplug_quote_model.gd")
var pid := -1
var pending: Dictionary = {}
var active: Dictionary = {}
var deadline := 0
var directory := ""
var sequence := 0

func request(code: String, token: int) -> void:
	if not Model.valid_code(code):
		return
	pending = {"code":code,"token":token}
	if pid<0:
		_start()

func _wsl_path(path: String) -> String:
	path = path.replace("\\","/")
	if path.length()<3 or path[1]!=":":
		return ""
	return "/mnt/"+path[0].to_lower()+path.substr(2)

func _start() -> void:
	active = pending
	pending = {}
	sequence += 1
	var identifier := "%d-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec(),sequence]
	active["request_id"] = identifier
	active["file"] = directory.path_join("nh-result-"+identifier+".json")
	var distro := OS.get_environment("PHALANX_NH_WSL_DISTRO")
	if distro.is_empty():
		distro = OS.get_environment("PHALANX_KIS_WSL_DISTRO")
	if distro.is_empty():
		distro = "Ubuntu-24.04"
	var python := OS.get_environment("PHALANX_NH_WSL_PYTHON")
	if python.is_empty():
		python = OS.get_environment("PHALANX_KIS_WSL_PYTHON")
	if python.is_empty():
		python = "/home/hansol/projects/phalanx/.venv/bin/python"
	var script := _wsl_path(ProjectSettings.globalize_path("res://tools/nhplug_quote_bridge.py"))
	var output := _wsl_path(active.file)
	if OS.get_name()!="Windows" or script.is_empty() or output.is_empty() or DirAccess.make_dir_recursive_absolute(directory)!=OK:
		_finish({"ok":false,"error":"NH_BRIDGE_UNAVAILABLE"})
		return
	pid = OS.create_process("wsl.exe",PackedStringArray(["-d",distro,"--exec","/usr/bin/timeout","20s",python,script,active.code,output,identifier]),false)
	deadline = Time.get_ticks_msec()+25000
	if pid<0:
		_finish({"ok":false,"error":"NH_BRIDGE_UNAVAILABLE"})

func _process(_delta: float) -> void:
	if pid<0:
		return
	var running := OS.is_process_running(pid)
	if running and Time.get_ticks_msec()<deadline:
		return
	if running:
		OS.kill(pid)
	pid = -1
	var result: Dictionary = {"ok":false,"error":"NH_READ_FAILED"}
	var file := FileAccess.open(active.file,FileAccess.READ)
	if file!=null and file.get_length()<=16*1024:
		var parsed := JSON.new()
		if parsed.parse(file.get_as_text())==OK and parsed.data is Dictionary:
			var envelope: Dictionary = parsed.data
			if envelope.get("request_id")==active.request_id and envelope.get("code")==active.code:
				if envelope.get("ok")==true and envelope.get("payload") is Dictionary:
					result = {"ok":true,"payload":envelope.payload}
				elif envelope.get("error") in ["NH_SDK_MISSING","NH_CONFIG_MISSING","NH_READ_FAILED"]:
					result = {"ok":false,"error":envelope.error}
		file.close()
	if FileAccess.file_exists(active.file):
		DirAccess.remove_absolute(active.file)
	_finish(result)

func _finish(envelope: Dictionary) -> void:
	var finished := active
	active = {}
	completed.emit(finished.code,finished.token,envelope)
	if not pending.is_empty():
		_start()

func _exit_tree() -> void:
	if pid>0:
		OS.kill(pid)

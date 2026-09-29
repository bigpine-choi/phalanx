extends Node
## One child at a time; quick stock switches replace only the pending request.
signal completed(code: String, token: int, payload: Dictionary)
const Model = preload("res://scripts/research_model.gd")
var pid := -1
var pending: Dictionary = {}
var active: Dictionary = {}
var deadline := 0
var directory := ""
var sequence := 0

func request(code: String, token: int) -> void:
	if not Model.Data.valid_code(code):
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
	active["file"] = directory.path_join("kis-result-"+identifier+".json")
	var distro := OS.get_environment("PHALANX_KIS_WSL_DISTRO")
	if distro.is_empty():
		distro = "Ubuntu-24.04"
	var python := OS.get_environment("PHALANX_KIS_WSL_PYTHON")
	if python.is_empty():
		python = "/home/hansol/projects/phalanx/.venv/bin/python"
	var script := _wsl_path(ProjectSettings.globalize_path("res://tools/kis_research_bridge.py"))
	var output := _wsl_path(active.file)
	if OS.get_name()!="Windows" or script.is_empty() or output.is_empty() or DirAccess.make_dir_recursive_absolute(directory)!=OK:
		_finish({})
		return
	pid = OS.create_process("wsl.exe",PackedStringArray(["-d",distro,"--exec","/usr/bin/timeout","50s",python,script,active.code,output,identifier]),false)
	deadline = Time.get_ticks_msec()+55000
	if pid<0:
		_finish({})

func _process(_delta: float) -> void:
	if pid<0:
		return
	var running := OS.is_process_running(pid)
	if running and Time.get_ticks_msec()<deadline:
		return
	if running:
		OS.kill(pid)
	pid = -1
	var result: Dictionary = {}
	var file := FileAccess.open(active.file,FileAccess.READ)
	if file!=null and file.get_length()<=256*1024:
		var parsed := JSON.new()
		if parsed.parse(file.get_as_text())==OK and parsed.data is Dictionary:
			var envelope: Dictionary = parsed.data
			if envelope.get("request_id")==active.request_id and envelope.get("code")==active.code and envelope.get("ok")==true and envelope.get("payload") is Dictionary:
				result = envelope.payload
		file.close()
	if FileAccess.file_exists(active.file):
		DirAccess.remove_absolute(active.file)
	_finish(result)

func _finish(payload: Dictionary) -> void:
	var finished := active
	active = {}
	completed.emit(finished.code,finished.token,payload)
	if not pending.is_empty():
		_start()

func _exit_tree() -> void:
	if pid>0:
		OS.kill(pid)

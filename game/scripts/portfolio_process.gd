extends "res://scripts/advisor_process.gd"
## Existing one-shot transport, with an explicitly read-only WSL account route.
const WslPath = preload("res://scripts/wsl_path.gd")
func _ready() -> void:
	super._ready()
	script_path = "res://tools/portfolio_bridge.py"

func request(action: String, value: Dictionary = {}) -> void:
	if action != "account":
		super.request(action,value)
		return
	cancel()
	if OS.get_environment("PHALANX_ACCOUNT_OFFLINE")=="1":
		completed.emit(action,{},"OFFLINE")
		return
	if DirAccess.make_dir_recursive_absolute(directory)!=OK:
		completed.emit(action,{},"LOCAL_WRITE_FAILED")
		return
	var identifier := "%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()]
	active = {"action":action,"id":identifier,"input":directory.path_join(identifier+".input.json"),"output":directory.path_join(identifier+".result.json")}
	var marker := FileAccess.open(active.input,FileAccess.WRITE)
	if marker==null:
		_finish({},"LOCAL_WRITE_FAILED")
		return
	marker.store_string(identifier)
	marker.close()
	var distro := OS.get_environment("PHALANX_KIS_WSL_DISTRO")
	if distro.is_empty(): distro = "Ubuntu-24.04"
	var python := OS.get_environment("PHALANX_KIS_WSL_PYTHON")
	if python.is_empty(): python = "/home/hansol/projects/phalanx/.venv/bin/python"
	var script := WslPath.from_windows(ProjectSettings.globalize_path("res://tools/account_bridge.py"))
	var output := WslPath.from_windows(active.output)
	if script.is_empty() or output.is_empty():
		_finish({},"ACCOUNT_CONFIG")
		return
	pid = OS.create_process("wsl.exe",PackedStringArray(["-d",distro,"--exec","/usr/bin/timeout","80s",python,script,output,identifier,WslPath.from_windows(active.input)]),false)
	deadline = Time.get_ticks_msec()+85000
	if pid<0: _finish({},"ACCOUNT_CONFIG")

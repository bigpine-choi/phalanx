extends Node
## Private local request files for research; secrets use only an anonymous pipe.
signal completed(action: String, payload: Dictionary, error: String)
var pid := -1
var active: Dictionary = {}
var pipes: Dictionary = {}
var deadline := 0
var python_path := ""
var directory := ""
var script_path := "res://tools/advisor_bridge.py"

func _ready() -> void:
	python_path = OS.get_environment("PHALANX_ADVISOR_PYTHON")
	if python_path.is_empty():
		python_path = OS.get_environment("USERPROFILE").path_join("dev/phalanx/.venv/Scripts/python.exe")
	directory = OS.get_environment("PHALANX_ADVISOR_REQUESTS")
	if directory.is_empty():
		directory = ProjectSettings.globalize_path("user://advisor_requests")

func request(action: String, value: Dictionary = {}) -> void:
	cancel()
	if not FileAccess.file_exists(python_path) or DirAccess.make_dir_recursive_absolute(directory)!=OK:
		completed.emit(action,{},"PYTHON_UNAVAILABLE")
		return
	var identifier := "%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()]
	active = {"action":action,"id":identifier,"input":directory.path_join(identifier+".input.json"),"output":directory.path_join(identifier+".result.json")}
	if action in ["analyze","facts","simulate","portfolio_review"]:
		var file := FileAccess.open(active.input,FileAccess.WRITE)
		if file == null:
			_finish({},"LOCAL_WRITE_FAILED")
			return
		file.store_string(JSON.stringify(value))
		file.close()
	var args := PackedStringArray([ProjectSettings.globalize_path(script_path),action,active.input,active.output,identifier])
	if action == "configure":
		# Bounded credential message fits an OS pipe; never a command argument/file.
		var message := JSON.stringify(value)+"\n"
		if message.to_utf8_buffer().size()>4096:
			_finish({},"CONFIG_INVALID")
			return
		pipes = OS.execute_with_pipe(python_path,args,true)
		pid = int(pipes.get("pid",-1))
		if pid > 0:
			pipes.stdio.store_string(message)
			pipes.stdio.flush()
	else:
		pid = OS.create_process(python_path,args,false)
	deadline = Time.get_ticks_msec()+70000
	if pid < 0:
		_finish({},"PYTHON_UNAVAILABLE")

func _process(_delta: float) -> void:
	if pid < 0:
		return
	if OS.is_process_running(pid):
		if Time.get_ticks_msec() < deadline:
			return
		OS.kill(pid)
		pid = -1
		_finish({},"TIMEOUT")
		return
	pid = -1
	var envelope: Dictionary = {}
	var file := FileAccess.open(active.output,FileAccess.READ)
	if file != null and file.get_length()<=512*1024:
		var value: Variant = JSON.parse_string(file.get_as_text())
		if value is Dictionary and value.get("request_id")==active.id:
			envelope = value
		file.close()
	if envelope.get("ok")==true and envelope.get("payload") is Dictionary:
		_finish(envelope.payload,"")
	else:
		_finish({},str(envelope.get("error","PROCESS_FAILED")))

func _finish(payload: Dictionary, error: String) -> void:
	var action: String = active.get("action","")
	_cleanup()
	completed.emit(action,payload,error)

func _cleanup() -> void:
	for key: String in ["input","output"]:
		if active.has(key) and FileAccess.file_exists(active[key]):
			DirAccess.remove_absolute(active[key])
	if active.has("output"):
		var temporary: String = active.output.get_basename()+".pending"
		if FileAccess.file_exists(temporary):
			DirAccess.remove_absolute(temporary)
	for pipe: Variant in pipes.values():
		if pipe is FileAccess:
			pipe.close()
	pipes = {}
	active = {}

func cancel() -> void:
	if pid>0 and OS.is_process_running(pid):
		OS.kill(pid)
	pid = -1
	_cleanup()

func _exit_tree() -> void:
	cancel()

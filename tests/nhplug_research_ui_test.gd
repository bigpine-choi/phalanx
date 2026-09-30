extends SceneTree
const Research = preload("res://scripts/research_detail.gd")
var failures := 0
var checks := 0

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	call_deferred("run")

func check(ok: bool, name: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(name)

func run() -> void:
	var research := Research.new()
	root.add_child(research)
	research.select_security({"code":"005930","name":"삼성전자"})
	check(research.nh_button.text=="NH 현재가" and not research.nh_button.disabled,"Separate NH quote action")
	var now := int(Time.get_unix_time_from_system())
	var quote := {"provider":"NHPLUG","code":"005930","market":"KRX","currency":"KRW","price":231000,"fetched_at":now}
	research._nh_completed("005930",research.nh_generation,{"ok":true,"payload":quote})
	check("231,000" in research.nh_status.text and "KIS 일봉과 별도" in research.nh_status.text,"NH quote labeled separately")
	var previous := research.nh_generation
	research.select_security({"code":"000660","name":"SK하이닉스"})
	research._nh_completed("005930",previous,{"ok":true,"payload":quote})
	check("231,000" not in research.nh_status.text,"Stale response cannot paint next stock")
	research.queue_free()
	await process_frame
	print("PHALANX_NHPLUG_UI_TEST: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

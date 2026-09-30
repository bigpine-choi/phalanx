extends SceneTree
const Fixture = preload("res://tests/operation_fixture.gd")
const Record = preload("res://scripts/operation_record.gd")
func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	call_deferred("run")
func run() -> void:
	var args := OS.get_cmdline_user_args()
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	view.storage_path = args[1]
	root.add_child(view)
	var draft := {"title":"프로세스 재시작 검증","rationale":"정확한 복원 확인","risk":"검증용 자료"}
	if args[0] == "seed":
		Fixture.install(view,19.0)
		view._operation_draft_changed(draft)
		view._record_operation()
		Fixture.install(view,17.5)
		view._operation_draft_changed(draft)
		view.flush_profile()
	else:
		if view.operations.size()!=1 or view.simulation_plan.rows[0].target!=17.5 or view.live_operation_draft!=draft or view.operations[0].rows[0].target!=19.0 or not Record.validate(view.operations[0]):
			push_error("Process restart failed to restore exact draft, targets and past snapshot")
			quit(1)
			return
	print("PHALANX_OPERATIONS_RESTART: PASS ("+args[0]+")")
	quit()

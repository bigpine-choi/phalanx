extends SceneTree
## Run write and read in separate Godot processes with one isolated profile path.
const Store = preload("res://scripts/workspace_store.gd")
const Fixture = preload("res://tests/operation_fixture.gd")
const Record = preload("res://scripts/operation_record.gd")
const CODE := "123456"
const NAME := "검증전자"
const NOTE := "그룹별 관찰 가설 · 종료 직전 입력 보존"

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()<2 or args[0] not in ["write","read"] or not args[1].is_absolute_path():
		push_error("Expected write/read and an isolated absolute profile path")
		quit(1)
		return
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",args[1])
	OS.set_environment("PHALANX_CATALOG_CACHE",args[1]+".catalog.json")
	OS.set_environment("PHALANX_RESEARCH_CACHE",args[1]+".research")
	call_deferred("run")

func entry() -> Dictionary:
	return {"code":CODE,"name":NAME,"market":"KOSDAQ","kind":"보통주","source":"격리 검증 목록",
		"collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}

func run() -> void:
	var args := OS.get_cmdline_user_args()
	root.size = Vector2i(1280,720)
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	root.add_child(view)
	for index: int in 6:
		await process_frame
	if not is_instance_valid(view.watch_table) or not view.watch_table.is_inside_tree():
		push_error("Watchlist table did not initialize; treat script errors as test failure")
		quit(1)
		return
	if args[0]=="write":
		if not view.catalog.accept_snapshot({"state":"ready","source":"격리 검증 목록","collected_at":"2026-09-30T00:00:00+00:00","items":[entry()],"collisions":[]}):
			push_error("Could not inject isolated catalogue")
			quit(1)
			return
		view._catalog_security_chosen(entry(),true)
		var first: String = view.watch_groups.create_group("성장 관찰")
		var second: String = view.watch_groups.create_group("분산 관찰")
		view._group_membership_requested(first,CODE,true)
		view._group_membership_requested(second,CODE,true)
		view.watch_groups.select_group(second)
		view.watch_groups.set_sort("kind",false)
		view._watch_preferences_changed()
		Fixture.install(view,19.0)
		view._operation_draft_changed({"title":"그룹 재실행 검증","rationale":"기존 작전 기록 보존","risk":"격리된 검증 자료"})
		view._record_operation()
		if view.operations.size()!=1:
			push_error("Could not seed one existing operation")
			quit(1)
			return
		view._select_stock(view._security_index(CODE))
		view.note_editor.text = NOTE
		view._note_changed()
		# Exit before debounce. Normal tree shutdown must flush note and preferences.
		print("WATCHLIST_GROUPS_RESTART_WRITE: two groups, sort, favorite, operation and pending note")
		quit(0)
		return
	var saved: Dictionary = Store.new(args[1]).load_profile()
	var group_state: Dictionary = view.watch_groups.export_state()
	var groups: Array = view.watch_groups.groups
	var valid: bool = saved.version==Store.VERSION and CODE in view.watchlist_codes and view.watchlist_codes.count(CODE)==1
	valid = valid and view._security_index(CODE)>=0 and view.securities[view._security_index(CODE)].name==NAME
	valid = valid and groups.size()==2 and groups[0].id.length()==32 and groups[1].id.length()==32 and groups[0].id!=groups[1].id
	valid = valid and CODE in groups[0].codes and CODE in groups[1].codes and view.watch_groups.selected_group==groups[1].id
	valid = valid and view.watch_groups.sort_column=="kind" and not view.watch_groups.sort_ascending and saved.watchlist_view==group_state
	view._select_stock(view._security_index(CODE))
	valid = valid and view.note_editor.text==NOTE and saved.notes.get(CODE)==NOTE and saved.security_names.get(CODE)==NAME
	valid = valid and view.operations.size()==1 and Record.validate(view.operations[0]) and saved.operations.size()==1
	valid = valid and view.simulator.account.is_empty()
	print("WATCHLIST_GROUPS_RESTART_READ: %s (new process; groups/selection/sort/favorite/name/note/operation)" % ["PASS" if valid else "FAIL"])
	quit(0 if valid else 1)

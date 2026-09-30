extends SceneTree
## Run write and read in different Godot processes with the same isolated path.
const Store = preload("res://scripts/workspace_store.gd")
const NOTE := "미보유 검증종목 가설 · 재실행 후에도 보존"
const CODE := "123456"
const NAME := "검증전자"

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()<2 or args[0] not in ["write","read"]:
		push_error("Expected write/read and an isolated absolute profile path")
		quit(1)
		return
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",args[1])
	OS.set_environment("PHALANX_CATALOG_CACHE",args[1]+".catalog.json")
	OS.set_environment("PHALANX_RESEARCH_CACHE",args[1]+".research")
	call_deferred("run")

func run() -> void:
	var args := OS.get_cmdline_user_args()
	root.size = Vector2i(1280,720)
	var dashboard: Control = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	for index: int in 6:
		await process_frame
	if args[0]=="write":
		var entry := {"code":CODE,"name":NAME,"market":"KOSPI","kind":"보통주","source":"격리 검증 목록",
			"collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}
		var fixture := {"state":"ready","collected_at":"2026-09-30T00:00:00+00:00","source":"격리 검증 목록","items":[entry],"collisions":[]}
		if not dashboard.catalog.accept_snapshot(fixture):
			push_error("Could not inject isolated catalogue")
			quit(1)
			return
		dashboard._open_catalog(CODE)
		dashboard.catalog_panel.add_button.pressed.emit()
		if dashboard.securities[dashboard.selected].code!=CODE or dashboard.watchlist_codes.count(CODE)!=1:
			push_error("Catalogue add did not select and watch the fixture")
			quit(1)
			return
		dashboard.note_editor.text = NOTE
		dashboard._note_changed()
		# Exit before the debounce interval. _exit_tree must persist the final edit.
		print("MARKET_CATALOG_RESTART_WRITE: pending note on separate process exit")
		quit(0)
		return
	var saved: Dictionary = Store.new(args[1]).load_profile()
	var index: int = dashboard._security_index(CODE)
	if index>=0:
		dashboard._select_stock(index)
	var valid: bool = CODE in dashboard.watchlist_codes and dashboard.watchlist_codes.count(CODE)==1 and index>=0
	valid = valid and dashboard.securities[index].name==NAME and dashboard.note_editor.text==NOTE
	valid = valid and dashboard.research_view.current_code==CODE and dashboard.research_view.advisor.context.code==CODE
	valid = valid and saved.security_names.get(CODE)==NAME and saved.notes.get(CODE)==NOTE
	valid = valid and saved.get("operations",[]) is Array and saved.get("live_operation_draft",{}) is Dictionary
	print("MARKET_CATALOG_RESTART_READ: %s (new process; favorite, name and note restored)" % ["PASS" if valid else "FAIL"])
	quit(0 if valid else 1)

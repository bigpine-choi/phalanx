extends SceneTree
## Execute write and read in distinct Godot processes with one isolated profile path.
const Store = preload("res://scripts/workspace_store.gd")
const Model = preload("res://scripts/nhplug_quote_model.gd")
const Fixture = preload("res://tests/operation_fixture.gd")
const Record = preload("res://scripts/operation_record.gd")
const CODE := "123456"
const NAME := "검증전자"
const NOTE := "시세 캐시와 별도로 보존하는 관찰 노트"
const PRICE := 918273645

var checks := 0
var failures := 0

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()<2 or args[0] not in ["write","read"] or not args[1].is_absolute_path():
		push_error("Expected write/read and an isolated absolute profile path")
		quit(1)
		return
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE","PHALANX_NH_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",args[1])
	OS.set_environment("PHALANX_CATALOG_CACHE",args[1]+".catalog.json")
	OS.set_environment("PHALANX_RESEARCH_CACHE",args[1]+".research")
	OS.set_environment("PHALANX_NH_QUOTE_CACHE",args[1]+".nh-quotes")
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func entry() -> Dictionary:
	return {"code":CODE,"name":NAME,"market":"KOSDAQ","kind":"보통주","source":"격리 검증 목록",
		"collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}

func find_row(rows: Array, code: String) -> Dictionary:
	for row: Dictionary in rows:
		if row.code==code:
			return row
	return {}

func run() -> void:
	var args := OS.get_cmdline_user_args()
	var profile_path: String = args[1]
	var nh_cache_path: String = (profile_path+".nh-quotes").path_join("quotes.json")
	root.size = Vector2i(1280,720)
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	root.add_child(view)
	for index: int in 6:
		await process_frame
	if not is_instance_valid(view.watch_table) or not is_instance_valid(view.research_view.nh_quotes):
		push_error("Watchlist and NH quote gateway did not initialize")
		quit(1)
		return
	if args[0]=="write":
		check(view.catalog.accept_snapshot({"state":"ready","source":"격리 검증 목록","collected_at":"2026-09-30T00:00:00+00:00","items":[entry()],"collisions":[]},true),"Isolated catalogue fixture loads")
		view._catalog_security_chosen(entry(),true)
		var id: String = view.watch_groups.create_group("시세 검증 그룹")
		view._group_membership_requested(id,CODE,true)
		view.watch_groups.select_group(id)
		view.watch_groups.set_sort("price",false)
		view._watch_preferences_changed()
		check(id.length()==32 and CODE in view.watch_groups.get_group(id).codes,"Group and price-descending preference prepared")
		Fixture.install(view,19.0)
		view._operation_draft_changed({"title":"시세 복원 검증","rationale":"기존 작전 기록 보존","risk":"격리된 검증 자료"})
		view._record_operation()
		# Sealing clears the live plan, so prepare another editable command draft.
		Fixture.install(view,19.0)
		view._operation_draft_changed({"title":"다음 명령서 초안","rationale":"새 시세와 별도로 판단","risk":"가정 가격 점검"})
		check(view.operations.size()==1 and (Record.validate(view.operations[0]) if not view.operations.is_empty() else false) and not view.simulation_plan.is_empty(),"Existing plan and sealed operation prepared")
		var now := int(Time.get_unix_time_from_system())
		var payload := {"provider":"NHPLUG","code":CODE,"market":"KRX","currency":"KRW","price":PRICE,"fetched_at":now}
		var quote: Dictionary = Model.parse(payload,CODE,now)
		check(not quote.is_empty(),"Synthetic public NH quote passes boundary validation")
		view.research_view.nh_quotes.quotes[CODE] = quote
		view.research_view.nh_quotes.states[CODE] = "ready"
		view.research_view.nh_quotes.reasons[CODE] = ""
		check(view.research_view.nh_quotes._write_cache() and FileAccess.file_exists(nh_cache_path),"Public NH quote writes to separate isolated cache")
		view.research_view.nh_quotes.changed.emit()
		view._select_stock(view._security_index(CODE))
		view.note_editor.text = NOTE
		view._note_changed()
		# Quit before debounce; tree shutdown must flush the user note and group preference.
		print("WATCHLIST_QUOTES_RESTART_WRITE: %s (%d checks; profile=%s)" % ["PASS" if failures==0 else "FAIL",checks,profile_path])
		quit(0 if failures==0 else 1)
		return
	var saved: Dictionary = Store.new(profile_path).load_profile()
	var groups: Array = view.watch_groups.groups
	var cached_text := FileAccess.get_file_as_string(nh_cache_path)
	var cached: Variant = JSON.parse_string(cached_text)
	var quote: Dictionary = view.research_view.nh_quotes.quote_for(CODE)
	var row: Dictionary = find_row(view._table_rows(),CODE)
	var workspace_text := FileAccess.get_file_as_string(profile_path)
	var security_index: int = view._security_index(CODE)
	check(saved.version==Store.VERSION and CODE in view.watchlist_codes and security_index>=0 and view.securities[security_index].name==NAME,"Watched security and name restore from v3 workspace")
	check(groups.size()==1 and groups[0].id.length()==32 and CODE in groups[0].codes and view.watch_groups.selected_group==groups[0].id,"Group identity, membership and selected group restore")
	check(view.watch_groups.sort_column=="price" and not view.watch_groups.sort_ascending and saved.watchlist_view.sort.column=="price","Descending numeric price sort restores through existing v3 field")
	view._select_stock(security_index)
	check(view.note_editor.text==NOTE and saved.notes.get(CODE)==NOTE,"Pending note restores independently of NH cache")
	check(view.operations.size()==1 and (Record.validate(view.operations[0]) if not view.operations.is_empty() else false) and saved.operations.size()==1 and not saved.simulation_plan.is_empty() and saved.live_operation_draft.title=="다음 명령서 초안","Existing plan, editable command and sealed operation survive restart")
	check(cached is Dictionary and cached.get("version")==1 and cached.get("quotes") is Array and cached.quotes.size()==1,"Separate public NH cache remains readable")
	if cached is Dictionary and cached.get("quotes") is Array and cached.quotes.size()==1:
		check(cached.quotes[0].price==PRICE and int(cached.quotes[0].fetched_at)==int(quote.get("fetched_at",-1)),"Cached price and receipt timestamp match restored gateway")
	else:
		check(false,"Cached price and receipt timestamp match restored gateway")
	var expected_time := Time.get_datetime_string_from_unix_time(int(quote.get("fetched_at",0))+9*3600).replace("T"," ")
	check(quote.get("price")==PRICE and row.get("price")==PRICE and row.get("quote_source")=="NH · KRX" and row.get("quote_time")==expected_time,"Restored quote appears in the table with source and receipt time")
	check(not workspace_text.contains(str(PRICE)) and not workspace_text.contains("NHPLUG") and not workspace_text.contains("nh_quotes"),"NH quote cache and price are absent from workspace JSON")
	check(view.simulator.account.is_empty(),"No account observation was loaded or requested")
	print("WATCHLIST_QUOTES_RESTART_READ: %s (%d checks; new process; isolated profile/NH cache)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

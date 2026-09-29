extends SceneTree
const Fixture = preload("res://tests/operation_fixture.gd")
const Store = preload("res://scripts/workspace_store.gd")
const Record = preload("res://scripts/operation_record.gd")
const Data = preload("res://scripts/market_data.gd")
var checks := 0
var failures := 0
var directory: String
const DRAFT := {"title":"검증용 · 방어적 재배치","rationale":"예시 판단 근거\n현금 여력을 남긴다.","risk":"예시 위험: 샘플 가격과 실제 시장의 차이"}

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	directory = OS.get_environment("TEMP").path_join("phalanx-operations-%s-%s" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func write(path: String, content: String) -> void:
	var file := FileAccess.open(path,FileAccess.WRITE)
	file.store_string(content)
	file.close()

func frames() -> void:
	for i: int in 8:
		await process_frame

func dashboard(path: String) -> Control:
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	view.storage_path = path
	root.add_child(view)
	return view

func run() -> void:
	root.gui_embed_subwindows = true
	root.size = Vector2i(1440,960)
	var path := directory.path_join("profile.json")
	var legacy := {"version":1,"watchlist":["005930"],"notes":{"005930":"보존할 노트"},"extension":{"test":true}}
	var original := JSON.stringify(legacy)
	write(path,original)
	var store := Store.new(path)
	var state: Dictionary = store.load_profile()
	check(state.version==2 and state.operations.is_empty(),"v1 migrates to empty history")
	check(FileAccess.get_file_as_string(path)==original,"Loading v1 does not rewrite disk")
	check(state.notes==legacy.notes and state.extension==legacy.extension,"Migration preserves notes and unknown fields")
	var view := dashboard(path)
	await frames()
	Fixture.install(view,20.0)
	view._operation_draft_changed(DRAFT)
	view.flush_profile()
	check(not view.save_failed,"New draft and targets save")
	check(FileAccess.get_file_as_string(path+".bak")==original,"First migration save backs up original v1 bytes")
	state = Store.new(path).load_profile()
	check(state.simulation_plan.rows[0].target==20 and state.live_operation_draft==DRAFT,"Draft and targets persist")
	check(state.notes==legacy.notes and state.extension==legacy.extension,"Extended save preserves previous user content")
	view._show_plan()
	await frames()
	view._record_operation()
	check(view.operations.size()==1 and view.dialog.recorded,"Successful disk save seals exactly one record")
	check(view.live_operation_draft==Record.empty_draft(),"Successful save prepares a fresh draft")
	var recorded: Dictionary = view.operations[0].duplicate(true)
	check(Record.validate(recorded),"Recorded snapshot validates")
	check(recorded.rows[0].target==20 and recorded.rows[0].price==72000 and recorded.rows[0].quantity==200,"Snapshot retains exact target, source price and base holding")
	check(recorded.rationale==DRAFT.rationale and recorded.risk==DRAFT.risk,"Reason and risk preserved")
	check(recorded.source==Record.LIVE_SOURCE and recorded.local_time.length()==19,"Timestamp and synthetic provenance retained")
	check(not view.dialog.document.rationale_input.editable and not view.dialog.document.title_input.editable,"Sealed document is read only")
	view._record_operation()
	check(view.operations.size()==1,"Repeated confirm does not duplicate record")
	view.dialog.hide()
	Fixture.install(view,12.0)
	view._operation_draft_changed({"title":"次の計画","rationale":"초안 변경","risk":"변경한 위험"})
	view.flush_profile()
	check(view.operations[0]==recorded,"Subsequent planning does not mutate historical snapshot")
	view.queue_free()
	await frames()
	view = dashboard(path)
	await frames()
	check(view.simulation_plan.rows[0].target==12 and view.live_operation_draft.rationale=="초안 변경","Recreated dashboard restores targets and unfinished draft")
	check(view.operations.size()==1 and view.operations[0]==JSON.parse_string(JSON.stringify(recorded)),"Recreated dashboard restores immutable record")
	view._show_plan()
	view._operation_draft_changed(Record.empty_draft())
	view._record_operation()
	check(view.operations.size()==1 and not view.dialog.recorded,"Incomplete draft cannot seal")
	view._operation_draft_changed(DRAFT)
	var malformed: Dictionary = view.simulation_plan.duplicate(true)
	malformed.base_assets += 1000
	view.simulation_plan = malformed
	view._record_operation()
	check(view.operations.size()==1,"Inconsistent live snapshot cannot seal")
	Fixture.install(view)
	view.flush_profile()
	check(Store.new(path).load_profile().simulation_plan.rows[0].target==20,"Live plan persists after correction")
	# A competing writer must prevent a misleading success seal or lost content.
	var competitor := Store.new(path)
	state = competitor.load_profile()
	check(competitor.save_profile(state.watchlist,{"005930":"다른 창의 메모"}),"Competing writer fixture saved")
	view._record_operation()
	check(view.operations.size()==1 and not view.dialog.recorded and view.save_failed,"Conflict leaves history unchanged and no completion seal")
	check(view.live_operation_draft==DRAFT,"Failed record keeps editable draft")
	check(Store.new(path).load_profile().notes["005930"]=="다른 창의 메모","Conflict does not overwrite another writer")
	view.dialog.hide()
	view.profile_dirty = false
	view.queue_free()
	await frames()
	# A temporarily unwritable parent exercises retry after actual IO failure.
	var blocker := directory.path_join("parent-is-file")
	write(blocker,"fixture")
	var retry := dashboard(blocker.path_join("profile.json"))
	await frames()
	Fixture.install(retry)
	retry._show_plan()
	retry._operation_draft_changed(DRAFT)
	retry._record_operation()
	check(retry.operations.is_empty() and not retry.dialog.recorded and retry.save_failed,"IO failure does not append or seal")
	DirAccess.remove_absolute(blocker)
	retry._record_operation()
	check(retry.operations.size()==1 and retry.dialog.recorded and not retry.save_failed,"Same confirmation retries successfully after IO recovery")
	retry._record_operation()
	check(retry.operations.size()==1,"Retried save still cannot duplicate")
	retry.queue_free()
	await frames()
	for key: String in ["planned_cash","base_assets","target_total"]:
		var corrupt := recorded.duplicate(true)
		corrupt[key] += 1000
		check(not Record.validate(corrupt),"Inconsistent financial snapshot rejected: "+key)
	var bad := recorded.duplicate(true)
	bad.rows[0].price = NAN
	check(not Record.validate(bad),"Nonfinite price rejected")
	bad = recorded.duplicate(true)
	bad.rows[0].delta += 1
	check(not Record.validate(bad),"Inconsistent trade quantity rejected")
	state = Store.defaults()
	state.operations = [recorded,recorded.duplicate(true)]
	check(not Store.validate(state),"Duplicate history identifiers rejected")
	check(not Record.valid_draft({"title":"x","rationale":"x".repeat(2001),"risk":"x"}),"Oversized rationale rejected")
	check(not Record.valid_targets({"005930":NAN}),"Nonfinite weights rejected")
	var archived_sample := recorded.duplicate(true)
	archived_sample.source = Record.SOURCE
	state = Store.defaults()
	state.operations = [archived_sample]
	state.targets = {"005930":18}
	state.operation_draft = DRAFT.duplicate(true)
	check(Store.validate(state),"Old sample records and draft fields remain readable for existing profiles")
	check(Record.from_snapshot(archived_sample,DRAFT).is_empty(),"Old sample plans cannot create new records")
	check(not Store.defaults().has("targets") and not Store.defaults().has("operation_draft"),"New profiles contain no sample account state")
	print("PHALANX_OPERATIONS_TEST: %s (%d checks; isolated profiles)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

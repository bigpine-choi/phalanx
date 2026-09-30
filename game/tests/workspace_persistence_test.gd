extends SceneTree
const Store = preload("res://scripts/workspace_store.gd")
var checks := 0
var failures := 0
var directory: String

func _initialize() -> void:
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	directory = OS.get_environment("TEMP").path_join("phalanx-persistence-test-%s-%s" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	call_deferred("run")

func check(value: bool, description: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(description)

func write(path: String, content: String) -> void:
	var file := FileAccess.open(path,FileAccess.WRITE)
	assert(file != null)
	file.store_string(content)
	file.close()

func frames(count := 5) -> void:
	for index: int in count:
		await process_frame

func click(control: Control) -> void:
	var point := control.get_global_rect().get_center()
	for pressed: bool in [true,false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.global_position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame

func new_dashboard(path: String) -> Control:
	var result: Control = load("res://scenes/headquarters.tscn").instantiate()
	result.embedded_in_camp = true
	result.storage_path = path
	root.add_child(result)
	return result

func run() -> void:
	var path := directory.path_join("profile.json")
	var store := Store.new(path)
	var fresh: Dictionary = store.load_profile()
	check(fresh.watchlist.size()==5 and fresh.notes.is_empty(),"First launch starts with the existing five demo stocks")
	check(not FileAccess.file_exists(path),"Opening a fresh profile must not write defaults")
	var note := "투자 가설: 수요 회복\n반대 근거: \"가격 하락\"\n다음 확인: 성장률 3% · α 📈"
	check(store.save_profile(["005930"],{"005930":note}),"UTF-8 note and custom watchlist must save")
	var loaded := Store.new(path)
	var state: Dictionary = loaded.load_profile()
	check(state.watchlist==["005930"] and state.notes["005930"]==note,"A new store instance must restore exact multiline Unicode")
	check(loaded.save_profile([],{}),"An intentionally empty watchlist and notes must save")
	var empty: Dictionary = Store.new(path).load_profile()
	check(empty.watchlist.is_empty() and empty.notes.is_empty(),"Empty saved data must not repopulate defaults")
	check(FileAccess.file_exists(path+".bak"),"Replacing a valid profile must retain its previous snapshot")
	write(path,"{broken-write")
	var recovering := Store.new(path)
	var restored: Dictionary = recovering.load_profile()
	check(restored.notes.get("005930")==note and not recovering.blocked,"Corrupt primary must recover the last valid backup")
	check(not recovering.message.is_empty(),"Recovery must be visible to the user")
	check(recovering.save_profile(restored.watchlist,restored.notes),"Recovered state must be writable")
	var archived := false
	for filename: String in DirAccess.get_files_at(directory):
		if filename.begins_with("profile.json.damaged-"):
			archived = FileAccess.get_file_as_string(directory.path_join(filename))=="{broken-write"
	check(archived,"Recovery must archive damaged bytes instead of silently discarding them")
	var corrupt_path := directory.path_join("unrecoverable.json")
	write(corrupt_path,"not json")
	var corrupt := Store.new(corrupt_path)
	corrupt.load_profile()
	check(corrupt.blocked and not corrupt.save_profile([],{}),"Unrecoverable profile must block overwrite")
	check(FileAccess.get_file_as_string(corrupt_path)=="not json","Unreadable original must remain intact")
	var future_path := directory.path_join("future.json")
	write(future_path,JSON.stringify({"version":Store.VERSION+1,"watchlist":[],"notes":{"005930":"future"}}))
	write(future_path+".bak",JSON.stringify(Store.defaults()))
	var future := Store.new(future_path)
	future.load_profile()
	check(future.blocked and not future.save_profile([],{}),"Newer schema must not be downgraded via backup")
	check(JSON.parse_string(FileAccess.get_file_as_string(future_path)).version==Store.VERSION+1,"Future schema must remain intact")
	for invalid: Variant in [[],{}, {"version":1,"watchlist":"bad","notes":{}}, {"version":1,"watchlist":["005930","005930"],"notes":{}}, {"version":1,"watchlist":[],"notes":{"005930":17}}]:
		check(not Store.validate(invalid),"Malformed schema must be rejected")
	var unknown_path := directory.path_join("unknown.json")
	write(unknown_path,JSON.stringify({"version":1,"watchlist":["FUTURE"],"notes":{"FUTURE":"keep me"},"extension":"keep too"}))
	var unknown := Store.new(unknown_path)
	var unknown_state: Dictionary = unknown.load_profile()
	check(unknown.save_profile(unknown_state.watchlist,unknown_state.notes),"Unknown catalogue codes remain savable")
	check(JSON.parse_string(FileAccess.get_file_as_string(unknown_path)).extension=="keep too","Unknown schema fields must survive normal edits")
	var missing_path := directory.path_join("missing-primary.json")
	write(missing_path+".bak",JSON.stringify({"version":1,"watchlist":[],"notes":{"005930":"backup only"}}))
	var missing := Store.new(missing_path)
	check(missing.load_profile().notes.get("005930")=="backup only","Missing primary must also recover backup")
	var conflict_path := directory.path_join("conflict.json")
	var first := Store.new(conflict_path)
	var second := Store.new(conflict_path)
	first.load_profile()
	second.load_profile()
	check(first.save_profile([],{"005930":"first"}),"First writer may save")
	check(not second.save_profile([],{"005930":"second"}),"A stale window must not overwrite another saved profile")
	check(Store.new(conflict_path).load_profile().notes.get("005930")=="first","Conflict preserves the already saved note")
	var obstacle := directory.path_join("not-a-directory")
	write(obstacle,"obstacle")
	var failing := Store.new(obstacle.path_join("profile.json"))
	failing.load_profile()
	check(not failing.save_profile([],{}),"Unwritable destination must return failure")
	check(not failing.message.is_empty(),"Write failure must have a user-visible explanation")
	var limited := Store.new(directory.path_join("limit.json"))
	limited.load_profile()
	check(not limited.save_profile([],{"005930":"x".repeat(Store.MAX_NOTE_LENGTH+1)}) and limited.message.contains("너무 길"),"Oversized notes must not silently truncate")
	root.size = Vector2i(1280,720)
	var ui_path := directory.path_join("ui.json")
	var dashboard := new_dashboard(ui_path)
	await frames()
	await click(dashboard.favorite_button)
	check(not dashboard.stock_buttons[0].visible and dashboard.watch_count.text=="4","Removing a favorite must update its row and count")
	dashboard.search.text = "005930"
	dashboard._filter_stocks(dashboard.search.text)
	check(dashboard.stock_buttons[0].visible,"Search must find a removed favorite")
	await click(dashboard.favorite_button)
	check("005930" in dashboard.watchlist_codes,"Search result can be added to favorites again")
	dashboard.search.text = ""
	dashboard._filter_stocks("")
	for index: int in 5:
		dashboard._select_stock(index)
		dashboard._toggle_favorite()
	check(dashboard.empty_label.visible and dashboard.watch_count.text=="0","Empty watchlist must display a useful recovery path")
	await click(dashboard.all_stocks_button)
	check(dashboard.stock_buttons[0].visible and dashboard.stock_buttons[4].visible,"All stocks must remain discoverable from an empty watchlist")
	dashboard._select_workspace("research")
	dashboard._select_stock(0)
	dashboard.note_editor.text = note
	dashboard._note_changed()
	await create_timer(0.7).timeout
	check(not dashboard.profile_dirty and not dashboard.save_failed,"Debounced autosave must finish without requiring navigation")
	check(Store.new(ui_path).load_profile().notes.get("005930")==note,"Autosave must reach disk")
	dashboard.note_editor.text = "last input before close"
	dashboard._note_changed()
	dashboard.queue_free()
	await frames()
	dashboard = new_dashboard(ui_path)
	await frames()
	check(dashboard.note_editor.text=="last input before close","Scene shutdown must flush the final pending edit")
	check(dashboard.watchlist_codes.is_empty(),"UI relaunch must restore an intentionally empty watchlist")
	dashboard.note_editor.text = ""
	dashboard._note_changed()
	dashboard._select_stock(1)
	check(not Store.new(ui_path).load_profile().notes.has("005930"),"Clearing a note must persist as deletion")
	dashboard.note_editor.text = "stock 1"
	dashboard._note_changed()
	dashboard._select_stock(2)
	check(dashboard.note_editor.text.is_empty(),"Different stock must not inherit a pending note")
	dashboard._select_stock(1)
	check(dashboard.note_editor.text=="stock 1","Stock switch must flush and restore the correct note")
	dashboard.queue_free()
	await frames()
	var failure_ui := new_dashboard(obstacle.path_join("failure-ui.json"))
	await frames()
	failure_ui.note_editor.text = "keep unsaved"
	failure_ui._note_changed()
	failure_ui.flush_profile()
	check(failure_ui.save_failed and failure_ui.profile_dirty and failure_ui.retry_save_button.visible,"UI must show failed saves and offer retry")
	check(failure_ui.note_editor.text=="keep unsaved","Save failure must not clear the user's edit")
	DirAccess.rename_absolute(obstacle,obstacle+".previous")
	DirAccess.make_dir_recursive_absolute(obstacle)
	await click(failure_ui.retry_save_button)
	check(not failure_ui.profile_dirty and not failure_ui.save_failed,"Retry must clear the error only after writing successfully")
	check(Store.new(obstacle.path_join("failure-ui.json")).load_profile().notes.get("005930")=="keep unsaved","Retry must save the previously unsaved edit")
	failure_ui.queue_free()
	await frames()
	print("PHALANX_WORKSPACE_PERSISTENCE_TEST: %s (%d checks; isolated files)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

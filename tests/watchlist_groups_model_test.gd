extends SceneTree
const Groups = preload("res://scripts/watchlist_groups.gd")
const Store = preload("res://scripts/workspace_store.gd")
const Fixture = preload("res://tests/operation_fixture.gd")
const Record = preload("res://scripts/operation_record.gd")

var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func write(path: String, contents: String) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	assert(file != null)
	file.store_string(contents)
	file.close()

func table_row(code: String, name: String, held: bool, status: String) -> Dictionary:
	return {"code":code,"name":name,"market":"KOSPI","kind":"보통주","held":held,"status":status}

func run() -> void:
	var directory := OS.get_environment("TEMP").path_join("phalanx-groups-model-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	check(DirAccess.make_dir_recursive_absolute(directory) == OK, "Isolated test directory created")
	var groups := Groups.new()
	check(Groups.validate_state(Groups.defaults()) and groups.export_state() == Groups.defaults(), "Default group state is valid")
	var first: String = groups.create_group("  반도체  ")
	check(first.length() == 32 and Groups._valid_id(first) and groups.get_group(first).name == "반도체", "Created group has stable random ID and trimmed name")
	check(groups.create_group("반도체").is_empty() and groups.groups.size() == 1, "Duplicate Korean group name is rejected")
	check(groups.create_group("Tech") != "" and groups.create_group("tech").is_empty(), "Duplicate Latin names are case insensitive")
	check(groups.rename_group(first,"  핵심  ") and groups.get_group(first).name == "핵심", "Rename keeps group identity")
	check(not groups.rename_group(first,"TECH") and groups.get_group(first).name == "핵심", "Rename rejects duplicate name")
	check(groups.add_code(first,"005930") and groups.add_code(first,"005935"), "Group accepts watched stock and preferred codes")
	check(not groups.add_code(first,"005930") and not groups.add_code(first,"bad-code"), "Duplicate and unsupported group codes rejected")
	var second: String = groups.groups[1].id
	check(groups.add_code(second,"005935"), "A watched code may appear in two groups")
	check(groups.select_group(first) and groups.selected_group == first, "Custom group selection retained")
	check(not groups.select_group("missing") and groups.selected_group == first, "Unknown selection cannot replace current group")
	var rows := [table_row("005930","Beta",false,"—"),table_row("000660","Alpha",true,"fresh"),table_row("005935","Alpha",false,"stale"),table_row("069500","ETF",false,"fresh")]
	var watched := ["005930","005935"]
	groups.select_group("all")
	check(groups.rows_for(rows,watched).map(func(row: Dictionary) -> String: return row.code) == ["005935","005930"], "All interest rows filter the watchlist and break name ties by code")
	groups.select_group("holdings")
	check(groups.rows_for(rows,watched).size() == 1 and groups.rows_for(rows,watched)[0].code == "000660", "Holdings selection includes an unwatched holding")
	var conflicted := table_row("035420","Conflict",false,"식별자 확인")
	conflicted.account_present = true
	rows.append(conflicted)
	check(groups.rows_for(rows,watched).size() == 2 and groups.rows_for(rows,watched)[1].code == "035420" and not groups.rows_for(rows,watched)[1].held, "Account identity conflict stays visible in holdings without becoming a verified holding")
	groups.select_group(first)
	groups.set_sort("status",false)
	check(groups.rows_for(rows,watched).map(func(row: Dictionary) -> String: return row.code) == ["005935","005930"], "Unknown status sorts last even descending")
	groups.set_sort("status",true)
	check(groups.rows_for(rows,watched).map(func(row: Dictionary) -> String: return row.code) == ["005935","005930"], "Unknown status sorts last ascending")
	groups.set_sort("code",false)
	check(groups.rows_for(rows,watched)[0].code == "005935", "Code sorting direction applies")
	var old_sort := groups.sort_column
	groups.set_sort("price",true)
	check(groups.sort_column == old_sort and not groups.message.is_empty(), "Unsupported sort column cannot replace saved preference")
	groups.remove_code_everywhere("005935")
	check(groups.get_group(first).codes == ["005930"] and groups.get_group(second).codes.is_empty() and watched.has("005935"), "Global unwatch removes group memberships without mutating watchlist")
	check(groups.remove_code(first,"005930") and not groups.remove_code(first,"005930"), "Removing a group member is idempotent and signalled")
	groups.add_code(first,"005930")
	check(groups.delete_group(first) and groups.selected_group == "all" and watched.has("005930"), "Deleting selected group resets selection but preserves global interest")
	check(not groups.delete_group(first), "Deleted group ID cannot be reused for deletion")
	var valid := groups.export_state()
	check(Groups.validate_state(valid), "Edited group state validates")
	var invalid: Dictionary = valid.duplicate(true)
	invalid.groups[0].name = " tech "
	check(not Groups.validate_state(invalid), "Untrimmed stored group name is rejected")
	invalid = valid.duplicate(true)
	invalid.groups[0].codes = ["005930","005930"]
	check(not Groups.validate_state(invalid), "Duplicate saved membership is rejected")
	invalid = valid.duplicate(true)
	invalid.selected_group = "missing"
	check(not Groups.validate_state(invalid), "Missing saved selection is rejected")
	invalid = valid.duplicate(true)
	invalid.groups.append(valid.groups[0].duplicate(true))
	invalid.groups[1].id = "a".repeat(32)
	invalid.groups[1].name = valid.groups[0].name.to_upper()
	check(not Groups.validate_state(invalid), "Duplicate saved names are case insensitive")
	var limit_groups := Groups.new()
	for index: int in Groups.MAX_GROUPS:
		limit_groups.create_group("그룹 %d" % index)
	check(limit_groups.groups.size() == Groups.MAX_GROUPS and limit_groups.create_group("초과").is_empty(), "Maximum group count enforced")
	var excessive := Groups.defaults()
	var many_codes: Array = []
	for code_number: int in Groups.MAX_MEMBERS + 1:
		many_codes.append("%06d" % code_number)
	excessive.groups = [{"id":"a".repeat(32),"name":"너무 큰 그룹","codes":many_codes}]
	check(not Groups.validate_state(excessive), "Maximum membership count enforced")
	var restored_groups := Groups.new()
	check(restored_groups.load_state(valid) and restored_groups.export_state() == valid, "Group state round trips independently of UI")
	var before_invalid := restored_groups.export_state()
	check(not restored_groups.load_state(invalid) and restored_groups.export_state() == before_invalid, "Invalid load does not mutate live preferences")

	var draft := {"title":"그룹 저장 검증","rationale":"기존 판단 근거 보존","risk":"기존 위험 보존"}
	var record: Dictionary = Fixture.create([18,16,22,8,14],draft)
	check(Record.validate(record), "Migration fixture has a real valid operation record")
	var v2: Dictionary = Store.defaults()
	v2.version = 2
	v2.erase("watchlist_view")
	v2.watchlist = ["005930","005935"]
	v2.notes = {"005935":"우선주 노트 보존"}
	v2.security_names = {"005935":"삼성전자우"}
	v2.operations = [record]
	v2.live_operation_draft = draft
	v2.extension = {"private":"keep"}
	var path := directory.path_join("profile.json")
	var original := JSON.stringify(v2)
	var stored_record: Dictionary = JSON.parse_string(JSON.stringify(record))
	write(path,original)
	var store := Store.new(path)
	var migrated := store.load_profile()
	check(not store.blocked and migrated.version == 3 and migrated.watchlist_view == Groups.defaults(), "Valid v2 migrates to v3 group defaults in memory")
	check(FileAccess.get_file_as_string(path) == original, "Loading v2 leaves original bytes unchanged")
	check(migrated.notes == v2.notes and migrated.operations == [stored_record] and migrated.live_operation_draft == draft and migrated.extension == v2.extension, "v2 notes, record, draft and unknown fields survive migration")
	var saved_group := Groups.new()
	var saved_id := saved_group.create_group("우선주")
	saved_group.add_code(saved_id,"005935")
	saved_group.select_group(saved_id)
	saved_group.set_sort("kind",false)
	check(store.save_profile(migrated.watchlist,migrated.notes,{"watchlist_view":saved_group.export_state()}), "Migrated v2 profile saves with group state")
	check(FileAccess.get_file_as_string(path+".bak") == original, "First v3 save backs up exact original v2 bytes")
	var reloaded := Store.new(path).load_profile()
	check(reloaded.watchlist_view == saved_group.export_state() and reloaded.notes == v2.notes and reloaded.operations == [stored_record] and reloaded.live_operation_draft == draft, "v3 reload retains groups and all previous user work")
	var unchanged := FileAccess.get_file_as_string(path)
	check(not store.save_profile([],migrated.notes,{"watchlist_view":saved_group.export_state()}) and FileAccess.get_file_as_string(path) == unchanged, "Group membership outside watchlist cannot be saved")
	check(saved_group.delete_group(saved_id) and store.save_profile(migrated.watchlist,migrated.notes,{"watchlist_view":saved_group.export_state()}), "Group deletion saves without changing interests")
	var after_delete := Store.new(path).load_profile()
	check(after_delete.watchlist == v2.watchlist and after_delete.notes == v2.notes and after_delete.operations == [stored_record] and after_delete.watchlist_view.groups.is_empty(), "Deleting a group preserves notes, watchlist and operation history")
	var corrupt_v2: Dictionary = v2.duplicate(true)
	corrupt_v2.operations = [{"bad":"record"}]
	var bad_path := directory.path_join("invalid-v2.json")
	var bad_original := JSON.stringify(corrupt_v2)
	write(bad_path,bad_original)
	var bad_store := Store.new(bad_path)
	bad_store.load_profile()
	check(bad_store.blocked and FileAccess.get_file_as_string(bad_path) == bad_original, "Malformed v2 is rejected before adding v3 fields")
	var v1: Dictionary = v2.duplicate(true)
	v1.version = 1
	var v1_path := directory.path_join("legacy-v1.json")
	var v1_original := JSON.stringify(v1)
	write(v1_path,v1_original)
	var old_store := Store.new(v1_path)
	var old_loaded := old_store.load_profile()
	check(not old_store.blocked and old_loaded.version == 3 and old_loaded.operations == [stored_record] and old_loaded.live_operation_draft == draft, "v1 migration preserves existing record and draft fields")
	check(old_store.save_profile(old_loaded.watchlist,old_loaded.notes) and FileAccess.get_file_as_string(v1_path+".bak") == v1_original, "First v1 migration save preserves exact original backup")
	var unknown_path := directory.path_join("unknown-code.json")
	var unknown_legacy: Dictionary = v2.duplicate(true)
	unknown_legacy.watchlist = ["FUTURE7"]
	unknown_legacy.notes = {"FUTURE7":"legacy note"}
	unknown_legacy.security_names = {}
	write(unknown_path,JSON.stringify(unknown_legacy))
	var unknown_store := Store.new(unknown_path)
	var unknown_state := unknown_store.load_profile()
	check(unknown_state.watchlist == ["FUTURE7"] and unknown_store.save_profile(unknown_state.watchlist,unknown_state.notes), "Unknown legacy code and note survive v2 migration")
	print("WATCHLIST_GROUPS_MODEL_TEST ",checks," checks, ",failures," failures")
	quit(1 if failures else 0)

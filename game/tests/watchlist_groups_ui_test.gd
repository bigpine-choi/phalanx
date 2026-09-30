extends SceneTree
## Group/table integration on an isolated offline workspace and catalogue.
const Store = preload("res://scripts/workspace_store.gd")

var checks := 0
var failures := 0
var directory := ""

func _initialize() -> void:
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	directory = OS.get_environment("TEMP").path_join("phalanx-watch-groups-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("profile.json"))
	OS.set_environment("PHALANX_CATALOG_CACHE",directory.path_join("catalog.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func frames(count := 6) -> void:
	for index: int in count:
		await process_frame

func item(code: String, name: String, market: String = "KOSPI", kind: String = "보통주") -> Dictionary:
	return {"code":code,"name":name,"market":market,"kind":kind,"source":"격리 검증 목록",
		"collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}

func catalog_fixture() -> Dictionary:
	return {"state":"ready","collected_at":"2026-09-30T00:00:00+00:00","source":"격리 검증 목록","collisions":[],"items":[
		item("005930","삼성전자","KOSPI","보통주"),item("000660","SK하이닉스","KOSPI","보통주"),
		item("069500","KODEX 200","ETF","ETF"),item("123456","검증전자","KOSDAQ","보통주"),
		item("123457","검증화학","KOSDAQ","우선주")]}

func account_snapshot(code: String, name: String, marker: String) -> Dictionary:
	var holding := {"code":code,"name":name,"quantity":"10","sellable":"10","price":"100","value":"1000","broker_value":"1000",
		"profit_loss":"0","stock_weight":"100","price_observed_at":"2026-09-29T12:00:00+00:00"}
	return {"version":1,"source":"kis_account","currency":"KRW","snapshot_id":marker.repeat(64),"account_masked":"0000****-**",
		"observed_at":"2026-09-29T12:00:00+00:00","positions_value":"1000",
		"summary":{"net_assets":"1000","deposit_total":"0","securities_evaluation_amount":"1000","profit_loss_total":"0"},
		"warnings":[],"rows":[holding]}

func observation(code: String) -> Dictionary:
	var now := int(Time.get_unix_time_from_system())
	var first := Time.get_datetime_string_from_unix_time(now+9*3600-5*86400).left(10)
	var second := Time.get_datetime_string_from_unix_time(now+9*3600-4*86400).left(10)
	var end := Time.get_datetime_string_from_unix_time(now+9*3600-86400).left(10)
	return {"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":now,"requested_start":first,
		"requested_end":end,"candles":[{"date":first,"open":100.0,"high":110.0,"low":90.0,"close":100.0,"volume":100},
			{"date":second,"open":100.0,"high":115.0,"low":95.0,"close":110.0,"volume":200}]}

func find_row(rows: Array, code: String) -> Dictionary:
	for row: Dictionary in rows:
		if row.code==code:
			return row
	return {}

func codes(rows: Array) -> Array:
	var result: Array = []
	for row: Dictionary in rows:
		result.append(row.code)
	return result

func select_table_code(panel: Control, code: String) -> bool:
	var item: TreeItem = panel.table.get_root().get_first_child() if panel.table.get_root()!=null else null
	while item!=null:
		if str(item.get_metadata(0))==code:
			panel.table.set_selected(item,0)
			return true
		item = item.get_next()
	return false

func table_first_code(panel: Control) -> String:
	if panel.table.get_root()==null or panel.table.get_root().get_first_child()==null:
		return ""
	return str(panel.table.get_root().get_first_child().get_metadata(0))

func mouse_select_table_code(panel: Control, code: String) -> bool:
	var item: TreeItem = panel.table.get_root().get_first_child() if panel.table.get_root()!=null else null
	while item!=null and str(item.get_metadata(0))!=code:
		item = item.get_next()
	if item==null:
		return false
	panel.table.scroll_to_item(item)
	await frames(2)
	var area: Rect2 = panel.table.get_item_area_rect(item,0)
	var point: Vector2 = panel.table.get_global_rect().position + area.get_center()
	var press := InputEventMouseButton.new()
	press.button_index = MOUSE_BUTTON_LEFT
	press.pressed = true
	press.position = point
	press.global_position = point
	root.push_input(press,false)
	var release := InputEventMouseButton.new()
	release.button_index = MOUSE_BUTTON_LEFT
	release.pressed = false
	release.position = point
	release.global_position = point
	root.push_input(release,false)
	await frames(6)
	return panel.selected_code==code

func escape_key() -> void:
	for is_pressed: bool in [true,false]:
		var event := InputEventKey.new()
		event.keycode = KEY_ESCAPE
		event.physical_keycode = KEY_ESCAPE
		event.pressed = is_pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()

func run() -> void:
	root.size = Vector2i(1280,720)
	var dashboard: Control = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	await frames()
	check(dashboard.watch_groups.groups.is_empty() and dashboard.watch_groups.selected_group=="all","First launch starts with the All view and no custom groups")
	dashboard._open_watch_table()
	check(dashboard.watch_table.visible and dashboard.workspace=="market","Table opens from the market workspace")
	var panel: Control = dashboard.watch_table
	if panel.table.get_root()==null or panel.visible_rows.size()!=5:
		push_error("Watchlist Tree did not render five fixture rows")
		quit(1)
		return
	for dimensions: Vector2i in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = dimensions
		await frames(2)
		var rect: Rect2 = panel.card.get_global_rect()
		check(rect.position.x>=0 and rect.position.y>=0 and rect.end.x<=dimensions.x+1 and rect.end.y<=dimensions.y+1 and panel.table.size.y>=210,"Table fits viewport "+str(dimensions))
	check(dashboard._table_rows().size()==5 and not dashboard._table_rows()[0].has("price"),"Table rows contain metadata and status without invented prices")
	check(find_row(dashboard._table_rows(),"035420").market=="—" and find_row(dashboard._table_rows(),"035420").kind=="—","Unknown market and kind display a missing-data dash")
	dashboard._select_stock(dashboard._security_index("005930"))
	dashboard.note_editor.text = "그룹에서 해제해도 남을 노트"
	dashboard._note_changed()
	dashboard.flush_profile()
	var growth: String = dashboard.watch_groups.create_group("성장 관찰")
	var income: String = dashboard.watch_groups.create_group("배당 관찰")
	check(growth.length()==32 and income.length()==32 and growth!=income,"Two groups receive stable distinct IDs")
	dashboard._watch_preferences_changed()
	dashboard._group_membership_requested(growth,"005930",true)
	dashboard._group_membership_requested(income,"005930",true)
	dashboard._group_membership_requested(income,"069500",true)
	check("005930" in dashboard.watch_groups.get_group(growth).codes and "005930" in dashboard.watch_groups.get_group(income).codes,"A security may belong to multiple groups")
	check(dashboard.watch_groups.rename_group(growth,"성장 점검") and dashboard.watch_groups.get_group(growth).id==growth,"Rename keeps the group ID")
	dashboard.watch_groups.select_group(income)
	dashboard._watch_preferences_changed()
	check(codes(dashboard.watch_groups.rows_for(dashboard._table_rows(),dashboard.watchlist_codes)).size()==2,"Selected custom group filters table rows")
	dashboard._group_membership_requested(income,"005930",false)
	check("005930" in dashboard.watchlist_codes and "005930" in dashboard.watch_groups.get_group(growth).codes and not "005930" in dashboard.watch_groups.get_group(income).codes and dashboard.notes_by_code.get("005930")=="그룹에서 해제해도 남을 노트","Removing one membership preserves global watch, another group and the exact note")
	check(dashboard.watch_groups.delete_group(income) and "069500" in dashboard.watchlist_codes,"Deleting a group preserves its securities in All")
	dashboard._watch_preferences_changed()
	check(dashboard.watch_groups.selected_group=="all" and dashboard.watch_groups.get_group(growth).name=="성장 점검" and dashboard.notes_by_code.get("005930")=="그룹에서 해제해도 남을 노트","Deleting selected group keeps other group and the exact note")
	panel.group_name_edit.text = "화면에서 만든 그룹"
	panel.create_button.pressed.emit()
	var ui_group: String = dashboard.watch_groups.selected_group
	check(dashboard.watch_groups.has_group(ui_group) and dashboard.watch_groups.get_group(ui_group).name=="화면에서 만든 그룹","Create button selects the new stable-ID group")
	panel.group_name_edit.text = "화면에서 변경한 그룹"
	panel.rename_button.pressed.emit()
	check(dashboard.watch_groups.get_group(ui_group).name=="화면에서 변경한 그룹","Rename button preserves the group ID")
	panel.delete_button.pressed.emit()
	check(panel.confirm_bar.visible,"Delete button requires an explicit confirmation")
	panel.handle_escape()
	check(dashboard.watch_groups.has_group(ui_group) and not panel.confirm_bar.visible,"Escape cancels pending group deletion")
	panel.delete_button.pressed.emit()
	panel.confirm_bar.get_child(1).pressed.emit()
	check(not dashboard.watch_groups.has_group(ui_group) and "005930" in dashboard.watchlist_codes and dashboard.notes_by_code.get("005930")=="그룹에서 해제해도 남을 노트","Confirmed UI deletion preserves watch and note")
	check(dashboard.catalog.accept_snapshot(catalog_fixture()),"Offline catalogue metadata fixture loads without WSL")
	var raw_rows: Array = dashboard._table_rows()
	check(find_row(raw_rows,"005930").market=="KOSPI" and find_row(raw_rows,"069500").kind=="ETF" and find_row(raw_rows,"035420").market=="—","Table joins matching catalogue identity and leaves unknown metadata blank")
	dashboard.simulator.set_account(account_snapshot("005930","삼성전자","a"))
	await frames()
	raw_rows = dashboard._table_rows()
	check(find_row(raw_rows,"005930").held and not find_row(raw_rows,"000660").held,"Only the matching observed account position is marked held")
	dashboard.watch_groups.select_group("holdings")
	dashboard._watch_preferences_changed()
	check(codes(dashboard.watch_groups.rows_for(raw_rows,dashboard.watchlist_codes))==["005930"],"Holdings view filters by the validated account identity")
	dashboard._table_security_selected("005930")
	var gateway: Node = dashboard.research_view.gateway
	gateway._kis_completed("005930",gateway.generation,observation("005930"))
	check(find_row(dashboard._table_rows(),"005930").status=="일봉 조회됨" and not find_row(dashboard._table_rows(),"005930").has("price"),"Viewed row follows the existing selected-code quote state without a price column")
	var conflict_group: String = dashboard.watch_groups.create_group("식별자 검증")
	dashboard._watch_preferences_changed()
	# Restored watched names are authoritative when a later account name differs.
	dashboard.security_names["005930"] = "삼성전자"
	dashboard.simulator.set_account(account_snapshot("005930","다른 회사","b"))
	await frames()
	var conflict_row: Dictionary = find_row(dashboard._table_rows(),"005930")
	check(conflict_row.account_present and conflict_row.identity_conflict and not conflict_row.held and conflict_row.status=="식별자 확인","Account identity conflict is visible without claiming a validated holding")
	dashboard.watch_groups.select_group("holdings")
	dashboard._watch_preferences_changed()
	check("005930" in codes(dashboard.watch_groups.rows_for(dashboard._table_rows(),dashboard.watchlist_codes)),"Holdings view retains the unresolved account row for inspection")
	var conflict_selected: bool = select_table_code(panel,"005930")
	await frames(2)
	check(conflict_selected and panel.table.get_selected().get_text(4)=="확인 필요","Tree marks an unresolved holding as confirmation needed")
	for index: int in panel.target_picker.item_count:
		if str(panel.target_picker.get_item_metadata(index))==conflict_group:
			panel.target_picker.select(index)
			panel.target_picker.item_selected.emit(index)
			break
	check(panel.add_button.disabled,"Group add is disabled for an unresolved account identity")
	dashboard._group_membership_requested(conflict_group,"005930",true)
	check(not "005930" in dashboard.watch_groups.get_group(conflict_group).codes,"Parent refuses direct group addition for unresolved identity")
	dashboard.watch_groups.delete_group(conflict_group)
	dashboard.simulator.set_account(account_snapshot("005930","삼성전자","c"))
	await frames()
	dashboard.watch_groups.select_group("all")
	dashboard._watch_preferences_changed()
	var selected_in_tree: bool = await mouse_select_table_code(panel,"069500")
	check(selected_in_tree and panel.selected_code=="069500" and dashboard.securities[dashboard.selected].code=="069500","Tree row click selects the same security in market workspace")
	var target_index: int = -1
	for index: int in panel.target_picker.item_count:
		if str(panel.target_picker.get_item_metadata(index))==growth:
			target_index = index
			break
	check(target_index>=0,"Membership target picker exposes the remaining group")
	if target_index>=0:
		panel.target_picker.select(target_index)
		panel.target_picker.item_selected.emit(target_index)
		panel.add_button.pressed.emit()
		check("069500" in dashboard.watch_groups.get_group(growth).codes and "069500" in dashboard.watchlist_codes,"Panel group add keeps global watch membership")
		panel.remove_button.pressed.emit()
		check(not "069500" in dashboard.watch_groups.get_group(growth).codes and "069500" in dashboard.watchlist_codes,"Panel group remove keeps global watch membership")
	for column: String in ["name","code","market","kind","held","status"]:
		dashboard.watch_groups.set_sort(column,true)
		var ascending: Array = dashboard.watch_groups.rows_for(dashboard._table_rows(),dashboard.watchlist_codes)
		dashboard.watch_groups.set_sort(column,false)
		var descending: Array = dashboard.watch_groups.rows_for(dashboard._table_rows(),dashboard.watchlist_codes)
		check(ascending.size()==descending.size() and dashboard.watch_groups.sort_column==column and not dashboard.watch_groups.sort_ascending,"Both sort directions work for "+column)
	for index: int in 6:
		panel.table.column_title_clicked.emit(index,MOUSE_BUTTON_LEFT)
		var first_direction: bool = dashboard.watch_groups.sort_ascending
		panel.table.column_title_clicked.emit(index,MOUSE_BUTTON_LEFT)
		check(dashboard.watch_groups.sort_column==["name","code","market","kind","held","status"][index] and dashboard.watch_groups.sort_ascending!=first_direction and panel.table.get_column_title(index).contains("↓" if first_direction else "↑"),"Tree header toggles both directions for column "+str(index))
	panel.table.column_title_clicked.emit(1,MOUSE_BUTTON_LEFT)
	check(dashboard.watch_groups.sort_column=="code" and dashboard.watch_groups.sort_ascending and table_first_code(panel)=="000660","Tree displays ascending code order after header click")
	panel.table.column_title_clicked.emit(1,MOUSE_BUTTON_LEFT)
	check(not dashboard.watch_groups.sort_ascending and table_first_code(panel)=="069500" and panel.selected_code=="069500" and str(panel.table.get_selected().get_metadata(0))=="069500","Descending Tree sort retains selected code")
	dashboard.watch_groups.set_sort("code",false)
	dashboard._watch_preferences_changed()
	dashboard._table_security_selected("069500")
	check(dashboard.securities[dashboard.selected].code=="069500" and dashboard.research_view.current_code=="069500" and dashboard.research_view.advisor.context.code=="069500","Sorted table selection keeps one code across market, research and advisor")
	dashboard._table_open_research("005930")
	await frames()
	check(dashboard.workspace=="research" and dashboard.securities[dashboard.selected].code=="005930" and dashboard.research_view.advisor.context.code=="005930","Research action opens the same security without AI request")
	dashboard._select_workspace("market")
	dashboard._select_stock(dashboard._security_index("005930"))
	dashboard._toggle_favorite()
	check(not "005930" in dashboard.watchlist_codes and not "005930" in dashboard.watch_groups.get_group(growth).codes and dashboard.notes_by_code.get("005930")=="그룹에서 해제해도 남을 노트","Global unwatch clears memberships but preserves the note")
	dashboard.flush_profile()
	check(Store.new(directory.path_join("profile.json")).load_profile().notes.get("005930")=="그룹에서 해제해도 남을 노트","Group changes persist without losing notes")
	dashboard._catalog_security_chosen(item("123456","검증전자","KOSDAQ"),false)
	check(dashboard.catalog_preview_code=="123456" and dashboard._security_index("123456")>=0,"Unwatched catalogue A opens as one preview")
	dashboard._catalog_security_chosen(item("123456","검증전자","KOSDAQ"),false)
	check(dashboard.catalog_preview_code=="123456","Reselecting A retains its preview marker")
	dashboard._catalog_security_chosen(item("123457","검증화학","KOSDAQ","우선주"),false)
	check(dashboard._security_index("123456")<0 and dashboard._security_index("123457")>=0 and dashboard.catalog_preview_code=="123457","Viewing B removes only old unwatched preview A")
	dashboard.watch_table.close()
	dashboard.queue_free()
	await frames()
	var overlay: CanvasLayer = load("res://scripts/dashboard_overlay.gd").new()
	root.add_child(overlay)
	overlay.open_dashboard()
	await frames(2)
	if is_instance_valid(overlay._tween):
		overlay._tween.kill()
	overlay._finish_open()
	overlay.dashboard._open_watch_table()
	var overlay_panel: Control = overlay.dashboard.watch_table
	overlay_panel.group_name_edit.text = "키보드 확인"
	overlay_panel.create_button.pressed.emit()
	overlay_panel.delete_button.pressed.emit()
	check(overlay_panel.confirm_bar.visible and overlay_panel.visible and overlay.is_open(),"Group delete confirmation opens inside the dashboard overlay")
	escape_key()
	await frames(2)
	check(not overlay_panel.confirm_bar.visible and overlay_panel.visible and overlay.is_open(),"First Escape cancels group deletion only")
	escape_key()
	await frames(2)
	check(not overlay_panel.visible and overlay.is_open(),"Second Escape closes the table only")
	escape_key()
	await frames(2)
	check(overlay.phase=="closing" or not overlay.is_open(),"Third Escape closes the dashboard")
	overlay.queue_free()
	await frames()
	print("WATCHLIST_GROUPS_UI_TEST: %s (%d checks; isolated profile/catalogue)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

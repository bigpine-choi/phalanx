extends SceneTree
## Bounded layout and code/scroll preservation under a large local table.
const Groups = preload("res://scripts/watchlist_groups.gd")
const TablePanel = preload("res://scripts/watchlist_table_panel.gd")

var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func frames(count := 4) -> void:
	for index: int in count:
		await process_frame

func row(code: String, status := "—") -> Dictionary:
	return {"code":code,"name":"검증 종목 "+code,"market":"KOSPI","kind":"보통주",
		"held":false,"status":status,"status_reason":""}

func within(inner: Rect2, outer: Rect2) -> bool:
	return inner.position.x >= outer.position.x - 1 and inner.position.y >= outer.position.y - 1 and inner.end.x <= outer.end.x + 1 and inner.end.y <= outer.end.y + 1

func run() -> void:
	root.size = Vector2i(1236,650)
	var model := Groups.new()
	var group_ids: Array = []
	for index: int in 32:
		var name := "%02d" % index + "가".repeat(38)
		var id: String = model.create_group(name)
		check(id.length()==32,"Group ID at "+str(index))
		group_ids.append(id)
		check(model.add_code(id,"300000"),"Group membership at "+str(index))
	var panel: Control = TablePanel.new()
	root.add_child(panel)
	await frames()
	panel.set_model(model)
	var rows: Array = []
	var watchlist: Array = []
	for index: int in 100:
		var code := "%06d" % (300000+index)
		rows.append(row(code))
		watchlist.append(code)
	panel.set_rows(rows,watchlist,"300000")
	panel.open()
	await frames()
	check(within(panel.card.get_global_rect(),root.get_visible_rect()),"Card fits 1236×650 embedded parent")
	for control: Control in [panel.scope_picker,panel.group_name_edit,panel.create_button,panel.rename_button,panel.delete_button,panel.filter_edit,panel.table,panel.selected_label,panel.target_picker,panel.add_button,panel.remove_button,panel.chart_button,panel.research_button]:
		check(within(control.get_global_rect(),panel.card.get_global_rect()),"Embedded card contains "+control.name)
	check(panel.scope_picker.size.x <= 230 and panel.target_picker.size.x <= 250,"Long group names do not expand selectors")
	check(panel.selected_label.text.contains("외 30개") and panel.selected_label.tooltip_text.contains("포함 그룹:"),"Many memberships have bounded label and full tooltip")
	for size: Vector2i in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = size
		await frames()
		check(within(panel.card.get_global_rect(),root.get_visible_rect()),"Card fits standalone "+str(size))
	root.size = Vector2i(1236,650)
	await frames()
	model.select_group(group_ids[0])
	await frames()
	panel._ask_delete_group()
	await frames()
	check(panel.confirm_bar.visible and within(panel.confirm_bar.get_global_rect(),panel.card.get_global_rect()),"Long-name inline deletion confirmation fits card")
	check(panel.handle_escape() and not panel.confirm_bar.visible and panel.visible,"First Esc dismisses inline confirmation")
	model.select_group("all")
	await frames()
	var conflict_rows: Array = rows.duplicate(true)
	conflict_rows[99].account_present = true
	conflict_rows[99].identity_conflict = true
	conflict_rows[99].status = "식별자 확인"
	panel.set_rows(conflict_rows,watchlist,"300099")
	check(panel.add_button.disabled,"Identity conflict blocks group addition")
	model.select_group("holdings")
	await frames()
	var conflict_item: TreeItem = panel.table.get_root().get_first_child()
	check(conflict_item != null and conflict_item.get_metadata(0)=="300099" and conflict_item.get_text(4)=="확인 필요","Holdings view shows unverified identity without claiming a holding")
	model.select_group("all")
	panel.set_rows(rows,watchlist,"300000")
	await frames()
	var item: TreeItem = panel.table.get_root().get_first_child()
	for index: int in 65:
		item = item.get_next()
	panel.table.scroll_to_item(item,true)
	await frames()
	var before_scroll: float = panel.table.get_scroll().y
	check(before_scroll > 0,"Large table scrolls before asynchronous refresh")
	var updated: Array = rows.duplicate(true)
	updated[0].status = "일봉 조회됨"
	panel.set_rows(updated,watchlist,"300000")
	await frames()
	var after_scroll: float = panel.table.get_scroll().y
	check(after_scroll > 0 and absf(after_scroll-before_scroll) <= 35.0,"Asynchronous row rebuild keeps viewport near its previous position")
	panel._column_clicked(1,MOUSE_BUTTON_LEFT)
	await frames()
	check(panel.selected_code == "300000" and panel.table.get_selected()!=null and panel.table.get_selected().get_metadata(0)=="300000","Sort retains selected security code")
	panel.filter_edit.text = "300099"
	panel._filter_changed("300099")
	check(panel.selected_code == "300000" and panel.chart_button.disabled,"Hidden selection remains remembered but cannot act")
	panel.filter_edit.text = ""
	panel._filter_changed("")
	check(panel.table.get_selected()!=null and panel.table.get_selected().get_metadata(0)=="300000","Clearing filter reselects code")
	panel.queue_free()
	await frames()
	print("WATCHLIST_TABLE_PANEL_STRESS_TEST: %s (%d checks)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

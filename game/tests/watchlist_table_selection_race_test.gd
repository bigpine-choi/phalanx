extends SceneTree
## A quote refresh must not erase a table click before its deferred HQ notification.

const Groups = preload("res://scripts/watchlist_groups.gd")
const TablePanel = preload("res://scripts/watchlist_table_panel.gd")

var failures := 0
var signals: Array[String] = []


func _initialize() -> void:
	call_deferred("run")


func check(ok: bool, label: String) -> void:
	if not ok:
		failures += 1
		push_error(label)


func row(code: String) -> Dictionary:
	return {"code":code,"name":"종목 " + code,"market":"KOSPI","kind":"보통주",
		"held":false,"status":"조회 대기","status_reason":""}


func select_code(panel: Control, code: String) -> void:
	var item: TreeItem = panel.table.get_root().get_first_child()
	while item != null and str(item.get_metadata(0)) != code:
		item = item.get_next()
	check(item != null, "Selection row exists: " + code)
	if item != null:
		panel.table.set_selected(item, 0)
		panel._tree_selected()


func settle() -> void:
	await process_frame
	await process_frame


func run() -> void:
	root.size = Vector2i(1280, 720)
	var panel: Control = TablePanel.new()
	root.add_child(panel)
	await settle()
	panel.set_model(Groups.new())
	var rows := [row("300001"), row("300002"), row("300003")]
	var watchlist := ["300001", "300002", "300003"]
	panel.set_rows(rows, watchlist, "300001")
	panel.open()
	await settle()
	panel.security_selected.connect(func(code: String) -> void: signals.append(code))

	# The market quote for A can finish between the Tree event for B and its
	# deferred security_selected(B) signal.
	select_code(panel, "300002")
	panel.set_rows(rows, watchlist, "300001")
	await settle()
	check(signals == ["300002"], "A quote refresh preserves pending B selection")
	check(panel.selected_code == "300002", "B remains the selected code after refresh")

	signals.clear()
	panel.set_rows(rows, watchlist, "300001")
	select_code(panel, "300002")
	panel.set_rows(rows, watchlist, "300001")
	select_code(panel, "300003")
	await settle()
	check(signals == ["300003"], "Latest rapid click wins after a refresh")

	signals.clear()
	panel.set_rows(rows, watchlist, "300001")
	select_code(panel, "300002")
	panel.filter_edit.text = "300003"
	panel._filter_changed("300003")
	await settle()
	check(signals == ["300002"], "Pending click survives a filter rebuild")
	check(panel.selected_code == "300002" and panel.chart_button.disabled, "Hidden selection remains recorded without an enabled chart action")
	panel.filter_edit.text = ""
	panel._filter_changed("")

	signals.clear()
	panel.set_rows(rows, watchlist, "300001")
	select_code(panel, "300002")
	panel.set_rows([row("300001"), row("300003")], ["300001", "300003"], "300001")
	await settle()
	check(signals.is_empty(), "Removed pending row does not emit a selection")
	check(panel.selected_code == "300001", "Removed pending row restores current HQ selection")

	signals.clear()
	panel.set_rows(rows, watchlist, "300001")
	select_code(panel, "300002")
	panel.close()
	await settle()
	check(signals.is_empty(), "Closing the panel cancels pending selection")

	panel.queue_free()
	await settle()
	print("WATCHLIST_TABLE_SELECTION_RACE_TEST: %s" % ("PASS" if failures == 0 else "FAIL"))
	quit(0 if failures == 0 else 1)

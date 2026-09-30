extends SceneTree
## Headless regression for deferred Korean search; native OS IME needs a manual check.
const Catalog = preload("res://scripts/market_catalog.gd")
const CatalogPanel = preload("res://scripts/market_catalog_panel.gd")
var chosen_codes: Array = []

func _initialize() -> void:
	OS.set_environment("PHALANX_CATALOG_OFFLINE", "1")
	OS.set_environment("PHALANX_CATALOG_CACHE", OS.get_environment("TEMP").path_join("catalog-input-probe-%d-%d.json" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("run")

func run() -> void:
	root.size = Vector2i(1280,720)
	var catalogue := Catalog.new()
	root.add_child(catalogue)
	catalogue.accept_snapshot({"state":"ready","collected_at":"2026-09-30T00:00:00+00:00","source":"test","collisions":[],"items":[
		{"code":"005930","name":"삼성전자","market":"KOSPI","kind":"보통주","source":"test","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""},
		{"code":"035420","name":"네이버","market":"KOSPI","kind":"보통주","source":"test","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}
	]})
	var panel := CatalogPanel.new()
	root.add_child(panel)
	panel.set_catalog(catalogue)
	panel.security_chosen.connect(func(item: Dictionary, _add: bool) -> void: chosen_codes.append(item.code))
	panel.open()
	await process_frame
	var original_row: Node = panel.results.get_child(0)
	for letter: String in ["삼", "성", "전", "자"]:
		panel.query_edit.insert_text_at_caret(letter)
		# Programmatic insertion does not emit the GUI's text_changed signal.
		panel.query_edit.text_changed.emit(panel.query_edit.text)
		panel._choose(true)
		if not panel.add_button.disabled or not panel.view_button.disabled or not chosen_codes.is_empty():
			push_error("Pending input can choose a stale search result")
			quit(1)
			return
		await process_frame
		if panel.results.get_child(0) != original_row:
			push_error("Search rebuilt controls during input")
			quit(1)
			return
	if panel.query_edit.text != "삼성전자" or root.gui_get_focus_owner() != panel.query_edit:
		push_error("Korean input text or focus was lost")
		quit(1)
		return
	await create_timer(0.4).timeout
	if panel.results.get_child(0) == original_row or panel.selected_item.get("code") != "005930" or not panel.count_label.text.contains("1건"):
		push_error("Delayed Korean search did not update")
		quit(1)
		return
	if panel.add_button.disabled or panel.view_button.disabled:
		push_error("Completed search did not restore selection actions")
		quit(1)
		return
	panel.query_edit.text = "035420"
	panel.query_edit.text_changed.emit("035420")
	panel._submit_query("035420")
	if chosen_codes != ["035420"] or panel.selected_item.get("code") != "035420":
		push_error("Enter must search the latest query before choosing a result")
		quit(1)
		return
	print("MARKET_CATALOG_KOREAN_INPUT_TEST: PASS")
	quit()


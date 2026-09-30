extends SceneTree
## Explicit opt-in public quote probe. Account, KIS, discovery and AI stay offline.
var directory := ""

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()!=1 or not args[0].is_absolute_path():
		push_error("Pass one isolated absolute directory to explicitly run the NH public quote probe")
		quit(2)
		return
	directory = args[0]
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_NH_OFFLINE","0")
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("profile.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	OS.set_environment("PHALANX_NH_QUOTE_CACHE",directory.path_join("nh"))
	OS.set_environment("PHALANX_CATALOG_CACHE",directory.path_join("catalog.json"))
	call_deferred("run")

func run() -> void:
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(view)
	await process_frame
	view._open_watch_table()
	view.watch_table.filter_edit.text = "005930"
	view.watch_table._filter_changed("005930")
	view.watch_table.quotes_refresh_button.pressed.emit()
	var quotes: Node = view.research_view.nh_quotes
	var deadline := Time.get_ticks_msec()+35000
	while quotes.busy and Time.get_ticks_msec()<deadline:
		await create_timer(0.1).timeout
	var quote: Dictionary = quotes.quote_for("005930")
	var fields: Dictionary = quotes.row_fields("005930")
	var row: Dictionary = view.watch_table.visible_rows.get("005930",{})
	var matched := false
	# Use the same formatter as the UI for all price magnitudes.
	if not quote.is_empty():
		matched = row.get("price")==quote.price and row.get("quote_time")==fields.get("quote_time") and view.research_view.nh_status.text.contains(preload("res://scripts/market_data.gd").money(quote.price))
	print("NH_LIVE_PROBE: ",JSON.stringify({"quote":quote,"row":fields,"table_research_match":matched,"busy":quotes.busy,"summary":quotes.summary}))
	view.queue_free()
	await process_frame
	quit(0 if matched else 1)

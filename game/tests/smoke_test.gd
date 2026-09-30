extends SceneTree

const Data = preload("res://scripts/market_data.gd")
var failures := 0

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	if OS.get_environment("PHALANX_WORKSPACE_PATH").is_empty():
		OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-smoke_test-%s-%s.json" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	var main = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(main)
	await process_frame
	main._select_stock(1)
	check(main.title_label.text == "SK하이닉스", "Stock selection must refresh heading")
	main._set_period(22)
	check(main.chart.days == 22 and main.chart.candles.is_empty(), "One-month period")
	main._set_period(252)
	check(main.chart.days == 252 and main.chart.candles.is_empty(), "One-year period")
	main._filter_stocks("005930")
	check(main.stock_buttons[0].visible and not main.stock_buttons[1].visible, "Code search")
	main._filter_stocks("no-match")
	check(main.empty_label.visible, "Empty search state")
	main._filter_stocks("")
	for window_size in [Vector2i(1440, 960), Vector2i(1024, 768), Vector2i(900, 680)]:
		root.size = window_size
		await process_frame
		await process_frame
		check(main.get_combined_minimum_size().x <= window_size.x, "Root must fit viewport")
		check(main.portfolio_button.is_visible_in_tree(), "Allocation editing must remain reachable in compact and wide workspaces")
		check(main.body.get_global_rect().end.x <= window_size.x + 1, "Body must not overflow horizontally")
	print("PHALANX_SMOKE_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

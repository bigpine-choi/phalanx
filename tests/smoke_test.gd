extends SceneTree

const Data = preload("res://scripts/demo_data.gd")
var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	check(is_equal_approx(Data.total_assets(), 100000000.0), "Account NAV must reconcile to 100 million KRW")
	var targets: Array = []
	for stock in Data.STOCKS:
		targets.append(stock.target)
	var result := Data.plan(targets)
	check(result.valid, "Default plan must be valid")
	var reconciled: float = result.cash
	for i in range(result.rows.size()):
		var row: Dictionary = result.rows[i]
		reconciled += row.result_quantity * Data.STOCKS[i].price
		check(row.result_quantity >= 0, "No short positions")
	check(is_equal_approx(reconciled, Data.total_assets()), "Trades must conserve NAV")
	check(not Data.plan([100, 100, 0, 0, 0]).valid, "Reject overweight allocation")
	var cash_only := Data.plan([0, 0, 0, 0, 0])
	check(cash_only.valid and is_equal_approx(cash_only.cash, Data.total_assets()), "Zero targets must liquidate demo positions")
	for i in range(Data.STOCKS.size()):
		var history := Data.history(i)
		check(is_equal_approx(history[-1].close, Data.STOCKS[i].price), "Chart quote must match stock quote")
		for candle in history:
			check(candle.low <= minf(candle.open, candle.close) and candle.high >= maxf(candle.open, candle.close), "Valid OHLC bounds")
	var main = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(main)
	await process_frame
	main._select_stock(1)
	check(main.title_label.text == "SK하이닉스", "Stock selection must refresh heading")
	main._target_changed(20.0)
	main._select_stock(2)
	main._select_stock(1)
	check(main.target_input.value == 20.0, "Targets must survive selection changes")
	main._set_period(22)
	check(main.chart.candles.size() == 22, "One-month period")
	main._set_period(252)
	check(main.chart.candles.size() == 252, "One-year period")
	main._filter_stocks("005930")
	check(main.stock_buttons[0].visible and not main.stock_buttons[1].visible, "Code search")
	main._filter_stocks("no-match")
	check(main.empty_label.visible, "Empty search state")
	main._filter_stocks("")
	main.targets = [100, 100, 0, 0, 0]
	main._update_plan()
	check(main.preview_button.disabled, "Disable preview for invalid allocation")
	main._reset_targets()
	check(not main.preview_button.disabled, "Reset allocation")
	for window_size in [Vector2i(1440, 960), Vector2i(1024, 768), Vector2i(900, 680)]:
		root.size = window_size
		await process_frame
		await process_frame
		check(main.get_combined_minimum_size().x <= window_size.x, "Root must fit viewport")
		check(main.account.get_parent() == (main.center if window_size.x < 1180 else main.body), "Responsive account placement")
		check(main.body.get_global_rect().end.x <= window_size.x + 1, "Body must not overflow horizontally")
	print("PHALANX_SMOKE_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

extends SceneTree
var failures := 0
var checks := 0
var dashboard: Control

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	if OS.get_environment("PHALANX_WORKSPACE_PATH").is_empty():
		OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-terminal_workspace_test-%s-%s.json" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

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

func run() -> void:
	root.size = Vector2i(1440,960)
	dashboard = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	await frames()
	await click(dashboard.stock_buttons[1])
	check(dashboard.selected==1,"Clicking a custom watchlist row must select its stock through its child labels")
	await click(dashboard.period_buttons[0])
	await click(dashboard.chart_mode_buttons[1])
	check(dashboard.chart.days==22 and dashboard.chart.display_mode=="line","Period and chart type buttons must update actual chart data and rendering mode")
	dashboard.target_input.value = 20.0
	await click(dashboard.workspace_buttons[1])
	await frames()
	check(dashboard.workspace=="portfolio" and dashboard.live_portfolio_page.visible,"Portfolio tab opens real-account workspace")
	dashboard.simulator.sample_requested.emit()
	await frames()
	check(dashboard.workspace=="sample" and dashboard.account.is_visible_in_tree(),"Sample action exposes the original allocation planner")
	check(dashboard.portfolio_rows[1].target.text=="20.0%","Portfolio table must show the current edited target")
	await click(dashboard.portfolio_rows[2].button)
	check(dashboard.selected==2 and dashboard.target_input.value==22.0,"A portfolio row must update shared selection and target editing")
	await click(dashboard.workspace_buttons[2])
	await frames()
	check(dashboard.research_title.text.contains("현대차"),"Research must follow the same selected stock")
	dashboard.note_editor.text = "TEST: 수요와 환율을 확인"
	dashboard._note_changed()
	await click(dashboard.research_buttons[0])
	check(dashboard.note_editor.text.is_empty(),"Another stock must not inherit the previous stock's note")
	await click(dashboard.research_buttons[2])
	check(dashboard.note_editor.text=="TEST: 수요와 환율을 확인","Returning to a stock must restore its temporary note")
	await click(dashboard.workspace_buttons[0])
	check(dashboard.selected==2 and dashboard.chart.days==22 and dashboard.chart.display_mode=="line","Workspace changes must preserve selection, period and chart mode")
	dashboard.search.text = "005930"
	dashboard._filter_stocks(dashboard.search.text)
	dashboard._submit_search(dashboard.search.text)
	check(dashboard.selected==0 and dashboard.stock_buttons[0].visible and not dashboard.stock_buttons[1].visible,"Search and Enter must act on the filtered result")
	dashboard.search.text = ""
	dashboard._filter_stocks("")
	dashboard._select_workspace("research")
	var key := InputEventKey.new()
	key.keycode = KEY_K
	key.ctrl_pressed = true
	key.pressed = true
	Input.parse_input_event(key)
	Input.flush_buffered_events()
	await frames()
	check(dashboard.workspace=="market" and dashboard.search.has_focus(),"Ctrl+K must open market search from a different workspace")
	for resolution: Vector2i in [Vector2i(1440,960),Vector2i(1280,720),Vector2i(1024,768),Vector2i(900,680)]:
		root.size = resolution
		await frames(8)
		dashboard._select_workspace("market")
		await frames()
		var boundary := dashboard.get_global_rect()
		check(dashboard.body.get_global_rect().end.x<=boundary.end.x+1,"Market columns must stay within viewport "+str(resolution))
		check(dashboard.chart.get_global_rect().end.y<=boundary.end.y-18,"Chart and volume must remain above the status bar "+str(resolution))
		check(dashboard.period_buttons[0].is_visible_in_tree(),"Chart controls must remain visible at "+str(resolution))
		if not dashboard.compact:
			check(dashboard.account.get_global_rect().encloses(dashboard.preview_button.get_global_rect()),"Plan review action must stay pinned inside the market planner "+str(resolution))
		if dashboard.compact:
			await click(dashboard.compact_plan_button)
		else:
			await click(dashboard.workspace_buttons[1])
			dashboard.simulator.sample_requested.emit()
		await frames()
		check(dashboard.workspace=="sample" and dashboard.account.is_visible_in_tree(),"Target editing must be reachable at "+str(resolution))
		check(dashboard.portfolio_split.get_global_rect().end.x<=boundary.end.x+1,"Portfolio table must fit without horizontal scrolling "+str(resolution))
		dashboard.portfolio_page.ensure_control_visible(dashboard.account)
		dashboard.account_scroll.ensure_control_visible(dashboard.target_input)
		await frames()
		dashboard._show_plan()
		check(dashboard.dialog.visible,"Plan review must still open at "+str(resolution))
		dashboard.dialog.hide()
		dashboard._select_workspace("research")
		await frames()
		check(dashboard.research_page.get_h_scroll_bar().max_value<=dashboard.research_page.size.x+1,"Research cards must not require horizontal scrolling "+str(resolution))
	dashboard.hide()
	dashboard._unhandled_key_input(key)
	check(dashboard.workspace=="research","A hidden workspace must not intercept camp keyboard shortcuts")
	dashboard.show()
	dashboard._show_plan()
	dashboard._unhandled_key_input(key)
	check(dashboard.workspace=="research","A plan dialog must block workspace shortcuts beneath it")
	dashboard.dialog.hide()
	dashboard.queue_free()
	await frames()
	print("PHALANX_TERMINAL_WORKSPACE_TEST: %s (%d checks)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

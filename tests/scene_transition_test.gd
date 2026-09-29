extends SceneTree
## Behavioral checks use real animation time and real viewport input dispatch.
var app: Control
var checks := 0
var failures := 0
var opened_count := 0
var closed_count := 0

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE", "1")
	OS.set_environment("PHALANX_RESEARCH_CACHE", OS.get_environment("TEMP").path_join("phalanx-transition-%d" % OS.get_process_id()))
	OS.set_environment("PHALANX_WORKSPACE_PATH", OS.get_environment("TEMP").path_join("phalanx-transition-%d.json" % OS.get_process_id()))
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func settle() -> void:
	var deadline := Time.get_ticks_msec() + 3000
	while app.is_transitioning() and Time.get_ticks_msec() < deadline:
		await process_frame
	check(not app.is_transitioning(), "A transition must always release its input gate")
	await process_frame

func escape() -> void:
	for pressed: bool in [true,false]:
		var event := InputEventKey.new()
		event.keycode = KEY_ESCAPE
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()

func click(control: Control) -> void:
	for pressed: bool in [true,false]:
		var event := InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		event.position = control.get_global_transform_with_canvas() * (control.size * 0.5)
		Input.parse_input_event(event)
		Input.flush_buffered_events()

func run() -> void:
	root.size = Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	await process_frame
	app.camp.restore_position(app.camp.entrance_position)
	var saved_position: Vector2 = app.camp.get_actor_position()
	app.enter_headquarters()
	check(app.mode == "camp" and app.scene_transition.busy, "Departure must animate before the location handoff")
	check(app.camp.visible and not app.camp.active and not app.hud.visible, "Departure must retain the picture while disabling world input")
	app.enter_headquarters()
	escape()
	await create_timer(0.18).timeout
	check(app.mode == "camp" and app._view_zoom > 1.0, "Camera must push toward the doorway before the hidden handoff")
	root.size = Vector2i(1280,720)
	await settle()
	check(app.mode == "headquarters" and app.headquarters.active, "Duplicate inputs and a resize must still arrive in headquarters once")
	check(is_equal_approx(app._view_zoom,1.0) and app.hud.visible, "Arrival must restore the authored transform and HUD")
	var overlay: CanvasLayer = app.dashboard_overlay
	overlay.opened.connect(func() -> void: opened_count += 1)
	overlay.closed.connect(func() -> void: closed_count += 1)
	app._open_dashboard()
	var dashboard: Control = overlay.dashboard
	check(overlay.phase == "opening" and overlay.presentation.scale.y < 0.1, "Map must start as a folded document")
	overlay.open_dashboard()
	await create_timer(0.18).timeout
	check(overlay.presentation.scale.y > 0.025 and overlay.presentation.scale.y < 1.0, "Unfold must produce visible intermediate frames")
	click(dashboard.stock_buttons[1])
	escape()
	await settle()
	check(dashboard.selected == 0 and overlay.phase == "open", "Animation input gate must block click-through and repeated Escape")
	check(opened_count == 1 and app.mode == "headquarters", "Repeated map open must keep one modal and one opening signal")
	check(overlay.presentation.scale.is_equal_approx(Vector2.ONE) and overlay.presentation.position.is_zero_approx(), "Unfold must finish at the full responsive layout")
	dashboard._select_stock(1)
	dashboard.target_input.value = 20.0
	dashboard._set_period(22)
	overlay.close_dashboard()
	check(overlay.is_open() and not app.headquarters.active, "Closing must retain modality until the fold completes")
	app.return_to_camp()
	escape()
	await settle()
	check(app.mode == "headquarters" and app.headquarters.active and closed_count == 1, "Closing must restore exactly one headquarters layer")
	app._open_dashboard()
	await create_timer(0.12).timeout
	overlay.close_dashboard()
	await settle()
	check(not overlay.is_open() and closed_count == 2, "Programmatic close during unfold must cancel cleanly without duplicate callbacks")
	app._open_dashboard()
	await create_timer(0.12).timeout
	root.size = Vector2i(1100,740)
	await settle()
	check(overlay.phase == "open" and overlay.presentation.position.is_zero_approx(), "Resize during unfold must settle a usable layout")
	check(overlay.dashboard == dashboard and dashboard.selected == 1 and dashboard.targets[1] == 20.0 and dashboard.chart.days == 22, "Reopening and resizing must preserve shared analysis state")
	root.min_size = Vector2i(900,680)
	root.size = Vector2i(900,680)
	for i in 5:
		await process_frame
	check(dashboard.watch_panel.get_global_rect().end.y < dashboard.status_label.get_global_rect().position.y, "Embedded watchlist must stay above the footer at the smallest review size")
	check(dashboard.center.get_global_rect().end.y < dashboard.status_label.get_global_rect().position.y, "Embedded chart controls must not overlap the footer")
	root.size = Vector2i(2160,1440)
	await process_frame
	await process_frame
	check(is_equal_approx(overlay.scale.x,1.5) and overlay.blocker.size.is_equal_approx(Vector2(1440,960)), "Large windows must retain readable logical UI dimensions")
	click(dashboard.stock_buttons[2])
	check(dashboard.selected == 2, "Scaled interface controls must receive correctly transformed clicks")
	overlay.close_dashboard()
	await create_timer(0.1).timeout
	root.size = Vector2i(1280,720)
	await settle()
	check(not overlay.is_open() and app.hud.visible and closed_count == 3, "Resize during folding must restore the HUD once")
	app.return_to_camp()
	app.return_to_camp()
	escape()
	await settle()
	check(app.mode == "camp" and app.camp.active and not app.headquarters.visible, "Return transition must restore only the camp")
	check(app.camp.get_actor_position().is_equal_approx(saved_position) and app.enter_button.visible, "Return must restore the actor and an immediately usable entrance button")
	check(is_equal_approx(app._view_zoom,1.0), "Repeated trips must not accumulate camera scale")
	app.queue_free()
	await process_frame
	print("PHALANX_SCENE_TRANSITION_TEST: %s (%d checks)" % ["PASS" if failures == 0 else "FAIL", checks])
	quit(0 if failures == 0 else 1)

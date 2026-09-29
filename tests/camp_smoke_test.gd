extends SceneTree
const Fixture = preload("res://tests/operation_fixture.gd")
## HISTORICAL: archived first-person camp only; not validation of the current quarter-view flow.
## Current scene-flow regression: res://tests/quarter_flow_test.gd.

var failures: int = 0
var opened_count: int = 0
var closed_count: int = 0
var activated_count: int = 0

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _settle() -> void:
	await process_frame
	await physics_frame
	await process_frame
	await process_frame

func _mouse_move(position: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.position = position
	event.global_position = position
	Input.parse_input_event(event)

func _mouse_click(position: Vector2) -> void:
	for pressed: bool in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = position
		event.global_position = position
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		event.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
		Input.parse_input_event(event)

func _key(keycode: Key) -> void:
	for pressed: bool in [true, false]:
		var event := InputEventKey.new()
		event.keycode = keycode
		event.physical_keycode = keycode
		event.pressed = pressed
		Input.parse_input_event(event)

func _escape() -> void:
	_key(KEY_ESCAPE)

func _inside(control: Control, bounds: Rect2) -> bool:
	var rectangle: Rect2 = control.get_global_rect()
	return rectangle.size.x > 0 and rectangle.size.y > 0 and bounds.has_point(rectangle.position) and bounds.has_point(rectangle.end - Vector2.ONE)

func _dashboard_count(node: Node) -> int:
	var count: int = 0
	var script: Script = node.get_script() as Script
	if script != null and script.resource_path == "res://scripts/headquarters.gd":
		count += 1
	for child: Node in node.get_children():
		count += _dashboard_count(child)
	return count

func _run() -> void:
	root.content_scale_factor = 1.0
	root.size = Vector2i(1440, 960)
	var main_path: String = str(ProjectSettings.get_setting("application/run/main_scene"))
	check(main_path == "res://scenes/command_camp.tscn", "The 3D camp must be the configured main scene")
	var packed: PackedScene = load(main_path) as PackedScene
	if packed == null:
		check(false, "Main scene must load")
		_finish()
		return
	var camp: Node = packed.instantiate()
	root.add_child(camp)
	current_scene = camp
	await _settle()
	check(camp is Node3D, "Main scene must be a 3D camp")
	var environment: Node = camp.get("environment") as Node
	var interactor: Variant = camp.get("table_interaction")
	var overlay: Variant = camp.get("dashboard_overlay")
	var player: Variant = camp.get("player")
	if environment == null or interactor == null or overlay == null or player == null:
		check(false, "Camp environment, player, interaction and overlay must be separate nodes")
		_finish()
		return
	var camera: Camera3D = player.get("camera") as Camera3D
	check(camera != null and camera.current, "Camp must have a current first-person camera")
	check(interactor is Area3D and interactor.get_child_count() > 0, "Operation table must have an interaction area")
	check(not overlay.is_open() and overlay.dashboard == null, "Dashboard must be lazy and initially closed")
	check(not interactor.interaction_enabled and not player.exploring, "Exploration and table input must wait for the initial click")
	check(camp.capture_prompt.visible and not camp.hover_hint.visible, "Paused camp must show only the capture instructions")
	if camera == null:
		_finish()
		return
	overlay.opened.connect(func() -> void: opened_count += 1)
	overlay.closed.connect(func() -> void: closed_count += 1)
	interactor.activated.connect(func() -> void: activated_count += 1)
	# A headless window cannot receive an OS focus event; simulate it explicitly.
	player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
	player.global_position = Vector3(0, 0.04, -2.2)
	camera.look_at(Vector3(0, 1.04, 0))
	var table_screen: Vector2 = Vector2(root.size) * 0.5
	_mouse_click(table_screen)
	await _settle()
	check(player.exploring and not overlay.is_open(), "Initial click must capture exploration without opening the table")
	check(interactor.hovered, "Looking at the nearby table must enable its hover state")
	check(not camp.capture_prompt.visible and camp.hover_hint.visible, "Nearby table must show only the E prompt while exploring")
	camera.look_at(camera.global_position + Vector3(0, 0, -1))
	await _settle()
	check(not interactor.hovered, "Looking away must clear table hover")
	check(not camp.capture_prompt.visible and not camp.hover_hint.visible, "Looking away while exploring must hide both contextual prompts")
	camera.look_at(Vector3(0, 1.04, 0))
	await _settle()
	_mouse_click(table_screen)
	await _settle()
	check(not overlay.is_open(), "Legacy left click must not activate the table while exploring")
	_key(KEY_E)
	await _settle()
	check(overlay.is_open() and overlay.dashboard != null, "E at the nearby centered table must open the dashboard")
	check(activated_count == 1 and opened_count == 1, "One E press must activate and open exactly once")
	if overlay.dashboard == null:
		_finish()
		return
	var dashboard: Control = overlay.dashboard as Control
	var dashboard_id: int = dashboard.get_instance_id()
	var close_connections: int = overlay.close_button.get_signal_connection_list("pressed").size()
	var table_connections: int = interactor.get_signal_connection_list("activated").size()
	check(not interactor.interaction_enabled and not interactor.hovered, "Opening the dashboard must disable and clear table hover")
	check(not player.exploring and player.modal_blocked, "Opening the dashboard must stop player movement and look")
	check(overlay.blocker.visible and overlay.blocker.mouse_filter == Control.MOUSE_FILTER_STOP, "Visible dashboard must have a full-screen input blocker")
	check(dashboard.get("embedded_in_camp") == true, "Embedded dashboard must leave camp window settings alone")
	var opens_before: int = opened_count
	_mouse_move(table_screen)
	_mouse_click(table_screen)
	await _settle()
	check(activated_count == 1 and opened_count == opens_before, "Dashboard clicks must not activate the 3D table behind it")
	var close_screen: Vector2 = overlay.close_button.get_global_rect().get_center()
	_mouse_move(close_screen)
	_mouse_click(close_screen)
	await _settle()
	check(not overlay.is_open() and closed_count == 1, "Close button must return to camp exactly once")
	check(interactor.interaction_enabled and player.exploring and not overlay.blocker.visible, "Closing must release the blocker and resume exploration")
	_key(KEY_E)
	await _settle()
	check(overlay.is_open(), "Table must remain usable with E after closing the dashboard")
	_escape()
	await _settle()
	check(not overlay.is_open() and closed_count == 2, "Escape must close the dashboard")
	_escape()
	await _settle()
	check(camp.capture_prompt.visible and not camp.hover_hint.visible, "Exploration Escape must restore only the capture prompt")
	_mouse_click(table_screen)
	await _settle()

	# Native popup event routing is simulated here; real window behavior needs GUI QA.
	overlay.open_dashboard()
	Fixture.install(dashboard)
	dashboard.call("_show_plan")
	await _settle()
	var preview: AcceptDialog = dashboard.get("dialog") as AcceptDialog
	check(preview.visible, "The existing plan preview must still open")
	preview.canceled.emit()
	check(overlay.is_open(), "Canceling the preview must leave the dashboard open")
	preview.hide()
	Fixture.install(dashboard)
	dashboard.call("_show_plan")
	await _settle()
	var native_escape := InputEventKey.new()
	native_escape.keycode = KEY_ESCAPE
	native_escape.pressed = true
	preview.window_input.emit(native_escape)
	await _settle()
	check(overlay.is_open() and not preview.visible and closed_count == 2, "First native popup Escape must close only the preview")
	# A duplicate delivery of the same press to the parent must not close another layer.
	Input.parse_input_event(native_escape)
	await _settle()
	check(overlay.is_open(), "One Escape press must not close both popup and dashboard")
	native_escape.pressed = false
	Input.parse_input_event(native_escape)
	_escape()
	await _settle()
	check(not overlay.is_open() and closed_count == 3 and player.exploring, "Next Escape must close the dashboard and resume exploration")
	overlay.open_dashboard()
	Fixture.install(dashboard)
	dashboard.call("_show_plan")
	await _settle()
	_escape()
	await _settle()
	check(overlay.is_open() and not preview.visible, "Main viewport Escape must also close only the popup")
	_escape()
	await _settle()
	check(not overlay.is_open(), "Second main viewport Escape must close the dashboard")

	# Reopening reuses the dashboard and preserves an in-session portfolio edit.
	Fixture.install(dashboard)
	for iteration: int in range(4):
		var old_opens: int = opened_count
		var old_closes: int = closed_count
		overlay.open_dashboard()
		overlay.open_dashboard()
		await _settle()
		check(overlay.dashboard.get_instance_id() == dashboard_id, "Repeated opening must reuse one dashboard instance")
		check(_dashboard_count(camp) == 1 and opened_count == old_opens + 1, "Opening twice must not duplicate UI or opened signals")
		check(dashboard.simulation_plan.rows[0].target == 20.0, "Closing and reopening must preserve the current demo allocation")
		overlay.close_dashboard()
		overlay.close_dashboard()
		check(closed_count == old_closes + 1, "Closing twice must emit closed only once")
	check(overlay.close_button.get_signal_connection_list("pressed").size() == close_connections, "Close button connections must not accumulate")
	check(interactor.get_signal_connection_list("activated").size() == table_connections, "Table connections must not accumulate")

	overlay.open_dashboard()
	var scroll: ScrollContainer = null
	# The retained dashboard creates its scroll container without a stable node name.
	for child: Node in dashboard.get_children():
		if child is ScrollContainer:
			scroll = child as ScrollContainer
			break
	check(scroll != null, "Embedded dashboard must retain its vertical scroll container")
	for window_size: Vector2i in [Vector2i(1280, 720), Vector2i(1440, 960)]:
		root.size = window_size
		await _settle()
		var viewport_bounds := Rect2(Vector2.ZERO, Vector2(window_size))
		check(_inside(overlay.close_button, viewport_bounds), "Close button must remain in bounds at %s" % window_size)
		check(_inside(overlay.dashboard_host, viewport_bounds), "Dashboard host must fit at %s" % window_size)
		check(overlay.blocker.get_global_rect().encloses(viewport_bounds), "Input blocker must cover the whole viewport at %s" % window_size)
		check(dashboard.get("body").get_global_rect().end.x <= window_size.x + 1, "Dashboard must not overflow horizontally at %s" % window_size)
		if scroll != null:
			var period_buttons: Array = dashboard.get("period_buttons")
			var required_controls: Array[Control] = [dashboard.find_child("StockSearch", true, false) as Control, period_buttons[0] as Control, dashboard.portfolio_button as Control]
			for control: Control in required_controls:
				check(control != null, "Main dashboard controls must exist")
				if control == null:
					continue
				scroll.ensure_control_visible(control)
				await _settle()
				check(_inside(control, scroll.get_global_rect()), "Dashboard control %s must be reachable by scrolling at %s" % [control.name, window_size])
				check(_inside(overlay.close_button, viewport_bounds), "Scrolling must not move the close button off screen")
	overlay.close_dashboard()
	camp.queue_free()
	await _settle()
	_finish()

func _finish() -> void:
	print("PHALANX_CAMP_SMOKE_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

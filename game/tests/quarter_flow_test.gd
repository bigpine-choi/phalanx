extends SceneTree
const Fixture = preload("res://tests/operation_fixture.gd")
## Current-design regression checks. All events are synthetic Godot viewport input.
## This does not claim operating-system or human keyboard/mouse verification.
## Optional GPU captures: --script res://tests/quarter_flow_test.gd -- ABSOLUTE_OUTPUT_DIR

var failures := 0
var checks := 0
var app: Control
var capture_directory := ""

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	if OS.get_environment("PHALANX_WORKSPACE_PATH").is_empty():
		OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-quarter_flow_test-%s-%s.json" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		push_error(message)

func frames(count: int = 4) -> void:
	for i in count:
		await process_frame
		await physics_frame
	var deadline := Time.get_ticks_msec() + 3000
	while is_instance_valid(app) and app.is_transitioning() and Time.get_ticks_msec() < deadline:
		await process_frame
		await physics_frame
	if is_instance_valid(app):
		check(not app.is_transitioning(), "Scene animation must finish within three seconds")

func mouse_motion(at: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.position = at
	event.global_position = at
	Input.parse_input_event(event)
	Input.flush_buffered_events()

func click_view(at: Vector2) -> void:
	mouse_motion(at)
	for pressed: bool in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = at
		event.global_position = at
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame

func click_world(at: Vector2) -> void:
	await click_view(app.call("world_to_view", at))

func click_control(control: Control) -> void:
	check(control.is_visible_in_tree(), "A clicked UI control must be visible")
	await click_view(control.get_global_rect().get_center())

func key(code: Key, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.physical_keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)
	Input.flush_buffered_events()

func tap(code: Key) -> void:
	key(code, true)
	await process_frame
	key(code, false)
	await frames()

func capture(label: String) -> void:
	if capture_directory.is_empty():
		return
	await frames(8)
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	var filename := "%s-%dx%d.png" % [label, root.size.x, root.size.y]
	check(shot.get_size() == root.size, "Captured image dimensions must match the window")
	check(shot.save_png(capture_directory.path_join(filename)) == OK, "Save screenshot " + filename)
	print("QUARTER_CAPTURE ", capture_directory.path_join(filename))

func check_world_fit() -> void:
	var origin: Vector2 = app.call("world_to_view", Vector2.ZERO)
	var end: Vector2 = app.call("world_to_view", Vector2(1600, 900))
	var horizontal: Vector2 = app.call("world_to_view", Vector2(1600, 0))
	var vertical: Vector2 = app.call("world_to_view", Vector2(0, 900))
	check(origin.x >= -0.5 and origin.y >= -0.5 and end.x <= root.size.x + 0.5 and end.y <= root.size.y + 0.5, "Entire art canvas must fit the viewport")
	check(is_equal_approx((horizontal.x - origin.x) / 1600.0, (vertical.y - origin.y) / 900.0), "Canvas fit must preserve the background aspect ratio")
	var headquarters: Node2D = app.get("headquarters")
	var atmosphere: Node2D = headquarters.get("atmosphere")
	check(is_instance_valid(atmosphere) and atmosphere.get_parent() == headquarters, "Headquarters atmosphere must complete initialization and join the scene tree")
	check(app.find_children("*", "CharacterBody3D", true, false).is_empty(), "Current scene flow must not instantiate the legacy first-person controller")
	for vertex: Vector2 in headquarters.get("table_polygon"):
		var mapped: Vector2 = app.call("world_to_view", vertex)
		check(Rect2(Vector2.ZERO, Vector2(root.size)).has_point(mapped), "Every table hotspot vertex must remain on screen")
	var center: Vector2 = headquarters.get("table_center")
	check(Geometry2D.is_point_in_polygon(center, headquarters.get("table_polygon")), "The table click target must lie inside its interaction polygon")
	check_art_assets()

func check_art_assets() -> void:
	var camp: Node2D = app.get("camp")
	var headquarters: Node2D = app.get("headquarters")
	var camp_art: Texture2D = camp.get("background_texture")
	var headquarters_art: Texture2D = headquarters.get("background").texture
	for texture: Texture2D in [camp_art, headquarters_art]:
		check(texture != null, "Current camp and headquarters must load their authored artwork")
		if texture != null:
			check(absf(float(texture.get_width()) / texture.get_height() - 1600.0 / 900.0) < 0.002, "Authored background aspect ratio must match the fixed picture plane without stretching")
	var sprite: Sprite2D = camp.get("avatar").get("sprite")
	check(sprite != null and sprite.texture != null, "The movable commander must provide a rendered character texture")
	check(sprite != null and camp.get("avatar").is_ancestor_of(sprite), "Commander renderer must complete initialization inside its actor node")
	# A transparent SubViewport is a GPU render target. The headless dummy renderer
	# has no image to inspect; do not pass a placeholder off as visual verification.
	if sprite != null and sprite.texture != null and DisplayServer.get_name() != "headless":
		var art := sprite.texture.get_image()
		check(art != null and art.detect_alpha() != Image.ALPHA_NONE, "Rendered commander must contain alpha transparency instead of an opaque rectangle")
		if art != null:
			check(art.get_pixel(0, 0).a < 0.01 and art.get_pixel(art.get_width() - 1, art.get_height() - 1).a < 0.01, "Commander sprite corners must remain transparent over the camp painting")

func check_headquarters_and_dashboard() -> void:
	var camp: Node2D = app.get("camp")
	var headquarters: Node2D = app.get("headquarters")
	var overlay: CanvasLayer = app.get("dashboard_overlay")
	check(app.get("mode") == "headquarters", "Entrance interaction must reach fixed headquarters")
	check(not camp.visible and headquarters.visible, "Only the headquarters art scene must be visible inside")
	check(not is_instance_valid(overlay.get("dashboard")), "Dashboard must remain lazy before the first table click")
	check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Headquarters must keep the mouse cursor visible")
	var camp_position: Vector2 = camp.call("get_actor_position")
	var fixed_transform := headquarters.transform
	for code: Key in [KEY_W, KEY_A, KEY_S, KEY_D]:
		key(code, true)
	await frames(12)
	for code: Key in [KEY_W, KEY_A, KEY_S, KEY_D]:
		key(code, false)
	mouse_motion(Vector2(40, 130))
	await frames()
	check(headquarters.transform.is_equal_approx(fixed_transform), "WASD and mouse motion must not change the fixed headquarters view")
	check(camp_position.is_equal_approx(camp.call("get_actor_position")), "Headquarters input must not move the hidden camp actor")
	await tap(KEY_E)
	check(not overlay.call("is_open"), "Legacy E interaction must not open the fixed-view dashboard")
	await click_world(Vector2(90, 190))
	check(not overlay.call("is_open"), "Clicking outside the table polygon must not open the dashboard")
	var table_center: Vector2 = headquarters.get("table_center")
	mouse_motion(app.call("world_to_view", table_center))
	await frames()
	check(headquarters.get("is_hovered"), "Mouse hover must match the visible table after viewport scaling")
	await capture("headquarters")
	await click_world(table_center)
	await frames()
	check(overlay.call("is_open"), "Direct map click must open the dashboard")
	var dashboard: Control = overlay.get("dashboard")
	check(is_instance_valid(dashboard), "The first map click must instantiate the dashboard")
	if not is_instance_valid(dashboard):
		return
	dashboard._select_workspace("market")
	await frames()
	check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Dashboard must keep a visible UI cursor")
	check(dashboard.get("embedded_in_camp"), "The reused dashboard must retain embedded mode")
	check(dashboard.get("stock_buttons").size() == 5, "The five initial watched securities remain available offline")
	await click_control(dashboard.get("stock_buttons")[1])
	await frames()
	check(dashboard.get("selected") == 1, "Dashboard stock selection must respond to a real UI click")
	# Inject public OHLCV only into this isolated runner; production stays empty offline.
	var history: Array = []
	for offset: int in 80:
		var date := Time.get_datetime_string_from_unix_time(Time.get_unix_time_from_datetime_string("2026-06-01T00:00:00")+offset*86400).left(10)
		history.append({"date":date,"open":100.0,"high":110.0,"low":90.0,"close":105.0,"volume":1000})
	var gateway: Node = dashboard.research_view.gateway
	var payload := {"provider":"KIS","code":"000660","currency":"KRW","market":"KRX","adjusted":true,"fetched_at":1790640000,"requested_start":"2026-06-01","requested_end":"2026-09-28","candles":history}
	gateway._kis_completed("000660",gateway.generation,payload)
	await click_control(dashboard.get("period_buttons")[0])
	await frames()
	check(dashboard.get("chart").get("candles").size() == 22, "Chart period UI must retain one-month data")
	Fixture.install(dashboard)
	await capture("dashboard")
	check(dashboard.body.get_global_rect().end.x <= root.size.x+1,"Market fits viewport without a sample account")
	await click_control(dashboard.portfolio_button)
	await frames()
	check(dashboard.live_portfolio_page.visible,"Portfolio entry opens the actual account workspace")
	dashboard._show_plan()
	await frames()
	check(dashboard.get("dialog").visible, "The portfolio plan popup must open from its dashboard button")
	await tap(KEY_ESCAPE)
	check(not dashboard.get("dialog").visible and overlay.call("is_open") and app.get("mode") == "headquarters", "First Escape must close only the plan popup")
	await tap(KEY_ESCAPE)
	check(not overlay.call("is_open") and app.get("mode") == "headquarters", "Second Escape must return only to the same headquarters composition")
	check(headquarters.transform.is_equal_approx(fixed_transform), "Dashboard close must preserve the fixed headquarters transform")
	await click_world(table_center)
	await frames()
	check(overlay.get("dashboard") == dashboard, "Reopening the map must reuse the dashboard instance")
	check(dashboard.get("selected") == 1 and dashboard.simulation_plan.rows[0].target == 20.0 and dashboard.get("chart").get("candles").size() == 22, "Selection, target and chart period must survive the dashboard round trip")
	await click_control(overlay.get("close_button"))
	await frames()
	check(not overlay.call("is_open") and app.get("mode") == "headquarters", "Dashboard return button must return to headquarters, not camp")
	await click_control(app.get("return_button"))
	await frames()
	check(app.get("mode") == "camp", "Explicit camp return button must leave the headquarters")
	check(camp.visible and not headquarters.visible, "Returning outside must restore the camp scene")
	check(camp_position.distance_to(camp.call("get_actor_position")) < 2.0, "Returning outside must restore the saved entrance-area actor position")
	await click_control(app.get("enter_button"))
	await frames()
	check(app.get("mode") == "headquarters", "The restored entrance position must permit re-entry")
	await tap(KEY_ESCAPE)
	check(app.get("mode") == "camp" and not overlay.call("is_open"), "Escape without overlays must return headquarters to camp exactly once")
	await tap(KEY_ESCAPE)
	check(app.get("mode") == "camp", "Escape in camp must not activate a stale transition")

func check_navigation_and_enter() -> void:
	var camp: Node2D = app.get("camp")
	var navigation: RefCounted = camp.get("navigation")
	var avatar: Node2D = camp.get("avatar")
	var start: Vector2 = camp.call("get_actor_position")
	await check_hud_occlusion(camp, navigation)
	check(navigation.call("is_walkable", start), "Camp spawn must have a valid walkable footprint")
	check(not app.get("enter_button").visible, "Entrance button must remain hidden while the actor is far away")
	var blocked: PackedVector2Array = camp.get("blocked_polygons")[0]
	var blocked_center := Vector2.ZERO
	for point: Vector2 in blocked:
		blocked_center += point / blocked.size()
	check(not navigation.call("is_walkable", blocked_center), "Camp building footprint must block navigation")
	await click_world(blocked_center)
	await frames(8)
	check(camp.call("get_actor_position").is_equal_approx(start), "Clicking a solid building must not move or teleport the actor")
	await click_world(Vector2(45, 120))
	await frames(8)
	check(camp.call("get_actor_position").is_equal_approx(start), "Clicking distant scenery outside the clearing must not move the actor")
	var destination := start
	for offset: Vector2 in [Vector2(160, 0), Vector2(-160, 0), Vector2(0, -120)]:
		if navigation.call("is_walkable", start + offset):
			destination = start + offset
			break
	check(destination.distance_to(start) > 100.0, "The visible clearing must provide a useful click-to-move route")
	await click_world(destination)
	check(avatar.get("moving"), "Ground click must start a path, not teleport the actor")
	check(camp.call("get_actor_position").distance_to(destination) > 50.0, "First click frame must not teleport to its destination")
	await wait_for_walk(camp, navigation)
	check(camp.call("get_actor_position").distance_to(destination) < 1.0, "Click-to-move must reach the exact valid destination")
	var outside_transform := camp.transform
	key(KEY_W, true)
	mouse_motion(Vector2(1250, 170))
	await frames(8)
	key(KEY_W, false)
	check(camp.transform.is_equal_approx(outside_transform), "Mouse motion and keys must not rotate the quarter-view camera")
	check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Quarter-view exploration must never capture the mouse")
	var entry: PackedVector2Array = camp.get("entry_polygon")
	var entry_center := Vector2.ZERO
	for point: Vector2 in entry:
		entry_center += point / entry.size()
	await click_world(entry_center)
	check(app.get("mode") == "camp", "Clicking the entrance from far away must approach before entering")
	await wait_for_walk(camp, navigation)
	check(camp.call("is_near_entrance"), "Entrance click must path to the doorway approach point")
	check(app.get("enter_button").visible, "Entrance interaction UI must appear when near the doorway")
	await click_world(entry_center)
	await frames()
	check(app.get("mode") == "headquarters", "A near entrance click must enter headquarters")

func check_hud_occlusion(camp: Node2D, navigation: RefCounted) -> void:
	# At 16:9 the lower clearing lies behind the opaque instruction panel. At
	# 3:2 the panel lies in the matte instead, so there is no overlapping ground.
	if root.size != Vector2i(1280, 720):
		return
	var foot := Vector2(1050, 860)
	var at: Vector2 = app.call("world_to_view", foot)
	var footer: Control = app.get("hud").get("_footer")
	check(navigation.call("is_walkable", foot), "HUD occlusion fixture must cover otherwise walkable ground")
	check(footer.get_global_rect().has_point(at), "HUD occlusion fixture must lie inside the visible footer")
	var start: Vector2 = camp.call("get_actor_position")
	await click_view(at)
	await frames(8)
	check(camp.call("get_actor_position").is_equal_approx(start) and not camp.get("avatar").get("moving"), "Clicking the footer must not issue a move command to the ground underneath")
	if DisplayServer.get_name() == "headless":
		return
	# A high-contrast world fixture tests actual rendered ordering, not only z
	# properties. The footer must still cover even white art at an actor's depth.
	var fixture := Polygon2D.new()
	fixture.position = foot
	fixture.polygon = PackedVector2Array([Vector2(-20, -12), Vector2(20, -12), Vector2(20, 12), Vector2(-20, 12)])
	fixture.color = Color.WHITE
	fixture.z_index = int(foot.y)
	app.get("world").add_child(fixture)
	await frames(3)
	await RenderingServer.frame_post_draw
	var picture := root.get_texture().get_image()
	var pixel := picture.get_pixel(int(at.x), int(at.y))
	check(maxf(pixel.r, maxf(pixel.g, pixel.b)) < 0.70, "Rendered HUD must cover high-contrast world art even at the actor's foreground depth")
	fixture.queue_free()
	await frames(3)

func wait_for_walk(camp: Node2D, navigation: RefCounted) -> void:
	var avatar: Node2D = camp.get("avatar")
	var route_stayed_walkable := true
	for frame: int in range(500):
		await physics_frame
		await process_frame
		if not navigation.call("is_walkable", camp.call("get_actor_position")):
			route_stayed_walkable = false
		if not avatar.get("moving"):
			break
	check(not avatar.get("moving"), "Camp route must finish within the test deadline")
	check(route_stayed_walkable, "Every simulated movement frame must keep the actor footprint out of obstacles and boundaries")

func check_path_corner_clearance() -> void:
	# A deliberately concave route catches diagonal and path-smoothing corner cuts,
	# independently of the current painting's precise obstacle coordinates.
	var navigation: RefCounted = load("res://scripts/camp_navigation.gd").new()
	var boundary := PackedVector2Array([Vector2(0, 0), Vector2(320, 0), Vector2(320, 320), Vector2(0, 320)])
	var obstacle := PackedVector2Array([Vector2(115, 90), Vector2(205, 90), Vector2(205, 230), Vector2(115, 230)])
	var obstacles: Array[PackedVector2Array] = [obstacle]
	navigation.call("configure", boundary, obstacles)
	var route: PackedVector2Array = navigation.call("path_to", Vector2(45, 160), Vector2(275, 160))
	check(route.size() >= 4, "A blocked direct route must produce a detour around the obstacle")
	var safe := true
	for index: int in range(1, route.size()):
		var length := route[index - 1].distance_to(route[index])
		for sample: int in range(int(ceil(length)) + 1):
			var at := route[index - 1].lerp(route[index], minf(1.0, sample / maxf(length, 1.0)))
			if not navigation.call("is_walkable", at):
				safe = false
	check(safe, "Smoothed path segments must not cut obstacle corners, including the actor radius")
	check(navigation.call("path_to", Vector2(45, 160), Vector2(160, 160)).is_empty(), "A blocked destination must not receive a route")
	check(navigation.call("path_to", Vector2(45, 160), Vector2(1, 1)).is_empty(), "Destinations too close to the clearing boundary must be rejected")

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if not args.is_empty():
		if args.size() != 1 or not args[0].is_absolute_path() or DisplayServer.get_name() == "headless":
			push_error("Optional captures require a GPU renderer and one absolute output directory")
			quit(1)
			return
		capture_directory = args[0]
		if DirAccess.make_dir_recursive_absolute(capture_directory) != OK:
			push_error("Cannot create capture directory")
			quit(1)
			return
	root.content_scale_factor = 1.0
	root.position = Vector2i(30, 30)
	check_path_corner_clearance()
	for resolution: Vector2i in [Vector2i(1280, 720), Vector2i(1440, 960)]:
		root.size = resolution
		app = load("res://scenes/phalanx.tscn").instantiate() as Control
		root.add_child(app)
		current_scene = app
		await frames(8)
		var initialized := is_instance_valid(app.get("camp")) and is_instance_valid(app.get("headquarters")) and is_instance_valid(app.get("hud")) and is_instance_valid(app.get("dashboard_overlay"))
		check(initialized, "The current scene and every required controller must complete initialization")
		if not initialized:
			app.queue_free()
			await frames()
			print("PHALANX_QUARTER_FLOW_TEST: FAIL (scene initialization)")
			quit(1)
			return
		check(app.get("mode") == "camp", "Startup must show the quarter-view camp")
		check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Startup must not capture the mouse")
		check_world_fit()
		await capture("camp")
		await check_navigation_and_enter()
		await check_headquarters_and_dashboard()
		app.queue_free()
		await frames()
	print("PHALANX_QUARTER_FLOW_TEST: %s (%d checks; synthetic viewport input; renderer=%s)" % ["PASS" if failures == 0 else "FAIL (%d)" % failures, checks, DisplayServer.get_name()])
	quit(0 if failures == 0 else 1)

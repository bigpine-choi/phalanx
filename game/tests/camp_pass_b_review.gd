extends SceneTree
## HISTORICAL: preserved art pass B comparison; do not use for current-design acceptance.
## Current scene-flow review/captures: res://tests/quarter_flow_test.gd.
## GPU-only captures: immutable comparison pose plus the actual startup/HUD state.
## No production shortcuts or OS input claims. Output stays outside the project.

var camp: Node3D
var output: String
var phase: String
var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func frames(count: int) -> void:
	for i in count:
		await process_frame

func capture(label: String) -> void:
	await frames(30)
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	var file := "%s-%s-%dx%d.png" % [phase, label, root.size.x, root.size.y]
	if shot.save_png(output.path_join(file)) != OK or shot.get_size() != root.size:
		failures += 1
	print("SHOT ", file)

func tap(code: Key) -> void:
	for pressed: bool in [true, false]:
		var event := InputEventKey.new()
		event.keycode = code
		event.physical_keycode = code
		event.pressed = pressed
		Input.parse_input_event(event)

func review_interaction() -> void:
	var player: CharacterBody3D = camp.get("player")
	var overlay: CanvasLayer = camp.get("dashboard_overlay")
	var player_camera: Camera3D = player.get("camera")
	player_camera.make_current()
	player.position = Vector3(0, 0.04, -2.2)
	player.rotation = Vector3.ZERO
	player.get("head").rotation = Vector3.ZERO
	player_camera.look_at(Vector3(0, 0.96, 0))
	camp.get("camp_hud").show()
	player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
	for pressed: bool in [true, false]:
		var click := InputEventMouseButton.new()
		click.button_index = MOUSE_BUTTON_LEFT
		click.position = Vector2(root.size) * 0.5
		click.pressed = pressed
		Input.parse_input_event(click)
	await capture("interaction")
	if not player.get("exploring") or not camp.get("hover_hint").visible or camp.get("capture_prompt").visible:
		failures += 1
	var saved_position := player.position
	var saved_view := player_camera.global_transform
	tap(KEY_E)
	await capture("dashboard")
	if not overlay.call("is_open") or player.get("exploring"):
		failures += 1
	tap(KEY_ESCAPE)
	await capture("returned")
	if overlay.call("is_open") or not player.get("exploring") or not saved_position.is_equal_approx(player.position) or not saved_view.is_equal_approx(player_camera.global_transform):
		failures += 1
	player.call("pause_exploration")

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2 or not args[0].is_absolute_path() or not args[1].is_valid_filename() or DisplayServer.get_name() == "headless":
		push_error("Use a GPU renderer: --script res://tests/camp_pass_b_review.gd -- ABSOLUTE_OUTPUT_DIR LABEL")
		quit(1)
		return
	var project := ProjectSettings.globalize_path("res://").replace("\\", "/").to_lower().trim_suffix("/")
	var target := args[0].replace("\\", "/").simplify_path().to_lower().trim_suffix("/")
	if target == project or target.begins_with(project + "/") or DirAccess.make_dir_recursive_absolute(args[0]) != OK:
		push_error("Capture directory must be writable and outside the project")
		quit(1)
		return
	output = args[0]
	phase = args[1]
	root.content_scale_factor = 1.0
	root.position = Vector2i(35, 35)
	for window_size: Vector2i in [Vector2i(1280, 720), Vector2i(1440, 960)]:
		root.size = window_size
		camp = load("res://scenes/command_camp.tscn").instantiate()
		root.add_child(camp)
		current_scene = camp
		camp.get_node("Environment/CampLighting").set_process(false)
		await frames(60)
		await capture("startup")
		camp.get("camp_hud").hide()
		await capture("startup-clean")
		# This pose is deliberately independent of scene/player defaults and must
		# stay identical when copied to an earlier revision for an art comparison.
		var camera := Camera3D.new()
		camp.add_child(camera)
		camera.position = Vector3(0, 1.80, -2.40)
		camera.rotation_degrees = Vector3(-12, 180, 0)
		camera.fov = 64.0
		camera.near = 0.05
		camera.far = 210.0
		camera.make_current()
		print("FIXED_POSE ", camera.transform, " FOV=", camera.fov)
		await capture("fixed")
		camera.position = Vector3(-2.56, 1.80, -0.10)
		camera.look_at(Vector3(0, 1.0, 0))
		await capture("detail-left")
		camera.queue_free()
		await review_interaction()
		camp.queue_free()
		await frames(4)
	print("PASS_B_CAPTURE_DONE ", phase, " failures=", failures)
	quit(0 if failures == 0 else 1)

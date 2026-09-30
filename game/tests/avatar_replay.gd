extends SceneTree
## Deterministic ACTUAL RENDER replay, driven by synthetic Godot mouse input.
## The route is deliberately compatible with the preserved pre-animation project.
## --resolution 1440x960 --fixed-fps 30 --write-movie ABSOLUTE_FILE.avi
## --script res://tests/avatar_replay.gd -- before|after
## This is not a recording of operating-system input or a human play session.

var app: Control
var camp: Node2D
var banner: Label
var replay_name := "after"
var failed := false


func _initialize() -> void:
	call_deferred("_run")


func frames(count: int) -> void:
	for index: int in count:
		await process_frame


func label_stage(text: String) -> void:
	banner.text = "SYNTHETIC REPLAY / %s\n%s" % [replay_name.to_upper(), text]
	print("AVATAR_REPLAY_STAGE ", text)


func click_world(point: Vector2) -> void:
	var at: Vector2 = app.call("world_to_view", point)
	var motion := InputEventMouseMotion.new()
	motion.position = at
	motion.global_position = at
	Input.parse_input_event(motion)
	Input.flush_buffered_events()
	for pressed: bool in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = at
		event.global_position = at
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame


func finish_walk() -> void:
	for frame: int in 900:
		await process_frame
		if not camp.get("avatar").get("moving"):
			await frames(18)
			return
	failed = true
	push_error("Replay route did not finish within 30 seconds")


func move_to(point: Vector2, stage: String) -> void:
	label_stage(stage)
	await click_world(point)
	await finish_walk()
	if camp.call("get_actor_position").distance_to(point) > 2.0:
		failed = true
		push_error("Replay destination rejected or not reached: " + str(point))


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if not args.is_empty():
		replay_name = args[0]
	root.content_scale_factor = 1.0
	# Match the MovieWriter's configured viewport size exactly. CLI window sizing
	# alone is insufficient for a standalone SceneTree on this Windows/DPI setup.
	root.size = Vector2i(1440, 960)
	app = load("res://scenes/phalanx.tscn").instantiate() as Control
	root.add_child(app)
	current_scene = app
	await frames(8)
	print("AVATAR_REPLAY_VIEWPORT ", root.size)
	camp = app.get("camp")
	var replay_layer := CanvasLayer.new()
	replay_layer.layer = 100
	root.add_child(replay_layer)
	banner = Label.new()
	banner.position = Vector2(18, 84)
	banner.add_theme_font_size_override("font_size", 17)
	banner.add_theme_color_override("font_color", Color("fff1c6"))
	banner.add_theme_color_override("font_outline_color", Color("141713"))
	banner.add_theme_constant_override("outline_size", 5)
	banner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	replay_layer.add_child(banner)
	label_stage("Same route: courtyard to headquarters entrance")
	var primary_start := Engine.get_process_frames()
	await frames(30)
	await click_world(camp.get("entrance_position"))
	await finish_walk()
	if not camp.call("is_near_entrance"):
		failed = true
		push_error("Replay must reach the entrance")
	# Both versions retain the same first nine-second chapter. A faster baseline
	# waits at the entrance instead of resetting while the new actor still walks.
	await frames(maxi(30, 270 - int(Engine.get_process_frames() - primary_start)))
	label_stage("Four directions / reset to the same courtyard start")
	camp.call("restore_position", camp.get("spawn_position"))
	await frames(30)
	await move_to(Vector2(942, 530), "North: walk, then retain facing while idle")
	await move_to(Vector2(780, 530), "West: walk, then retain facing while idle")
	await move_to(Vector2(780, 650), "South: walk, then retain facing while idle")
	await move_to(Vector2(980, 650), "East: walk, then retain facing while idle")
	label_stage("Retarget while moving: northeast, then south")
	await click_world(Vector2(1110, 440))
	await frames(20)
	await click_world(Vector2(1000, 710))
	await finish_walk()
	await move_to(Vector2(720, 460), "Final approach: long route beside the foreground tree")
	label_stage("Entrance: arrive, settle, retain the final facing")
	await click_world(camp.get("entrance_position"))
	await finish_walk()
	await frames(45)
	print("PHALANX_AVATAR_REPLAY: %s (%s; synthetic Godot mouse input)" % ["FAIL" if failed else "PASS", replay_name])
	quit(1 if failed else 0)

extends SceneTree
## GPU screenshots or native QA fixture. Native mode NEVER injects input.
## -- baseline|after|native OUTPUT_DIRECTORY 1280|1440
var app: Control
var camp: Node2D
var output := ""
var tag := "after"
var native := false
var previous := ""
var last_capture := -100.0
var sequence := 0

class NativeObserver extends Node:
	var review: SceneTree
	func _input(event: InputEvent) -> void:
		if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_F9:
			# Test fixture only: allow the inspection tool time to observe walking.
			Engine.time_scale = 1.0 if Engine.time_scale < 1.0 else 0.25
			review.update_title()
			review.call_deferred("log_state", "qa_time_scale")
			get_viewport().set_input_as_handled()
		elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			review.call_deferred("log_state", "mouse_click")

func _initialize() -> void:
	call_deferred("run")

func frames(count: int) -> void:
	for index: int in count:
		await process_frame

func save_frame(name: String) -> void:
	await RenderingServer.frame_post_draw
	var result := root.get_texture().get_image().save_png(output.path_join(name + ".png"))
	if result != OK:
		push_error("Capture failed: " + name)
		quit(1)

func run() -> void:
	var args := OS.get_cmdline_user_args()
	tag = args[0]
	native = tag == "native"
	output = args[1]
	DirAccess.make_dir_recursive_absolute(output)
	root.content_scale_factor = 1.0
	root.size = Vector2i(1280,720) if args.size() > 2 and args[2] == "1280" else Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await frames(12)
	camp = app.camp
	if native:
		update_title()
		var observer := NativeObserver.new()
		observer.review = self
		root.add_child(observer)
		root.focus_entered.connect(func() -> void: log_state("focus_in"))
		root.focus_exited.connect(func() -> void: log_state("focus_out"))
		log_state("ready")
		return
	var samples := {"sun": Vector2(984,714), "canopy": Vector2(1090,550), "tree": Vector2(701,572), "wall": Vector2(1040,389), "cape": Vector2(984,714)}
	for label: String in samples:
		var point: Vector2 = samples[label] * camp.ART_SCALE + camp.ART_OFFSET
		camp.restore_position(point)
		var actor: Node2D = camp.avatar
		actor.set_physics_process(false)
		actor.gait.yaw = PI if label == "cape" else 0.0
		actor.gait.walk_blend = 0.0
		actor.gait.reset_grounding(actor.position, actor._depth())
		actor.visual.present(actor.gait, 0.0)
		await frames(6)
		await save_frame("%s-%s-%d" % [tag,label,root.size.x])
		actor.visual.viewport.get_texture().get_image().save_png(output.path_join("%s-%s-actor.png" % [tag,label]))
		print("REVIEW_SAMPLE ",label," ",actor.position," ",actor.debug_snapshot())
	print("PHALANX_LIGHTING_REVIEW: PASS (actual GPU capture; synthetic positioning)")
	quit()

func update_title() -> void:
	root.title = "Phalanx - Shade review %dx%d (%.2fx QA)" % [root.size.x,root.size.y,Engine.time_scale]

func log_state(event: String) -> void:
	if camp == null:
		return
	var state := {"event":event, "time_ms":Time.get_ticks_msec(), "mode":app.mode,
		"time_scale":Engine.time_scale, "destination":str(camp.avatar.path[-1]) if not camp.avatar.path.is_empty() else "none",
		"dashboard":app.dashboard_overlay.is_open(), "position":[camp.avatar.position.x,camp.avatar.position.y],
		"moving":camp.avatar.moving, "facing":camp.avatar.gait.facing,
		"lighting":camp.avatar.debug_snapshot().get("lighting", {}), "resolution":[root.size.x,root.size.y]}
	var path := output.path_join("native-%d.jsonl" % root.size.x)
	var file := FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE)
	file.seek_end()
	file.store_line(JSON.stringify(state))
	file.close()
	print("NATIVE_STATE ",JSON.stringify(state))

func _process(_delta: float) -> bool:
	if not native or camp == null:
		return false
	var state := "%s/%s/%s/%s" % [app.mode,app.dashboard_overlay.is_open(),camp.avatar.moving,camp.avatar.gait.facing]
	if state != previous:
		previous = state
		log_state("state_change")
		# Native evidence is rendered by Godot after observed OS interaction.
		# No screenshots are presented as a human play recording.
		if not camp.avatar.moving and Time.get_ticks_msec() - last_capture > 500.0:
			last_capture = Time.get_ticks_msec()
			sequence += 1
			save_frame("native-%d-%02d-%s" % [root.size.x,sequence,app.mode])
	return false

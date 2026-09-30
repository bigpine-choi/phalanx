extends SceneTree
## Observable movement/animation invariants. Synthetic routes and notifications;
## this does not establish visual quality, OS focus behavior, or human testing.

var checks := 0
var failures := 0
var app: Control
var camp: Node2D
var avatar: Node2D


func _initialize() -> void:
	call_deferred("_run")


func check(condition: bool, message: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		push_error(message)


func frames(count: int) -> void:
	for index: int in count:
		await physics_frame
		await process_frame


func snapshot() -> Dictionary:
	return avatar.call("debug_snapshot")


func finish_walk() -> void:
	for index: int in 600:
		await physics_frame
		await process_frame
		if not avatar.get("moving"):
			return
	check(false, "Avatar must reach the requested destination before the deadline")


func move_and_check(destination: Vector2, facing: String) -> void:
	check(camp.call("walk_to", destination), "The direction fixture must have a valid navigable route")
	await finish_walk()
	await frames(40)
	var state := snapshot()
	check(avatar.position.distance_to(destination) < 1.0, "Animation must not change the navigation destination")
	check(state.facing == facing, "A cardinal route must retain its last facing when it stops: " + facing)
	check(not state.moving and state.speed < 0.01, "Arrival must settle to a stationary idle")
	check(state.walk_blend < 0.02, "Walking pose must blend back to idle after arriving")
	var phase: float = state.gait_phase
	await frames(15)
	check(snapshot().facing == facing and is_equal_approx(snapshot().gait_phase, phase), "Idle must preserve facing without continuing a sliding walk cycle")


func check_direction_and_idle() -> void:
	camp.call("restore_position", Vector2(940, 650))
	await frames(40)
	await move_and_check(Vector2(940, 480), "north")
	await move_and_check(Vector2(760, 480), "west")
	await move_and_check(Vector2(760, 650), "south")
	await move_and_check(Vector2(970, 650), "east")


func check_grounding_and_turns() -> void:
	camp.call("restore_position", Vector2(770, 600))
	await frames(40)
	check(camp.call("walk_to", Vector2(1100, 600)), "The long stride fixture must have a valid route")
	var previous := snapshot()
	var initial_distance: float = previous.total_distance
	var initial_phase: float = previous.gait_phase
	var anchored_samples := 0
	var planted_drift := 0.0
	var minimum_foot_height := 0.0
	var maximum_yaw_step := 0.0
	var maximum_registration_error := 0.0
	for index: int in 360:
		await physics_frame
		await process_frame
		var state := snapshot()
		maximum_yaw_step = maxf(maximum_yaw_step, absf(angle_difference(previous.yaw, state.yaw)))
		minimum_foot_height = minf(minimum_foot_height, minf(state.left_foot.y, state.right_foot.y))
		for side: String in ["left", "right"]:
			if previous[side + "_planted"] and state[side + "_planted"] and state.speed > 20.0:
				anchored_samples += 1
				planted_drift = maxf(planted_drift, previous[side + "_ground"].distance_to(state[side + "_ground"]))
			if state[side + "_planted"]:
				# Follow the actual renderer/camera/sprite transforms. A correct gait
				# target alone must not hide a misplaced or mis-scaled composite.
				var visual: Node2D = avatar.get("visual")
				var camera: Camera3D = visual.get("camera")
				var sprite: Sprite2D = avatar.get("sprite")
				var model: Node3D = visual.get("model")
				var model_foot: Vector3 = model.get(side + "_foot_world")
				var canvas_foot := camp.to_local(sprite.to_global(camera.unproject_position(model_foot)))
				maximum_registration_error = maxf(maximum_registration_error, canvas_foot.distance_to(state[side + "_ground"]))
		previous = state
		if not avatar.get("moving"):
			break
	check(anchored_samples > 12, "Real strides must contain observable planted-foot intervals")
	check(planted_drift < 2.5, "A stance foot must stay near the same authored ground point during a straight stride")
	check(minimum_foot_height > -0.02, "Foot targets must not penetrate below the model's ground plane")
	check(maximum_registration_error < 1.0, "Projected model feet must align with the same authored ground anchors used by navigation and shadows")
	check(maximum_yaw_step < 0.30, "Turning must progress over several frames instead of snapping or flipping")
	check(previous.total_distance > initial_distance + 1.0 and previous.gait_phase > initial_phase + 0.1, "Actual displacement must advance both travel and the locomotion cycle")
	await frames(40)
	var before := snapshot()
	check(camp.call("walk_to", Vector2(1100, 440)), "Retarget fixture must start moving")
	await frames(12)
	var at_retarget := avatar.position
	var yaw_before: float = snapshot().yaw
	check(camp.call("walk_to", Vector2(930, 710)), "A new destination must replace the current route")
	check(avatar.position.distance_to(at_retarget) < 0.01, "Retargeting must not teleport the navigation origin")
	await frames(1)
	check(absf(angle_difference(yaw_before, snapshot().yaw)) < 0.30, "Retargeting must not instantly flip the visible facing")
	await finish_walk()
	await frames(40)
	check(avatar.position.distance_to(Vector2(930, 710)) < 1.0, "Retargeted motion must arrive at the new endpoint")
	check(snapshot().total_distance > before.total_distance, "Retargeted gait must still track real travel")


func check_stop_focus_and_restore() -> void:
	check(camp.call("walk_to", Vector2(1040, 530)), "Focus fixture must have a valid route")
	await frames(15)
	camp.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_OUT)
	var stopped_at := avatar.position
	check(not avatar.get("moving"), "Synthetic focus-out notification must immediately cancel path travel")
	await frames(40)
	var stopped := snapshot()
	check(avatar.position.is_equal_approx(stopped_at) and stopped.speed < 0.01 and stopped.walk_blend < 0.02, "Focus stop must stay grounded and settle to idle without finishing the old path")
	camp.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
	await frames(8)
	check(avatar.position.is_equal_approx(stopped_at), "Focus-in must not resume an old movement command")
	check(camp.call("walk_to", camp.get("entrance_position")), "A fresh post-focus route must be accepted")
	await finish_walk()
	await frames(40)
	var entrance_state := snapshot()
	var entrance_position := avatar.position
	check(camp.call("try_enter"), "The animated actor must still enter from the doorway")
	await frames(20)
	check(app.get("mode") == "headquarters" and not avatar.get("moving"), "Entering headquarters must suspend the outdoor actor")
	app.call("return_to_camp")
	await frames(40)
	var returned := snapshot()
	check(app.get("mode") == "camp" and avatar.position.distance_to(entrance_position) < 1.0, "Camp return must restore the same ground position")
	check(returned.facing == entrance_state.facing and absf(angle_difference(returned.yaw, entrance_state.yaw)) < 0.05, "Camp return must preserve the last facing and idle orientation")
	check(not returned.moving and returned.speed < 0.01 and returned.walk_blend < 0.02, "Camp return must not resurrect an old walking cycle")


func check_small_path_bends() -> void:
	# Deliberately retain small waypoint bends instead of the navigation smoother
	# removing them. The rendered actor must not twitch from one bend to the next.
	camp.call("restore_position", Vector2(940, 650))
	await frames(40)
	var route := PackedVector2Array([Vector2(940, 650), Vector2(941, 625), Vector2(939, 600), Vector2(941, 575), Vector2(939, 550), Vector2(940, 525)])
	avatar.call("move_along", route)
	var stable_facing := true
	var reference_yaw := 0.0
	var began_sampling := false
	var maximum_sway := 0.0
	for index: int in 360:
		await physics_frame
		await process_frame
		if avatar.position.y < 599:
			var state := snapshot()
			stable_facing = stable_facing and state.facing == "north"
			if not began_sampling:
				reference_yaw = state.yaw
				began_sampling = true
			maximum_sway = maxf(maximum_sway, absf(angle_difference(reference_yaw, state.yaw)))
		if not avatar.get("moving"):
			break
	check(began_sampling and stable_facing and maximum_sway < deg_to_rad(10.0), "Small waypoint bends must retain one facing without a repeated visible turn oscillation")


func _run() -> void:
	root.size = Vector2i(1280, 720)
	app = load("res://scenes/phalanx.tscn").instantiate() as Control
	root.add_child(app)
	current_scene = app
	await frames(8)
	camp = app.get("camp")
	avatar = camp.get("avatar")
	check(avatar.has_method("debug_snapshot"), "The animated actor must expose its observable locomotion state")
	if not avatar.has_method("debug_snapshot"):
		quit(1)
		return
	check(snapshot().renderer_kind == "articulated_3d", "The current actor must use the articulated renderer, not the old bobbing cutout")
	await check_direction_and_idle()
	await check_grounding_and_turns()
	await check_small_path_bends()
	await check_stop_focus_and_restore()
	app.queue_free()
	await frames(4)
	print("PHALANX_AVATAR_ANIMATION_TEST: %s (%d checks; synthetic routes and focus notifications)" % ["PASS" if failures == 0 else "FAIL (%d)" % failures, checks])
	quit(0 if failures == 0 else 1)

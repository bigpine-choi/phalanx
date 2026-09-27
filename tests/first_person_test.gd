extends SceneTree
## Physics/input regression checks using synthetic events, not physical GUI input.

var failures := 0
var camp: Node3D
var player: CharacterBody3D
var interactor: Area3D
var overlay: CanvasLayer

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _settle(frames: int = 4) -> void:
	for frame: int in range(frames):
		await physics_frame
		await process_frame

func _key(code: Key, pressed: bool, echo: bool = false, physical_override: Key = KEY_NONE) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.physical_keycode = code if physical_override == KEY_NONE else physical_override
	event.pressed = pressed
	event.echo = echo
	Input.parse_input_event(event)

func _tap(code: Key, physical_override: Key = KEY_NONE) -> void:
	_key(code, true, false, physical_override)
	_key(code, false, false, physical_override)

func _motion(delta: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.relative = delta
	event.screen_relative = delta
	event.position = Vector2(root.size) * 0.5
	Input.parse_input_event(event)

func _place(at: Vector3, yaw: float = PI) -> void:
	player.call("pause_exploration")
	player.global_position = at
	player.rotation = Vector3(0, yaw, 0)
	player.get("head").rotation = Vector3(deg_to_rad(-12.0), 0, 0)
	player.get("camera").rotation = Vector3.ZERO
	player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
	player.call("begin_exploration")
	await _settle()

func _walk(code: Key, frames: int) -> void:
	_key(code, true)
	await _settle(frames)
	_key(code, false)
	await _settle()

func _assert_sweep_collision(at: Vector3, motion: Vector3, prefix: String) -> void:
	var from := Transform3D(Basis.IDENTITY, at)
	var collision := KinematicCollision3D.new()
	var hit: bool = player.test_move(from, motion, collision)
	check(hit, "Player capsule must collide with %s" % prefix)
	if hit:
		var collider: Node = collision.get_collider() as Node
		check(collider != null and String(collider.name).begins_with(prefix), "Capsule sweep must hit %s, got %s" % [prefix, collider.name if collider != null else "null"])

func _check_collision() -> void:
	# Ground and table are exercised by real move_and_slide physics frames below.
	await _place(Vector3(0, 0.8, -2.8))
	await _settle(45)
	check(player.is_on_floor() and absf(player.position.y) < 0.08, "Gravity must settle the player on the floor without falling below it")
	await _walk(KEY_W, 65)
	check(player.position.z <= -1.49 and player.position.z >= -1.58, "Walking forward must stop outside the solid table")
	check(absf(player.position.y) < 0.08, "Table collision must not lift or drop the player")
	_assert_sweep_collision(Vector3(0, 0.02, -3.1), Vector3(0, 0, -2), "TentRearWall")
	_assert_sweep_collision(Vector3(3.2, 0.02, -0.5), Vector3(2, 0, 0), "TentSideWallRight")
	_assert_sweep_collision(Vector3(0, 0.02, 5.3), Vector3(0, 0, 3), "ExplorationBoundaryFront")
	_assert_sweep_collision(Vector3(5.9, 0.02, 4.0), Vector3(3, 0, 0), "ExplorationBoundaryRight")
	var world: Node = camp.get_node("CampCollision")
	var crates: Array[Node] = world.find_children("SupplyCrateSolid*", "StaticBody3D", false, false)
	check(not crates.is_empty(), "Large supply crates must have solid collision")
	if not crates.is_empty():
		var crate: StaticBody3D = crates[0] as StaticBody3D
		var at: Vector3 = crate.global_position
		_assert_sweep_collision(Vector3(at.x, 0.02, at.z + 1.5), Vector3(0, 0, -2.0), "SupplyCrateSolid")
	var posts: Array[Node] = world.find_children("TentPostSolid*", "StaticBody3D", false, false)
	check(posts.size() >= 4, "Tent structural posts must have collision")
	for post_node: Node in posts:
		var post: StaticBody3D = post_node as StaticBody3D
		var at: Vector3 = post.global_position
		if at.z > 0:
			# The widened curtain skirt now stands in front of the post at floor level.
			_assert_sweep_collision(Vector3(at.x, 0.02, at.z + 1.0), Vector3(0, 0, -1.4), "CurtainSkirtSolid")
			_assert_sweep_collision(Vector3(at.x, 0.90, at.z + 1.0), Vector3(0, 0, -1.4), "TentPostSolid")
			break
	# The right-hand aisle must lead out into the nearby camp without snagging.
	await _place(Vector3(2.6, 0.04, -2.7))
	await _walk(KEY_W, 170)
	check(player.position.z > 3.5, "The side aisle must allow passage from inside the tent through its entrance")
	await _walk(KEY_W, 170)
	check(player.position.z <= 6.15 and player.position.z >= 6.0, "Walking in the camp must stop at the exploration boundary")
	check(player.is_on_floor() and absf(player.position.y + 0.14) < 0.025, "Outdoor walking must match the lowered terrain")
	player.rotation.y = 0.0
	await _walk(KEY_W, 165)
	check(player.position.z < 1.0 and player.position.z > -1.5, "The ramp must allow walking back up the right aisle without jumping")
	check(player.is_on_floor() and absf(player.position.y) < 0.025, "Returning through the ramp must reach the timber platform height")

func _check_movement_and_focus() -> void:
	await _place(Vector3(0, 0.04, 4.0), 0.0)
	# Accessibility/key-injection tools may supply a logical letter with an unrelated scan code.
	_key(KEY_W, true, false, KEY_F6)
	await _settle()
	check(player.velocity.z < -2.0, "Logical W must move forward when the physical key code is unrelated")
	_key(KEY_W, false, false, KEY_F6)
	await _settle()
	check(Vector2(player.velocity.x, player.velocity.z).is_zero_approx(), "Logical W release must clear movement with an unrelated physical code")
	_key(KEY_W, true)
	await _settle()
	var straight_speed := Vector2(player.velocity.x, player.velocity.z).length()
	_key(KEY_D, true)
	await _settle()
	var diagonal_speed := Vector2(player.velocity.x, player.velocity.z).length()
	check(straight_speed > 2.0 and is_equal_approx(straight_speed, diagonal_speed), "Diagonal input must retain walking speed rather than accelerate")
	_key(KEY_W, false)
	_key(KEY_D, false)
	var yaw: float = player.rotation.y
	var head: Node3D = player.get("head") as Node3D
	var pitch: float = head.rotation.x
	_motion(Vector2(1000, 1000))
	await _settle()
	check(is_equal_approx(player.rotation.y, yaw) and is_equal_approx(head.rotation.x, pitch), "The first capture-warp mouse event must be ignored")
	_motion(Vector2(120, 10000))
	await _settle()
	check(not is_equal_approx(player.rotation.y, yaw), "Mouse horizontal motion must rotate the player")
	check(head.rotation.x > -PI * 0.5 and head.rotation.x < 0, "Looking down must clamp before inversion")
	_motion(Vector2(0, -20000))
	await _settle()
	check(head.rotation.x < PI * 0.5 and head.rotation.x > 0, "Looking up must clamp before inversion")
	_tap(KEY_ESCAPE)
	await _settle()
	check(not player.get("exploring") and Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Exploration Escape must release the mouse and stop input")
	var paused_at: Vector3 = player.position
	yaw = player.rotation.y
	_key(KEY_W, true)
	_motion(Vector2(200, 200))
	await _settle(6)
	check(player.position.is_equal_approx(paused_at) and is_equal_approx(player.rotation.y, yaw), "Paused exploration must ignore movement and mouse look")
	_key(KEY_W, false)
	player.call("begin_exploration")
	_key(KEY_W, true)
	await _settle()
	player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_OUT)
	paused_at = player.position
	await _settle(6)
	check(not player.get("exploring") and player.position.is_equal_approx(paused_at), "Focus loss must immediately stop movement and release capture")
	player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
	check(not player.get("exploring"), "Focus return must require a fresh exploration click")
	player.call("begin_exploration")
	_key(KEY_W, true, true)
	await _settle(6)
	check(player.position.is_equal_approx(paused_at), "Focus return must clear held keys and ignore auto-repeat from an old press")
	yaw = player.rotation.y
	pitch = head.rotation.x
	_motion(Vector2(1500, 1500))
	await _settle()
	check(is_equal_approx(player.rotation.y, yaw) and is_equal_approx(head.rotation.x, pitch), "First mouse motion after focus return must not jump the view")
	_key(KEY_W, false)

func _check_interaction() -> void:
	await _place(Vector3(0, 0.04, -3.8))
	var camera: Camera3D = player.get("camera") as Camera3D
	camera.look_at(Vector3(0, 1.04, 0))
	await _settle()
	check(not interactor.get("hovered"), "Distant table must not be selectable")
	_tap(KEY_E)
	await _settle()
	check(not overlay.call("is_open"), "E from outside interaction distance must not open the dashboard")
	await _place(Vector3(0, 0.04, -2.2))
	camera.look_at(Vector3(0, 1.04, 0))
	await _settle()
	check(interactor.get("hovered"), "Nearby centered table must be selectable")
	var occluder := StaticBody3D.new()
	occluder.collision_layer = 1
	occluder.collision_mask = 0
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(1.0, 2.0, 0.15)
	shape.shape = box
	occluder.add_child(shape)
	camp.add_child(occluder)
	occluder.position = Vector3(0, 1.0, -1.75)
	await _settle()
	check(not interactor.get("hovered"), "A solid object between the player and table must block selection")
	_tap(KEY_E)
	await _settle()
	check(not overlay.call("is_open"), "E must not activate the table through a solid occluder")
	occluder.queue_free()
	await _settle()
	check(interactor.get("hovered"), "Removing the occluder must restore unobstructed selection")
	_tap(KEY_E, KEY_F6)
	await _settle()
	check(overlay.call("is_open"), "Logical E must open the nearby table even when the physical code is unrelated")
	var old_position: Vector3 = player.position
	var old_rotation: Vector3 = player.rotation
	var old_pitch: Vector3 = player.get("head").rotation
	_key(KEY_W, true)
	_motion(Vector2(800, 600))
	_tap(KEY_E)
	await _settle(12)
	_key(KEY_W, false)
	check(player.position.is_equal_approx(old_position) and player.rotation.is_equal_approx(old_rotation) and player.get("head").rotation.is_equal_approx(old_pitch), "Dashboard must freeze player position and view")
	check(Input.mouse_mode == Input.MOUSE_MODE_VISIBLE, "Dashboard must expose a cursor for UI interaction")
	_tap(KEY_ESCAPE)
	await _settle()
	check(not overlay.call("is_open") and player.get("exploring"), "Dashboard Escape must resume exploration without pausing it again")
	check(player.position.is_equal_approx(old_position) and player.rotation.is_equal_approx(old_rotation), "Closing dashboard must preserve position and view")

func _run() -> void:
	root.size = Vector2i(1280, 720)
	var packed: PackedScene = load("res://scenes/command_camp.tscn") as PackedScene
	camp = packed.instantiate() as Node3D
	root.add_child(camp)
	current_scene = camp
	await _settle()
	player = camp.get("player") as CharacterBody3D
	interactor = camp.get("table_interaction") as Area3D
	overlay = camp.get("dashboard_overlay") as CanvasLayer
	check(player != null and interactor != null and overlay != null, "First-person camp components must load")
	if player != null and interactor != null and overlay != null:
		await _check_collision()
		await _check_movement_and_focus()
		await _check_interaction()
	camp.queue_free()
	await _settle()
	print("PHALANX_FIRST_PERSON_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

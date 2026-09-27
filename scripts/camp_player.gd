extends CharacterBody3D
## First-person movement owns capture/focus state; modal UI only suspends it.

signal exploration_changed(value: bool)

const WALK_SPEED := 2.6
const EYE_HEIGHT := 1.65
const BODY_HEIGHT := 1.75
const BODY_RADIUS := 0.26
const MOUSE_SENSITIVITY := 0.0022
const PITCH_LIMIT := deg_to_rad(78.0)
const GRAVITY := 20.0

var camera: Camera3D
var head: Node3D
var exploring := false
var modal_blocked := false
var _window_focused := true
var _ignore_next_motion := true
var _held_keys: Dictionary = {}


func _ready() -> void:
	collision_layer = 4
	collision_mask = 1
	floor_snap_length = 0.15
	floor_stop_on_slope = true
	var body_shape := CapsuleShape3D.new()
	body_shape.radius = BODY_RADIUS
	body_shape.height = BODY_HEIGHT
	var shape := CollisionShape3D.new()
	shape.name = "PlayerCapsule"
	shape.shape = body_shape
	shape.position.y = BODY_HEIGHT * 0.5
	add_child(shape)
	head = Node3D.new()
	head.name = "Head"
	head.position.y = EYE_HEIGHT
	head.rotation.x = deg_to_rad(-15.0)
	add_child(head)
	camera = Camera3D.new()
	camera.name = "PlayerCamera"
	camera.fov = 70.0
	camera.near = 0.05
	camera.far = 210.0
	head.add_child(camera)
	camera.make_current()
	# Godot cameras face -Z; the entrance and table are ahead along +Z.
	rotation.y = PI
	_window_focused = get_window().has_focus()
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func begin_exploration() -> void:
	if modal_blocked or not _window_focused:
		return
	_held_keys.clear()
	velocity = Vector3.ZERO
	_ignore_next_motion = true
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	_set_exploring(true)


func pause_exploration() -> void:
	_held_keys.clear()
	velocity = Vector3.ZERO
	_ignore_next_motion = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	_set_exploring(false)


func set_modal_blocked(value: bool) -> void:
	modal_blocked = value
	if value:
		pause_exploration()
	elif _window_focused:
		begin_exploration()


func _set_exploring(value: bool) -> void:
	if exploring == value:
		return
	exploring = value
	exploration_changed.emit(value)


func _unhandled_input(event: InputEvent) -> void:
	if modal_blocked or not _window_focused:
		return
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT and event.pressed and not exploring:
			begin_exploration()
			get_viewport().set_input_as_handled()
		return
	if not exploring:
		return
	if event is InputEventKey:
		if event.keycode == KEY_ESCAPE and event.pressed:
			if not event.echo:
				pause_exploration()
			get_viewport().set_input_as_handled()
			return
		var code: int = event.physical_keycode
		# OS-injected/accessibility input can carry an unrelated physical code.
		if code not in [KEY_W, KEY_A, KEY_S, KEY_D]:
			code = event.keycode
		if code in [KEY_W, KEY_A, KEY_S, KEY_D]:
			# Ignore auto-repeat, especially after Alt+Tab with a key held down.
			if not event.echo:
				if event.pressed:
					_held_keys[code] = true
				else:
					_held_keys.erase(code)
			get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion:
		if _ignore_next_motion:
			_ignore_next_motion = false
			return
		rotate_y(-event.screen_relative.x * MOUSE_SENSITIVITY)
		head.rotation.x = clampf(head.rotation.x - event.screen_relative.y * MOUSE_SENSITIVITY, -PITCH_LIMIT, PITCH_LIMIT)
		get_viewport().set_input_as_handled()


func _physics_process(delta: float) -> void:
	if not exploring or modal_blocked or not _window_focused:
		velocity = Vector3.ZERO
		return
	var movement := Vector2(
		float(_held_keys.has(KEY_D)) - float(_held_keys.has(KEY_A)),
		float(_held_keys.has(KEY_S)) - float(_held_keys.has(KEY_W))
	).normalized()
	var direction := global_basis * Vector3(movement.x, 0.0, movement.y)
	velocity.x = direction.x * WALK_SPEED
	velocity.z = direction.z * WALK_SPEED
	if is_on_floor():
		velocity.y = 0.0
	else:
		velocity.y -= GRAVITY * delta
	move_and_slide()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		_window_focused = false
		pause_exploration()
	elif what == NOTIFICATION_WM_WINDOW_FOCUS_IN:
		# A fresh click is required after returning to the game window.
		_window_focused = true
		_held_keys.clear()
		_ignore_next_motion = true


func _exit_tree() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

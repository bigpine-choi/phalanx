extends Node2D
## Path follower only; gait and 3D compositing own the actor's visual pose.
signal movement_finished
const Gait := preload("res://scripts/commander_gait.gd")
const Visual := preload("res://scripts/commander_visual.gd")
const ACCELERATION := 300.0
const DECELERATION := 360.0
var speed := 116.0
var current_speed := 0.0
var moving := false
var active := true
var velocity := Vector2.ZERO
var path := PackedVector2Array()
var sprite: Sprite2D
var visual: Node2D
var gait := Gait.new()
var lighting_field: RefCounted
var _path_index := 0
var _last_origin := Vector2.ZERO
var _time := 0.0

func _ready() -> void:
	name = "Commander"
	visual = Visual.new()
	add_child(visual)
	sprite = visual.sprite
	_last_origin = position
	gait.reset_grounding(position, _depth())
	visual.present(gait, 0.0)
	sync_lighting(0.0, true)

func move_along(points: PackedVector2Array) -> void:
	path = points
	_path_index = 1 if path.size() > 1 else 0
	moving = active and path.size() > 1
	# Retargets preserve gait phase and momentum; the path still owns position.
	if not moving:
		stop()

func stop() -> void:
	path.clear()
	_path_index = 0
	moving = false
	velocity = Vector2.ZERO
	current_speed = 0.0

func set_active(value: bool) -> void:
	active = value
	if not active:
		stop()
		gait.reset_grounding(position, _depth())
		visual.present(gait, _time)
	sync_lighting(0.0, true)
	visual.set_render_active(value)

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		stop()

func sync_lighting(delta: float, immediate := false) -> void:
	if visual != null:
		var visibility: float = lighting_field.sunlight_at(position) if lighting_field != null else 1.0
		visual.update_lighting(visibility, delta, immediate)

func _depth() -> float:
	return lerpf(0.94, 1.02, clampf((position.y - 370.0) / 490.0, 0.0, 1.0))

func _remaining_length() -> float:
	if not moving or _path_index >= path.size():
		return 0.0
	var distance := position.distance_to(path[_path_index])
	for index in range(_path_index + 1, path.size()):
		distance += path[index - 1].distance_to(path[index])
	return distance

func _physics_process(delta: float) -> void:
	var relocated := position.distance_squared_to(_last_origin) > 0.01
	if relocated:
		gait.reset_grounding(position, _depth())
	var origin := position
	var depth := _depth()
	if active and moving:
		var heading := position.direction_to(path[_path_index])
		var perspective := Vector2(heading.x, heading.y / sin(Gait.ELEVATION)).length()
		var desired_speed := speed * depth / maxf(perspective, 1.0)
		var yaw_error := absf(angle_difference(gait.yaw, atan2(heading.x, heading.y / sin(Gait.ELEVATION))))
		desired_speed *= lerpf(1.0, 0.38, clampf((yaw_error - 0.5) / 2.0, 0.0, 1.0))
		desired_speed = minf(desired_speed, sqrt(2.0 * DECELERATION * _remaining_length()))
		current_speed = move_toward(current_speed, desired_speed, (ACCELERATION if desired_speed > current_speed else DECELERATION) * delta)
		var remaining := current_speed * delta
		while moving and remaining > 0.0:
			var target := path[_path_index]
			var displacement := target - position
			var distance := displacement.length()
			if distance <= remaining + 0.015:
				position = target
				remaining = maxf(0.0, remaining - distance)
				_path_index += 1
				if _path_index >= path.size():
					stop()
					movement_finished.emit()
			else:
				position += displacement.normalized() * remaining
				remaining = 0.0
	velocity = (position - origin) / maxf(delta, 0.001)
	if not moving:
		velocity = Vector2.ZERO
	_time += delta if active else 0.0
	gait.update(delta, position - origin, position, depth, moving or position.distance_squared_to(origin) > 0.000001)
	z_index = int(position.y)
	scale = Vector2.ONE * depth
	if active:
		sync_lighting(delta, relocated)
		visual.present(gait, _time)
	_last_origin = position

func debug_snapshot() -> Dictionary:
	return {"moving": moving, "speed": current_speed, "current_speed": current_speed,
		"facing": gait.facing, "yaw": gait.yaw, "gait_phase": gait.phase,
		"walk_blend": gait.walk_blend, "left_foot": gait.left_foot, "right_foot": gait.right_foot,
		"left_ground": gait.ground[0], "right_ground": gait.ground[1],
		"left_planted": gait.planted[0], "right_planted": gait.planted[1],
		"total_distance": gait.total_distance, "renderer_kind": "articulated_3d", "lighting": visual.lighting_snapshot()}

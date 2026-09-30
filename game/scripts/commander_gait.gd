extends RefCounted
## Distance-driven articulated gait. Stance anchors use authored camp coordinates.
const ELEVATION := 0.6632251158 # 38 degrees, shared with the avatar camera.
const PIXELS_PER_METRE := 78.0
const STRIDE := 1.06
const STANCE := 0.60
const HIP_WIDTH := 0.105
var yaw := PI
var facing := "north"
var phase := 0.0
var total_distance := 0.0
var walk_blend := 0.0
var left_foot := Vector3(-HIP_WIDTH, 0, 0)
var right_foot := Vector3(HIP_WIDTH, 0, 0)
var ground: Array[Vector2] = [Vector2.ZERO, Vector2.ZERO]
var planted: Array[bool] = [true, true]
var _anchors: Array[Vector2] = [Vector2.ZERO, Vector2.ZERO]
var _swing_starts: Array[Vector2] = [Vector2.ZERO, Vector2.ZERO]
var _initialized := false
var turn_lean := 0.0
var _idle_left := Vector3.ZERO
var _idle_right := Vector3.ZERO
var _settling := false

static func ground_delta(screen_delta: Vector2, depth: float) -> Vector2:
	return Vector2(screen_delta.x, screen_delta.y / sin(ELEVATION)) / (PIXELS_PER_METRE * depth)

func project_foot(foot: Vector3, origin: Vector2, depth: float) -> Vector2:
	var rotated := Basis(Vector3.UP, yaw) * foot
	return origin + Vector2(rotated.x, rotated.z * sin(ELEVATION)) * PIXELS_PER_METRE * depth

func _local_foot(at: Vector2, height: float, origin: Vector2, depth: float) -> Vector3:
	var relative := ground_delta(at - origin, depth)
	return Basis(Vector3.UP, -yaw) * Vector3(relative.x, height, relative.y)

func reset_grounding(origin: Vector2, depth: float) -> void:
	walk_blend = 0.0
	left_foot = Vector3(-HIP_WIDTH, 0, 0)
	right_foot = Vector3(HIP_WIDTH, 0, 0)
	for index in 2:
		ground[index] = project_foot(left_foot if index == 0 else right_foot, origin, depth)
		_anchors[index] = ground[index]
		_swing_starts[index] = ground[index]
		planted[index] = true
	_initialized = true
	_settling = false

func update(delta: float, displacement: Vector2, origin: Vector2, depth: float, moving: bool) -> void:
	if not _initialized:
		reset_grounding(origin - displacement, depth)
	var metric := ground_delta(displacement, depth)
	var distance := metric.length()
	var was_walking := walk_blend > 0.001
	if moving and distance > 0.00001:
		if _settling:
			for index in 2:
				_anchors[index] = ground[index]
				_swing_starts[index] = ground[index]
			_settling = false
		var desired := atan2(metric.x, metric.y)
		var error := angle_difference(yaw, desired)
		if absf(error) > deg_to_rad(3.0):
			var turn := clampf(error, -5.0 * delta, 5.0 * delta)
			yaw = wrapf(yaw + turn, -PI, PI)
			turn_lean = lerpf(turn_lean, clampf(-turn / maxf(delta, 0.001) * 0.025, -0.10, 0.10), 1.0 - exp(-9.0 * delta))
		else:
			turn_lean = lerpf(turn_lean, 0.0, 1.0 - exp(-9.0 * delta))
		_update_facing()
		phase += distance / STRIDE
		total_distance += distance
		walk_blend = move_toward(walk_blend, 1.0, delta * 5.0)
		for index in 2:
			var p := fposmod(phase + float(index) * 0.5, 1.0)
			var stance_now := p < STANCE
			var neutral := Vector3(-HIP_WIDTH if index == 0 else HIP_WIDTH, 0, 0)
			var target := project_foot(neutral + Vector3(0, 0, STRIDE * STANCE * 0.5), origin, depth)
			var lift := 0.0
			if stance_now:
				if not planted[index]:
					_anchors[index] = ground[index]
				ground[index] = _anchors[index]
			else:
				if planted[index]:
					_swing_starts[index] = ground[index]
				var swing := (p - STANCE) / (1.0 - STANCE)
				ground[index] = _swing_starts[index].lerp(target, smoothstep(0.0, 1.0, swing))
				lift = sin(swing * PI) * 0.12
			planted[index] = stance_now
			var foot := _local_foot(ground[index], lift, origin, depth)
			# Release unreachable anchors on a near U-turn, rather than stretching legs.
			if Vector2(foot.x - neutral.x, foot.z).length() > 0.52:
				foot = neutral + Vector3(clampf(foot.x - neutral.x, -0.20, 0.20), lift, clampf(foot.z, -0.39, 0.39))
				ground[index] = project_foot(foot, origin, depth)
				_anchors[index] = ground[index]
			if index == 0:
				left_foot = foot
			else:
				right_foot = foot
	else:
		if was_walking and not _settling:
			_idle_left = left_foot
			_idle_right = right_foot
			_settling = true
		walk_blend = move_toward(walk_blend, 0.0, delta * 5.5)
		turn_lean = lerpf(turn_lean, 0.0, 1.0 - exp(-10.0 * delta))
		var blend := smoothstep(0.0, 1.0, 1.0 - walk_blend)
		left_foot = _idle_left.lerp(Vector3(-HIP_WIDTH, 0, 0), blend) if _settling else Vector3(-HIP_WIDTH, 0, 0)
		right_foot = _idle_right.lerp(Vector3(HIP_WIDTH, 0, 0), blend) if _settling else Vector3(HIP_WIDTH, 0, 0)
		for index in 2:
			ground[index] = project_foot(left_foot if index == 0 else right_foot, origin, depth)
			_anchors[index] = ground[index]
			planted[index] = walk_blend < 0.001

func _update_facing() -> void:
	var angles := {"south": 0.0, "east": PI * 0.5, "north": PI, "west": -PI * 0.5}
	# Named states have hysteresis; the rendered body rotates continuously.
	if absf(angle_difference(float(angles[facing]), yaw)) < deg_to_rad(57.0):
		return
	var closest := PI
	for direction: String in angles:
		var error := absf(angle_difference(float(angles[direction]), yaw))
		if error < closest:
			closest = error
			facing = direction

extends Node3D
## Authored, articulated commander. Local +Z is forward; sole targets use Y=0.
## Navigation, heading and gait timing belong to the avatar, not this model.

var left_foot_world := Vector3.ZERO
var right_foot_world := Vector3.ZERO
var _torso: Node3D
var _head: Node3D
var _legs: Array[Dictionary] = []
var _arms: Array[Dictionary] = []
var _tabs: Array[Node3D] = []
var _cape: MeshInstance3D
var _cape_border: MeshInstance3D
var _cloth: Material
var _linen: Material
var _skin: Material
var _bronze: Material
var _leather: Material
var _dark: Material
var _hair: Material
var _seam: Material
var _built := false
var _last_pose := {}

func _ready() -> void:
	build()
	apply_pose(Vector3(-0.105, 0, 0), Vector3(0.105, 0, 0), 0, 0, 0, 0)

func build() -> void:
	if _built:
		return
	_built = true
	_cloth = _fabric(Color("772d24"), 0.97, 15.0, 0.34)
	_linen = _fabric(Color("b6a68a"), 0.96, 47.0, 0.24)
	_skin = _fabric(Color("a77b59"), 0.88, 31.0, 0.09)
	_bronze = _material(Color("746246"), 0.65, 0.48)
	_leather = _material(Color("37281c"), 0.93)
	_dark = _material(Color("261d15"), 0.94)
	_hair = _material(Color("2c2119"), 0.98)
	_seam = _material(Color("746348"), 0.96)
	_torso = Node3D.new()
	_torso.name = "TailoredCuirass"
	add_child(_torso)
	# Slightly flattened, fitted oval armour, flared at chest rather than a capsule.
	_lathe(_torso, "LinenCuirass", [Vector3(0.138, 0.94, 0.095), Vector3(0.139, 1.04, 0.092), Vector3(0.135, 1.12, 0.091), Vector3(0.156, 1.245, 0.110), Vector3(0.185, 1.350, 0.116), Vector3(0.174, 1.405, 0.092), Vector3(0.111, 1.445, 0.060)], _linen, 40)
	_lathe(_torso, "LeatherWaist", [Vector3(0.146, 1.01, 0.102), Vector3(0.147, 1.055, 0.105)], _leather, 40)
	_lathe(_torso, "BeltEdgeLower", [Vector3(0.149, 1.011, 0.106), Vector3(0.149, 1.017, 0.106)], _bronze, 40)
	_lathe(_torso, "BeltEdgeUpper", [Vector3(0.15, 1.048, 0.107), Vector3(0.15, 1.054, 0.107)], _bronze, 40)
	_sphere(_torso, "Buckle", Vector3(0, 1.032, 0.112), Vector3(0.027, 0.018, 0.007), _bronze)
	# A hem of overlapping linen/leather pteruges keeps a tailored silhouette.
	_lathe(_torso, "PleatedUndertunic", [Vector3(0.138, 0.755, 0.113), Vector3(0.174, 0.785, 0.122), Vector3(0.163, 0.93, 0.111), Vector3(0.138, 1.02, 0.096)], _linen, 48, 0.007)
	for i in 18:
		var angle := TAU * float(i) / 18.0
		var tab := Node3D.new()
		tab.position = Vector3(sin(angle) * 0.141, 1.009, cos(angle) * 0.105)
		tab.rotation.y = angle
		_torso.add_child(tab)
		_tabs.append(tab)
		_panel(tab, "LinenLappet", PackedVector3Array([Vector3(-0.023, 0, 0.002), Vector3(0.023, 0, 0.002), Vector3(0.028, -0.195 - 0.013 * sin(angle * 3), 0.032), Vector3(-0.028, -0.195 - 0.013 * sin(angle * 3), 0.032)]), _linen)
		_box(tab, "LappetLeather", Vector3(0, -0.088, 0.015), Vector3(0.012, 0.17, 0.004), _leather)
		_box(tab, "HemFitting", Vector3(0, -0.182 - 0.013 * sin(angle * 3), 0.034), Vector3(0.03, 0.019, 0.004), _bronze)
	# Long narrow seams and the overlapped front plate give the light armour scale.
	for sx in [-1.0, 1.0]:
		_segment(_torso, "CuirassStitch", Vector3(sx * 0.094, 1.075, 0.074), Vector3(sx * 0.131, 1.350, 0.091), 0.0035, _seam)
		_panel(_torso, "LinenShoulderYoke", PackedVector3Array([Vector3(sx * 0.089, 1.444, 0.036), Vector3(sx * 0.144, 1.432, 0.040), Vector3(sx * 0.128, 1.260, 0.098), Vector3(sx * 0.076, 1.260, 0.114)]), _linen)
		_sphere(_torso, "YokeRivet", Vector3(sx * 0.104, 1.272, 0.111), Vector3(0.007, 0.007, 0.004), _bronze)
		_segment(_torso, "CollarBinding", Vector3(sx * 0.062, 1.438, 0.03), Vector3(sx * 0.103, 1.404, 0.07), 0.006, _seam)
	_sphere(_torso, "Neck", Vector3(0, 1.478, 0.004), Vector3(0.052, 0.082, 0.05), _skin)
	_build_head()
	_build_sword()
	for side in [-1.0, 1.0]:
		_legs.append(_build_leg(side))
		_arms.append(_build_arm(side))
	_cape = MeshInstance3D.new()
	_cape.name = "FoldedCrimsonWool"
	_cape.material_override = _heraldic_wool()
	add_child(_cape)
	_cape_border = MeshInstance3D.new()
	_cape_border.name = "CapeWovenBorder"
	_cape_border.material_override = _seam
	add_child(_cape_border)
	# Clasp and a sagging shoulder fold visibly join cape and armour.
	_sphere(_torso, "CapeClasp", Vector3(-0.161, 1.421, 0.077), Vector3(0.027, 0.027, 0.009), _bronze)
	_build_shoulder_drape()
	# Slightly proud overlapping panel and diagonal suspension leather break up the chest.
	_segment(_torso, "CuirassOverlap", Vector3(-0.028, 1.066, 0.103), Vector3(-0.026, 1.302, 0.122), 0.0023, _seam)
	_segment(_torso, "SwordSuspension", Vector3(0.178, 1.08, 0.053), Vector3(0.021, 1.20, 0.121), 0.009, _leather)
	_sphere(_torso, "SuspensionBuckle", Vector3(0.108, 1.133, 0.092), Vector3(0.017, 0.012, 0.004), _bronze)

func _build_head() -> void:
	_head = Node3D.new()
	_head.name = "HeadAndCurlyHair"
	_head.position = Vector3(0, 1.514, 0.006)
	_torso.add_child(_head)
	_lathe(_head, "Face", [Vector3(0.041, 0.00, 0.043), Vector3(0.068, 0.042, 0.066), Vector3(0.080, 0.105, 0.073), Vector3(0.081, 0.155, 0.069), Vector3(0.069, 0.210, 0.060), Vector3(0.034, 0.238, 0.035)], _skin, 32)
	_sphere(_head, "Nose", Vector3(0, 0.109, 0.076), Vector3(0.011, 0.025, 0.019), _skin)
	_sphere(_head, "NoseTip", Vector3(0, 0.087, 0.091), Vector3(0.014, 0.009, 0.009), _skin)
	for side in [-1.0, 1.0]:
		_sphere(_head, "Ear", Vector3(side * 0.080, 0.107, -0.003), Vector3(0.013, 0.025, 0.019), _skin)
		_sphere(_head, "Brow", Vector3(side * 0.034, 0.135, 0.066), Vector3(0.019, 0.0038, 0.004), _hair)
		_sphere(_head, "EyeShadow", Vector3(side * 0.033, 0.121, 0.070), Vector3(0.009, 0.0028, 0.002), _dark)
		_sphere(_head, "Cheek", Vector3(side * 0.046, 0.086, 0.054), Vector3(0.029, 0.022, 0.018), _skin)
	_sphere(_head, "ShortBeard", Vector3(0, 0.033, 0.051), Vector3(0.044, 0.020, 0.021), _hair)
	_sphere(_head, "LowerLip", Vector3(0, 0.055, 0.078), Vector3(0.018, 0.0035, 0.004), _skin)
	_sphere(_head, "HairUnderlayer", Vector3(0, 0.175, -0.016), Vector3(0.080, 0.070, 0.069), _hair)
	# Seeded ring curls: compact sculpted masses rather than individual flying strands.
	for row in 6:
		var elev := lerpf(-0.14, 1.36, float(row) / 5.0)
		var count := maxi(6, int(19.0 * cos(elev)))
		for i in count:
			var a := TAU * (float(i) + float(row % 2) * 0.5) / float(count) + sin(float(i * 13 + row * 23)) * 0.08
			if row < 2 and cos(a) > 0.30:
				continue
			var p := Vector3(sin(a) * cos(elev) * 0.083, 0.140 + sin(elev) * 0.114, cos(a) * cos(elev) * 0.072 - 0.008)
			p.y += sin(float(i * 17 + row * 11)) * 0.009
			var size := 0.0155 + 0.004 * sin(float(i * 7 + row * 3))
			_sphere(_head, "Curl", p, Vector3(size, size * 0.87, size), _hair, 10)

func _build_sword() -> void:
	var sword := Node3D.new()
	sword.name = "ShortSwordAndLeatherScabbard"
	sword.position = Vector3(0.185, 1.002, -0.033)
	sword.rotation.z = 0.12
	sword.rotation.x = -0.16
	_torso.add_child(sword)
	_lathe(sword, "Scabbard", [Vector3(0.006, -0.414, 0.007), Vector3(0.025, -0.386, 0.014), Vector3(0.031, -0.014, 0.018), Vector3(0.03, 0, 0.018)], _leather, 16)
	_lathe(sword, "ScabbardThroat", [Vector3(0.032, -0.026, 0.019), Vector3(0.032, -0.003, 0.019)], _bronze, 16)
	_lathe(sword, "Chape", [Vector3(0.008, -0.42, 0.009), Vector3(0.022, -0.396, 0.014), Vector3(0.024, -0.375, 0.016)], _bronze, 16)
	_box(sword, "Guard", Vector3(0, 0.016, 0), Vector3(0.090, 0.015, 0.031), _bronze)
	_lathe(sword, "Grip", [Vector3(0.013, 0.023, 0.013), Vector3(0.012, 0.107, 0.012)], _leather, 16)
	_sphere(sword, "Pommel", Vector3(0, 0.116, 0), Vector3(0.02, 0.013, 0.02), _bronze)

func _build_leg(side: float) -> Dictionary:
	var upper := Node3D.new()
	upper.name = "LeftThigh" if side < 0 else "RightThigh"
	add_child(upper)
	_lathe(upper, "Thigh", [Vector3(0.046, 0, 0.048), Vector3(0.067, 0.20, 0.061), Vector3(0.076, 0.38, 0.067), Vector3(0.068, 0.44, 0.059)], _skin, 24)
	var lower := Node3D.new()
	lower.name = "Calf"
	add_child(lower)
	_lathe(lower, "Shin", [Vector3(0.028, 0, 0.031), Vector3(0.032, 0.07, 0.036), Vector3(0.048, 0.22, 0.045), Vector3(0.052, 0.30, 0.044), Vector3(0.046, 0.43, 0.045)], _skin, 24)
	var knee := _sphere(self, "Knee", Vector3.ZERO, Vector3(0.047, 0.046, 0.046), _skin)
	var foot := Node3D.new()
	foot.name = "Sandal"
	add_child(foot)
	_sphere(foot, "Foot", Vector3(0, 0.043, 0.042), Vector3(0.041, 0.033, 0.100), _skin)
	_sphere(foot, "LeatherSole", Vector3(0, 0.017, 0.044), Vector3(0.045, 0.016, 0.113), _leather)
	for z in [-0.002, 0.046, 0.095]:
		var strap := _box(foot, "InstepStrap", Vector3(0, 0.068, z), Vector3(0.077, 0.012, 0.015), _leather)
		strap.rotation.x = -0.14
	for h in [0.098, 0.138, 0.181]:
		_lathe(lower, "AnkleLacing", [Vector3(0.034 + h * 0.03, h - 0.073, 0.038), Vector3(0.034 + h * 0.03, h - 0.061, 0.038)], _leather, 24)
	_sphere(foot, "SandalBuckle", Vector3(side * 0.036, 0.077, 0.014), Vector3(0.006, 0.009, 0.01), _bronze)
	return {"upper":upper, "lower":lower, "knee":knee, "foot":foot, "side":side}

func _build_arm(side: float) -> Dictionary:
	var shoulder := Node3D.new()
	shoulder.name = "LeftArm" if side < 0 else "RightArm"
	_torso.add_child(shoulder)
	_sphere(shoulder, "Deltoid", Vector3.ZERO, Vector3(0.056, 0.065, 0.058), _skin)
	_build_epaulette(shoulder, side)
	for i in 5:
		var a := lerpf(-1.1, 1.1, float(i) / 4.0)
		var strip := _box(shoulder, "ShoulderFringe", Vector3(side * cos(a) * 0.054, -0.033, sin(a) * 0.055), Vector3(0.022, 0.082, 0.009), _linen)
		strip.rotation.x = -a * 0.12
	var upper := Node3D.new()
	shoulder.add_child(upper)
	_lathe(upper, "UpperArm", [Vector3(0.035, 0, 0.036), Vector3(0.047, 0.14, 0.044), Vector3(0.056, 0.265, 0.052)], _skin, 24)
	var lower := Node3D.new()
	shoulder.add_child(lower)
	_lathe(lower, "Forearm", [Vector3(0.026, 0, 0.026), Vector3(0.030, 0.07, 0.031), Vector3(0.041, 0.185, 0.038), Vector3(0.036, 0.235, 0.035)], _skin, 24)
	_lathe(lower, "LeatherWristWrap", [Vector3(0.029, 0.015, 0.030), Vector3(0.033, 0.10, 0.035)], _leather, 24)
	_lathe(lower, "WristBronzeBand", [Vector3(0.031, 0.02, 0.032), Vector3(0.031, 0.032, 0.032)], _bronze, 24)
	var hand := _sphere(shoulder, "RelaxedHand", Vector3.ZERO, Vector3(0.032, 0.052, 0.025), _skin)
	var thumb := _sphere(hand, "Thumb", Vector3(-side * 0.75, 0.1, 0.25), Vector3(0.29, 0.70, 0.44), _skin)
	# Hand is a scaled mesh; thumb inherits scale deliberately to retain human proportions.
	thumb.rotation.z = side * 0.30
	return {"shoulder":shoulder, "upper":upper, "lower":lower, "hand":hand, "side":side}

func _build_epaulette(parent: Node3D, side: float) -> void:
	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for row in 9:
		var v := float(row) / 8.0
		for col in 13:
			var u := float(col) / 12.0
			var z := (u - 0.5) * 0.123
			var cross_shape := sqrt(maxf(0.13, 1.0 - pow(z / 0.071, 2)))
			vertices.append(Vector3(side * sin(v * 1.72) * 0.066 * cross_shape, cos(v * 1.72) * 0.072 * cross_shape, z))
			uvs.append(Vector2(u, v))
	for row in 8:
		for col in 12:
			var a := row * 13 + col
			if side < 0:
				indices.append_array(PackedInt32Array([a, a + 1, a + 13, a + 1, a + 14, a + 13]))
			else:
				indices.append_array(PackedInt32Array([a, a + 13, a + 1, a + 1, a + 13, a + 14]))
	var plate := MeshInstance3D.new()
	plate.name = "FittedBronzeEpaulette"
	plate.mesh = _mesh(vertices, uvs, indices)
	plate.material_override = _bronze
	parent.add_child(plate)
	for u in [-0.75, 0.75]:
		var z: float = u * 0.0615
		for j in 4:
			var v := float(j) / 3.0
			_sphere(parent, "ShoulderRivet", Vector3(side * sin(v * 1.64) * 0.054, cos(v * 1.64) * 0.059, z), Vector3(0.0035, 0.0035, 0.0035), _seam, 8)

func _build_shoulder_drape() -> void:
	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for row in 9:
		var v := float(row) / 8.0
		for col in 25:
			var u := float(col) / 24.0
			var x := lerpf(-0.173, 0.159, u)
			var y := 1.436 + sin(u * PI) * 0.038 - v * 0.035 + sin(v * TAU * 2.0 + u * 4.0) * 0.005
			var z := lerpf(0.047 * (1.0 - u), -0.161, v)
			vertices.append(Vector3(x, y, z))
			uvs.append(Vector2(u, v))
	for row in 8:
		for col in 24:
			var a := row * 25 + col
			indices.append_array(PackedInt32Array([a, a + 25, a + 1, a + 1, a + 25, a + 26]))
	var drape := MeshInstance3D.new()
	drape.name = "AsymmetricGatheredShoulderDrape"
	drape.mesh = _mesh(vertices, uvs, indices)
	drape.material_override = _cloth
	_torso.add_child(drape)

## phase is a complete gait cycle in radians (0..TAU), not normalized cycles.
func apply_pose(left_foot: Vector3, right_foot: Vector3, phase: float, walk_blend: float, turn_lean: float, time: float) -> void:
	if not _built:
		build()
	var blend := clampf(walk_blend, 0, 1)
	var bob := -0.009 * cos(phase * 2) * blend + sin(time * 1.7) * 0.0015 * (1.0 - blend)
	# Lower the pelvis at a long double-support stance, rather than stretching a
	# shin or pulling a planted sandal away from its navigation foot target.
	for target in [left_foot, right_foot]:
		var reach_height: float = target.y + 0.086 + sqrt(maxf(0.01, 0.867 * 0.867 - pow(target.z - 0.008, 2)))
		bob = minf(bob, reach_height - 0.93)
	_torso.position.y = bob
	_torso.rotation.z = -sin(phase) * 0.021 * blend + clampf(turn_lean, -1, 1) * 0.018
	_torso.rotation.y = sin(phase) * 0.026 * blend
	_head.rotation.y = -_torso.rotation.y * 0.65
	for i in 2:
		var leg := _legs[i]
		var target := left_foot if i == 0 else right_foot
		var hip := Vector3(float(leg.side) * 0.105, 0.93 + bob, 0)
		var ankle := target + Vector3(0, 0.086, -0.008)
		var joint := _solve_knee(hip, ankle, 0.44, 0.43)
		_fit_segment(leg.upper, joint, hip, 0.44)
		_fit_segment(leg.lower, ankle, joint, 0.43)
		leg.knee.position = joint
		leg.foot.position = target
		# Lifted toes flex gently; a grounded sole never rotates through the floor.
		leg.foot.rotation.x = -minf(target.y * 1.15, 0.12)
		var arm := _arms[i]
		var side := float(arm.side)
		var swing := -clampf(target.z / 0.32, -1.0, 1.0) * blend
		arm.shoulder.position = Vector3(side * 0.188, 1.370, 0)
		var elbow := Vector3(side * 0.026, -0.254 + absf(swing) * 0.021, swing * 0.092)
		var wrist := elbow + Vector3(side * 0.012, -0.217, 0.052 + swing * 0.070)
		_fit_segment(arm.upper, elbow, Vector3.ZERO, 0.265)
		_fit_segment(arm.lower, wrist, elbow, 0.235)
		arm.hand.position = wrist + Vector3(0, -0.039, 0.01)
		arm.hand.rotation.x = swing * 0.10
	for i in _tabs.size():
		var a := TAU * float(i) / float(_tabs.size())
		_tabs[i].rotation.x = cos(a) * (0.04 + absf(sin(phase + sin(a))) * 0.08 * blend)
		_tabs[i].rotation.z = sin(a) * sin(phase) * 0.03 * blend
	_update_cape(phase, blend, turn_lean, time, bob)
	left_foot_world = global_transform * left_foot if is_inside_tree() else left_foot
	right_foot_world = global_transform * right_foot if is_inside_tree() else right_foot
	_last_pose = {"left_sole":left_foot, "right_sole":right_foot, "phase":phase, "walk_blend":blend, "height":1.78, "forward":Vector3.FORWARD * -1}

func get_pose_state() -> Dictionary:
	return _last_pose.duplicate()

func _solve_knee(hip: Vector3, ankle: Vector3, upper_length: float, lower_length: float) -> Vector3:
	var delta := ankle - hip
	var d := clampf(delta.length(), 0.02, upper_length + lower_length - 0.001)
	var axis := delta.normalized()
	var along := (upper_length * upper_length - lower_length * lower_length + d * d) / (2 * d)
	var knee_forward := Vector3(0, 0, 1) - axis * axis.dot(Vector3(0, 0, 1))
	return hip + axis * along + knee_forward.normalized() * sqrt(maxf(0, upper_length * upper_length - along * along))

func _update_cape(phase: float, blend: float, lean: float, time: float, bob: float) -> void:
	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	const COLS := 36
	const ROWS := 28
	for row in ROWS + 1:
		var v := float(row) / ROWS
		for col in COLS + 1:
			var u := float(col) / COLS
			var x := (u - 0.5) * lerpf(0.33, 0.47, sin(v * PI * 0.54)) - 0.027 * v
			var fold := (sin(u * TAU * 3.3 + v * 2.1) * 0.032 + sin(u * TAU * 6.1 - v * 1.7) * 0.008) * (0.55 + v * 0.65)
			var sway := sin(phase - v * 1.7) * 0.027 * blend * v * v + sin(time * 1.4 + v * 3.0) * 0.003 * v
			var hem := 0.515 + 0.16 * u + sin(u * PI * 2.6) * 0.023
			var y := lerpf(1.427 + sin(u * PI) * 0.008, hem, v) + bob + sin(u * PI) * -0.020 + sin(u * 10.0) * 0.012 * v * v
			# Back arch clears armour/legs, opening smoothly behind a lifted heel.
			var z := -0.143 - sin(v * PI * 0.70) * 0.092 + fold - blend * v * 0.035 + sin(phase * 2.0 - v * 3.0) * 0.016 * blend * v
			vertices.append(Vector3(x + sway - lean * v * 0.024, y, z))
			uvs.append(Vector2(u, v))
	for row in ROWS:
		for col in COLS:
			var a := row * (COLS + 1) + col
			indices.append_array(PackedInt32Array([a, a + COLS + 1, a + 1, a + 1, a + COLS + 1, a + COLS + 2]))
	_cape.mesh = _mesh(vertices, uvs, indices)
	# Same deforming surface, narrow binding only; no independent cloth origin.
	var edge_vertices := PackedVector3Array()
	var edge_uvs := PackedVector2Array()
	var edge_indices := PackedInt32Array()
	for row in range(ROWS - 1, ROWS + 1):
		for col in COLS + 1:
			var p := vertices[row * (COLS + 1) + col]
			if row == ROWS - 1:
				p = p.lerp(vertices[ROWS * (COLS + 1) + col], 0.67)
			p.z -= 0.0015
			edge_vertices.append(p)
			edge_uvs.append(Vector2(float(col) / COLS, float(row - ROWS + 1)))
	for col in COLS:
		edge_indices.append_array(PackedInt32Array([col, col + COLS + 1, col + 1, col + 1, col + COLS + 1, col + COLS + 2]))
	_cape_border.mesh = _mesh(edge_vertices, edge_uvs, edge_indices)

func _fit_segment(node: Node3D, start: Vector3, end: Vector3, authored_length: float) -> void:
	var delta := end - start
	var y := delta.normalized()
	var x := Vector3.RIGHT - y * y.dot(Vector3.RIGHT)
	if x.length_squared() < 0.0001:
		x = Vector3.FORWARD - y * y.dot(Vector3.FORWARD)
	x = x.normalized()
	node.transform = Transform3D(Basis(x, y * delta.length() / authored_length, x.cross(y)), start)

func _material(color: Color, roughness: float, metal := 0.0) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	material.metallic = metal
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	return material

func _fabric(color: Color, roughness: float, frequency: float, strength: float) -> ShaderMaterial:
	var shader := Shader.new()
	shader.code = """
shader_type spatial;
render_mode cull_disabled;
uniform vec4 cloth_color : source_color;
uniform float fiber_scale = 30.0;
uniform float variation = 0.1;
uniform float cloth_roughness = 0.95;
varying vec3 local_pos;
float hash(vec3 p){return fract(sin(dot(p,vec3(17.13,57.47,113.71)))*43758.54);}
float noise(vec3 p){vec3 i=floor(p);vec3 f=fract(p); f=f*f*(3.0-2.0*f);return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
void vertex(){local_pos=VERTEX;}
void fragment(){
 vec2 fiber=local_pos.xy*fiber_scale*vec2(31.0,26.0);
 float filter_weight=1.0/(1.0+dot(fwidth(fiber),fwidth(fiber)));
 float weave=sin(fiber.x)*sin(fiber.y)*filter_weight;
 float worn=noise(local_pos*21.0)*0.55+noise(local_pos*67.0)*0.25+noise(local_pos*6.0)*0.2;
 float creases=sin(local_pos.x*97.0+sin(local_pos.y*13.0)*2.0)*0.035;
 ALBEDO=cloth_color.rgb*(1.0+variation*((worn-0.5)*2.1+weave*0.08+creases));
 ROUGHNESS=cloth_roughness;
 SPECULAR=0.15;
}
"""
	var mat := ShaderMaterial.new()
	mat.shader = shader
	mat.set_shader_parameter("cloth_color", color)
	mat.set_shader_parameter("fiber_scale", frequency)
	mat.set_shader_parameter("variation", strength)
	mat.set_shader_parameter("cloth_roughness", roughness)
	return mat

## A readable, subdued woven sun and double hem. Uses the cape's continuous
## deforming UVs, so the embroidery bends with the cloth in every direction.
func _heraldic_wool() -> ShaderMaterial:
	var material := _fabric(Color("772d24"), 0.97, 15.0, 0.34)
	material.shader.code = material.shader.code.replace("ROUGHNESS=cloth_roughness;", """
 vec2 crest=(UV-vec2(0.5,0.38))*vec2(0.48,0.9);
 float radius=length(crest);
 float aa=max(fwidth(radius),0.001);
 float theta=atan(crest.y,crest.x);
 float disc=1.0-smoothstep(0.023-aa,0.023+aa,radius);
 float rays=pow(max(0.0,cos(theta*12.0)),7.0);
 float ray_shape=(1.0-smoothstep(0.049,0.074,radius)) * smoothstep(0.027,0.034,radius) * rays;
 float border=(1.0-smoothstep(0.004,0.008,abs(UV.y-0.941))) * 0.70;
 border=max(border,(1.0-smoothstep(0.003,0.006,abs(UV.y-0.916)))*0.45);
 float embroidery=clamp(max(disc,ray_shape)+border,0.0,1.0);
 ALBEDO=mix(ALBEDO,vec3(0.36,0.24,0.105)*(0.88+0.12*worn),embroidery*0.85);
 ROUGHNESS=cloth_roughness;
 """)
	return material

func _sphere(parent: Node3D, node_name: String, at: Vector3, dimensions: Vector3, material: Material, segments := 20) -> MeshInstance3D:
	var primitive := SphereMesh.new()
	primitive.radius = 1.0
	primitive.height = 2.0
	primitive.radial_segments = segments
	primitive.rings = maxi(6, segments / 2)
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = primitive
	instance.material_override = material
	instance.position = at
	instance.scale = dimensions
	parent.add_child(instance)
	return instance

func _box(parent: Node3D, node_name: String, at: Vector3, dimensions: Vector3, material: Material) -> MeshInstance3D:
	var primitive := BoxMesh.new()
	primitive.size = dimensions
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = primitive
	instance.material_override = material
	instance.position = at
	parent.add_child(instance)
	return instance

func _segment(parent: Node3D, node_name: String, start: Vector3, end: Vector3, radius: float, material: Material) -> void:
	var holder := Node3D.new()
	holder.name = node_name
	parent.add_child(holder)
	_lathe(holder, "Seam", [Vector3(radius, 0, radius), Vector3(radius, start.distance_to(end), radius)], material, 8)
	_fit_segment(holder, start, end, start.distance_to(end))

func _panel(parent: Node3D, node_name: String, points: PackedVector3Array, material: Material) -> void:
	var vertices := points.duplicate()
	for p in points:
		vertices.append(p + Vector3(0, 0, -0.004))
	var indices := PackedInt32Array([0, 1, 2, 0, 2, 3, 6, 5, 4, 7, 6, 4, 0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0])
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = _mesh(vertices, PackedVector2Array([Vector2(0,0), Vector2(1,0), Vector2(1,1), Vector2(0,1), Vector2(0,0), Vector2(1,0), Vector2(1,1), Vector2(0,1)]), indices)
	instance.material_override = material
	parent.add_child(instance)

func _lathe(parent: Node3D, node_name: String, rings: Array, material: Material, sides := 32, pleat := 0.0) -> MeshInstance3D:
	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	for j in rings.size():
		var ring: Vector3 = rings[j]
		for i in sides + 1:
			var angle := TAU * float(i) / float(sides)
			var fold := cos(angle * 12.0) * pleat
			vertices.append(Vector3(sin(angle) * (ring.x + fold), ring.y, cos(angle) * (ring.z + fold)))
			uvs.append(Vector2(float(i) / sides, float(j) / maxf(1, rings.size() - 1)))
	for j in rings.size() - 1:
		for i in sides:
			var a := j * (sides + 1) + i
			indices.append_array(PackedInt32Array([a, a + 1, a + sides + 1, a + 1, a + sides + 2, a + sides + 1]))
	for end in 2:
		var row := 0 if end == 0 else rings.size() - 1
		var center := vertices.size()
		var ring: Vector3 = rings[row]
		vertices.append(Vector3(0, ring.y, 0))
		uvs.append(Vector2(0.5, 0.5))
		for i in sides:
			if end == 0:
				indices.append_array(PackedInt32Array([center, i + 1, i]))
			else:
				indices.append_array(PackedInt32Array([center, row * (sides + 1) + i, row * (sides + 1) + i + 1]))
	for triangle in range(0, indices.size(), 3):
		var first := indices[triangle]
		indices[triangle] = indices[triangle + 2]
		indices[triangle + 2] = first
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = _mesh(vertices, uvs, indices)
	instance.material_override = material
	parent.add_child(instance)
	return instance

func _mesh(vertices: PackedVector3Array, uvs: PackedVector2Array, indices: PackedInt32Array) -> ArrayMesh:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	surface.set_smooth_group(0)
	for i in vertices.size():
		surface.set_uv(uvs[i])
		surface.add_vertex(vertices[i])
	for index in indices:
		surface.add_index(index)
	surface.generate_normals()
	return surface.commit()

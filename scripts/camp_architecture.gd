extends Node3D
## Walkable command pavilion: dimensional fabric, a fitted timber deck and woven rug.
## Visual construction only. CampCollision owns the matching walking surfaces.

const Materials := preload("res://scripts/camp_materials.gd")
const RUG_SHADER: Shader = preload("res://shaders/camp_rug.gdshader")
const FLOOR_HEIGHT: float = 0.0
const ROOF_PEAK: float = 3.95
const EAVE_HEIGHT: float = 3.05
const DECK_WIDTH: float = 8.6
const DECK_REAR: float = -4.3
const DECK_FRONT: float = 2.8
const RAMP_END: float = 3.6
const OUTDOOR_HEIGHT: float = -0.14

var _wood: Material
var _post_wood: Material
var _dark_wood: Material
var _bronze: Material
var _red: Material
var _red_inside: Material
var _lining: Material
var _stitch: Material
var _rope: Material


func _ready() -> void:
	name = "CommandPavilion"
	_wood = Materials.wood(Color("57422f"))
	_post_wood = Materials.wood(Color("584634"), true)
	_dark_wood = Materials.wood(Color("352e26"))
	_bronze = Materials.bronze(Color("82643e"))
	_red = Materials.cloth(Color("692c35"))
	_red_inside = Materials.cloth(Color("7d3641"))
	_lining = Materials.cloth(Color("baa382"))
	_stitch = Materials.cloth(Color("ac8753"))
	_rope = Materials.cloth(Color("8c7655"))
	_build_platform()
	_build_structure()
	_build_canvas()
	_build_rug()


func _instance(node_name: String, mesh: Mesh, at: Vector3, material: Material) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.material_override = material
	instance.position = at
	add_child(instance, true)
	return instance


func _box(node_name: String, at: Vector3, size: Vector3, material: Material) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	return _instance(node_name, mesh, at, material)


func _cylinder(node_name: String, at: Vector3, radius: float, height: float, material: Material) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.bottom_radius = radius
	mesh.top_radius = radius
	mesh.height = height
	mesh.radial_segments = 12
	return _instance(node_name, mesh, at, material)


func _surface() -> SurfaceTool:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	return surface


func _quad(surface: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, reverse: bool = false) -> void:
	var points: Array[Vector3] = [a, b, c, d]
	var uvs: Array[Vector2] = [Vector2.ZERO, Vector2.RIGHT, Vector2.ONE, Vector2.DOWN]
	var order: Array[int] = [0, 1, 2, 0, 2, 3]
	if reverse:
		order = [0, 2, 1, 0, 3, 2]
	for index: int in order:
		surface.set_uv(uvs[index])
		surface.add_vertex(points[index])


func _finish(node_name: String, surface: SurfaceTool, material: Material) -> MeshInstance3D:
	surface.generate_normals()
	surface.index()
	return _instance(node_name, surface.commit(), Vector3.ZERO, material)


func _beam_into(surface: SurfaceTool, start: Vector3, finish: Vector3, radius: float, sides: int = 6) -> void:
	var along := (finish - start).normalized()
	var guide := Vector3.UP if absf(along.y) < 0.9 else Vector3.RIGHT
	var across := along.cross(guide).normalized()
	var second := along.cross(across).normalized()
	for side in sides:
		var a: float = float(side) / float(sides) * TAU
		var b: float = float(side + 1) / float(sides) * TAU
		var da: Vector3 = (across * cos(a) + second * sin(a)) * radius
		var db: Vector3 = (across * cos(b) + second * sin(b)) * radius
		_quad(surface, start + da, finish + da, finish + db, start + db)


func _plank_into(surface: SurfaceTool, center: Vector3, size: Vector3, top_slope: float = 0.0) -> void:
	# Small bevels are geometry, so plank joints survive a grazing first-person view.
	var lo := center - size * 0.5
	var hi := center + size * 0.5
	var bevel: float = minf(0.009, size.z * 0.05)
	var top: Array[Vector3] = [
		Vector3(lo.x + bevel, hi.y, lo.z + bevel), Vector3(hi.x - bevel, hi.y, lo.z + bevel),
		Vector3(hi.x - bevel, hi.y, hi.z - bevel), Vector3(lo.x + bevel, hi.y, hi.z - bevel)
	]
	var rim: Array[Vector3] = [
		Vector3(lo.x, hi.y - bevel, lo.z), Vector3(hi.x, hi.y - bevel, lo.z),
		Vector3(hi.x, hi.y - bevel, hi.z), Vector3(lo.x, hi.y - bevel, hi.z)
	]
	var foot: Array[Vector3] = [
		Vector3(lo.x, lo.y, lo.z), Vector3(hi.x, lo.y, lo.z),
		Vector3(hi.x, lo.y, hi.z), Vector3(lo.x, lo.y, hi.z)
	]
	for index in 4:
		top[index].y += (top[index].z - center.z) * top_slope
		rim[index].y += (rim[index].z - center.z) * top_slope
		foot[index].y += (foot[index].z - center.z) * top_slope
	_quad(surface, top[0], top[1], top[2], top[3])
	_quad(surface, foot[0], foot[3], foot[2], foot[1])
	for index in 4:
		var next: int = (index + 1) % 4
		_quad(surface, top[index], rim[index], rim[next], top[next])
		_quad(surface, rim[index], foot[index], foot[next], rim[next])


func _build_platform() -> void:
	_box("PlatformUnderstructure", Vector3(0, -0.12, -0.75), Vector3(DECK_WIDTH, 0.12, 7.1), _dark_wood)
	var boards: Array[SurfaceTool] = []
	for index in 6:
		boards.append(_surface())
	var fasteners := _surface()
	var row_width: float = (DECK_FRONT - DECK_REAR) / 24.0
	for row in 24:
		var z: float = DECK_REAR + (float(row) + 0.5) * row_width
		var joins: Array[float] = [-4.3, -1.5 + float(row % 3) * 0.49, 1.8 - float(row % 4) * 0.26, 4.3]
		for section in 3:
			var left: float = joins[section] + 0.004
			var right: float = joins[section + 1] - 0.004
			var center := Vector3((left + right) * 0.5, -0.0425, z)
			_plank_into(boards[(row * 3 + section * 7) % 6], center, Vector3(right - left, 0.085, row_width - 0.006))
			for x: float in [left + 0.055, right - 0.055]:
				for dz: float in [-0.075, 0.075]:
					var nail := Vector3(x, 0.001, z + dz)
					_quad(fasteners, nail + Vector3(-0.006, 0, -0.006), nail + Vector3(0.006, 0, -0.006), nail + Vector3(0.006, 0, 0.006), nail + Vector3(-0.006, 0, 0.006))
	# The full-width shallow ramp also serves the outer table aisles.
	var ramp_slope: float = OUTDOOR_HEIGHT / (RAMP_END - DECK_FRONT)
	for row in 4:
		var z: float = DECK_FRONT + (float(row) + 0.5) * 0.2
		var y: float = (z - DECK_FRONT) * ramp_slope
		for section in 3:
			var x: float = -DECK_WIDTH * 0.5 + (float(section) + 0.5) * DECK_WIDTH / 3.0
			_plank_into(boards[(row + section) % 6], Vector3(x, y - 0.04, z), Vector3(DECK_WIDTH / 3.0 - 0.006, 0.08, 0.196), ramp_slope)
	for index in boards.size():
		var color: Color = Color("594431").lerp(Color("775b40"), float(index) / 8.0)
		_finish("PlatformPlankBatch", boards[index], Materials.wood(color))
	_finish("PlatformForgedNails", fasteners, _bronze)
	for x: float in [-4.28, 4.28]:
		_box("PlatformSideFascia", Vector3(x, -0.086, -0.75), Vector3(0.055, 0.17, 7.1), _dark_wood)
	_box("PlatformRearFascia", Vector3(0, -0.086, -4.29), Vector3(8.6, 0.17, 0.055), _dark_wood)


func _build_structure() -> void:
	var timbers := _surface()
	var longitudinal_timbers := _surface()
	var ropes := _surface()
	for x: float in [-4.3, 4.3]:
		for z: float in [-4.1, 2.35]:
			_cylinder("TentPost", Vector3(x, 1.515, z), 0.095, 3.03, _post_wood)
			_cylinder("PostFoot", Vector3(x, 0.14, z), 0.14, 0.28, _bronze)
			_cylinder("PostCap", Vector3(x, 3.07, z), 0.128, 0.11, _bronze)
			_beam_into(ropes, Vector3(x, 2.96, z), Vector3(x * 1.34, OUTDOOR_HEIGHT + 0.06, z + 0.48), 0.018)
			_cylinder("TentPeg", Vector3(x * 1.34, OUTDOOR_HEIGHT + 0.07, z + 0.48), 0.038, 0.27, _dark_wood)
		# Author long rails along local X before turning the mesh, so grain follows wood.
		_beam_into(longitudinal_timbers, Vector3(4.21, 2.99, x), Vector3(-2.51, 2.99, x), 0.066, 10)
	_beam_into(longitudinal_timbers, Vector3(4.35, ROOF_PEAK - 0.045, 0), Vector3(-2.55, ROOF_PEAK - 0.045, 0), 0.075, 10)
	for z: float in [-4.13, -0.89, 2.38]:
		_beam_into(timbers, Vector3(-4.35, EAVE_HEIGHT - 0.04, z), Vector3(0, ROOF_PEAK - 0.045, z), 0.059, 10)
		_beam_into(timbers, Vector3(4.35, EAVE_HEIGHT - 0.04, z), Vector3(0, ROOF_PEAK - 0.045, z), 0.059, 10)
	_finish("PavilionTimberFrame", timbers, _wood)
	var rails := _finish("PavilionLongitudinalTimbers", longitudinal_timbers, _wood)
	rails.rotation.y = PI * 0.5
	_finish("PavilionGuyRopes", ropes, _rope)


func _roof_point(side: float, u: float, z: float) -> Vector3:
	var between_rafters: float = absf(sin((z + 4.13) / 3.24 * PI))
	var transverse_sag: float = sin(u * PI) * (0.19 + between_rafters * 0.055)
	var sewn_fold: float = sin(z * 10.0 + u * 0.8) * 0.017 * sin(u * PI)
	return Vector3(side * u * 4.44, ROOF_PEAK - u * (ROOF_PEAK - EAVE_HEIGHT) - transverse_sag - between_rafters * 0.055 + sewn_fold, z)


func _build_canvas() -> void:
	var seams := _surface()
	for side: float in [-1.0, 1.0]:
		var outside := _surface()
		var inside := _surface()
		for row in 32:
			var z0: float = lerpf(-4.28, 2.56, float(row) / 32.0)
			var z1: float = lerpf(-4.28, 2.56, float(row + 1) / 32.0)
			for column in 24:
				var u0: float = float(column) / 24.0
				var u1: float = float(column + 1) / 24.0
				var a := _roof_point(side, u0, z0)
				var b := _roof_point(side, u1, z0)
				var c := _roof_point(side, u1, z1)
				var d := _roof_point(side, u0, z1)
				_quad(outside, a, b, c, d, side < 0.0)
				var thickness := Vector3(0, -0.018, 0)
				_quad(inside, a + thickness, b + thickness, c + thickness, d + thickness, side > 0.0)
				if row == 0:
					_quad(inside, b, a, a + thickness, b + thickness, side < 0.0)
				if row == 31:
					_quad(inside, d, c, c + thickness, d + thickness, side < 0.0)
				if column == 23:
					_quad(inside, c, b, b + thickness, c + thickness, side < 0.0)
		_finish("SaggingCanvasRoof", outside, _red)
		_finish("CanopyInteriorAndHem", inside, _red_inside)
		for z: float in [-3.69, -2.28, -0.89, 0.48, 1.86]:
			for segment in 20:
				var a := _roof_point(side, float(segment) / 20.0, z) + Vector3.DOWN * 0.024
				var b := _roof_point(side, float(segment + 1) / 20.0, z) + Vector3.DOWN * 0.024
				_beam_into(seams, a, b, 0.007, 5)
	_finish("CanvasRoofSeamBatch", seams, _stitch)
	_wall("RearCanvas", Vector3(0, 1.47, -4.17), Vector2(8.55, 2.92), 0.0, _lining)
	_wall("RearCrimsonBand", Vector3(0, 0.47, -4.055), Vector2(8.55, 0.90), 0.0, _red)
	_rear_gable()
	for side: float in [-1.0, 1.0]:
		_wall("SideCanvas", Vector3(side * 4.23, 1.47, -1.8), Vector2(4.7, 2.92), side * PI * 0.5, _lining)
		_wall("SideCrimsonBand", Vector3(side * 4.10, 0.47, -1.8), Vector2(4.7, 0.90), side * PI * 0.5, _red)
		_eave_lining(side)
		_curtain(side)
	_valance()


func _gable_point(u: float, v: float) -> Vector3:
	var x: float = lerpf(-4.34, 4.34, u)
	var z: float = -4.17 + sin(u * TAU * 12.0) * 0.027 * sin(v * PI)
	var side: float = -1.0 if x < 0.0 else 1.0
	var canopy_height: float = _roof_point(side, absf(x) / 4.44, z).y
	# The bottom laps the rear wall; the top is sewn into the canopy thickness.
	return Vector3(x, lerpf(2.84, canopy_height - 0.003, v), z)


func _rear_gable() -> void:
	var lining := _surface()
	var outside := _surface()
	var hem := _surface()
	var thickness := Vector3(0, 0, -0.022)
	for column in 64:
		for row in 12:
			var a := _gable_point(float(column) / 64.0, float(row) / 12.0)
			var b := _gable_point(float(column + 1) / 64.0, float(row) / 12.0)
			var c := _gable_point(float(column + 1) / 64.0, float(row + 1) / 12.0)
			var d := _gable_point(float(column) / 64.0, float(row + 1) / 12.0)
			_quad(lining, a, d, c, b)
			_quad(outside, a + thickness, b + thickness, c + thickness, d + thickness)
			if row == 0:
				_quad(hem, a, b, b + thickness, a + thickness)
			if row == 11:
				_quad(hem, c, d, d + thickness, c + thickness)
			if column == 0:
				_quad(hem, d, a, a + thickness, d + thickness)
			if column == 63:
				_quad(hem, b, c, c + thickness, b + thickness)
	_finish("RearGableLining", lining, _lining)
	_finish("RearGableOuterCanvas", outside, _red)
	_finish("RearGableBoundEdges", hem, _lining)


func _eave_lining(side: float) -> void:
	var fabric := _surface()
	for column in 48:
		for row in 4:
			var a := _eave_point(side, float(column) / 48.0, float(row) / 4.0)
			var b := _eave_point(side, float(column + 1) / 48.0, float(row) / 4.0)
			var c := _eave_point(side, float(column + 1) / 48.0, float(row + 1) / 4.0)
			var d := _eave_point(side, float(column) / 48.0, float(row + 1) / 4.0)
			_closed_fabric_cell(fabric, a, b, c, d, row == 0, row == 3, column == 0, column == 47)
	var eave := _finish("SideEaveLining", fabric, _lining)
	eave.position = Vector3(side * 4.23, 0.0, -1.8)
	eave.rotation.y = side * PI * 0.5


func _eave_point(side: float, u: float, v: float) -> Vector3:
	var folded := _wall_point(u, lerpf(0.955, 1.0, v), Vector2(4.7, 2.92))
	var world_x: float = 4.23 + folded.z
	var world_z: float = -1.8 - side * folded.x
	var canopy_height: float = _roof_point(side, world_x / 4.44, world_z).y
	return Vector3(folded.x, lerpf(2.82, canopy_height - 0.003, v), folded.z)


func _wall_point(u: float, v: float, size: Vector2) -> Vector3:
	var pleats: float = sin(u * TAU * maxf(2.0, size.x * 1.45) + v * 0.48) * 0.073
	pleats += sin(u * TAU * 3.0) * 0.021
	return Vector3((u - 0.5) * size.x, (v - 0.5) * size.y - sin(u * PI) * v * 0.035, pleats * (0.72 + sin(v * PI) * 0.28))


func _wall(node_name: String, at: Vector3, size: Vector2, yaw: float, material: Material) -> void:
	var fabric := _surface()
	for row in 18:
		for column in 48:
			var a := _wall_point(float(column) / 48.0, float(row) / 18.0, size)
			var b := _wall_point(float(column + 1) / 48.0, float(row) / 18.0, size)
			var c := _wall_point(float(column + 1) / 48.0, float(row + 1) / 18.0, size)
			var d := _wall_point(float(column) / 48.0, float(row + 1) / 18.0, size)
			_closed_fabric_cell(fabric, a, b, c, d, row == 0, row == 17, column == 0, column == 47)
	var panel := _finish(node_name, fabric, material)
	panel.position = at
	panel.rotation.y = yaw


func _closed_fabric_cell(surface: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, bottom: bool, top: bool, left: bool, right: bool) -> void:
	var thickness := Vector3(0, 0, -0.012)
	_quad(surface, a, d, c, b)
	_quad(surface, a + thickness, b + thickness, c + thickness, d + thickness)
	if bottom:
		_quad(surface, a, b, b + thickness, a + thickness)
	if top:
		_quad(surface, c, d, d + thickness, c + thickness)
	if left:
		_quad(surface, d, a, a + thickness, d + thickness)
	if right:
		_quad(surface, b, c, c + thickness, b + thickness)


func _curtain_point(side: float, u: float, v: float) -> Vector3:
	var width: float
	var center: float
	if v < 0.49:
		var t: float = smoothstep(0.0, 0.49, v)
		width = lerpf(0.76, 0.29, t)
		center = lerpf(4.04, 4.14, t)
	else:
		var t: float = pow((v - 0.49) / 0.51, 1.4)
		width = lerpf(0.29, 1.56, t)
		center = lerpf(4.14, 3.69, t)
	var depth: float = sin(u * TAU * 5.0 + v * 1.3) * (0.03 + width * 0.072)
	depth += sin(v * PI) * 0.08
	return Vector3(side * (center - 4.14 + (u - 0.5) * width), v * 3.0 - 1.5, depth)


func _curtain(side: float) -> void:
	var fabric := _surface()
	for row in 32:
		for column in 32:
			var a := _curtain_point(side, float(column) / 32.0, float(row) / 32.0)
			var b := _curtain_point(side, float(column + 1) / 32.0, float(row) / 32.0)
			var c := _curtain_point(side, float(column + 1) / 32.0, float(row + 1) / 32.0)
			var d := _curtain_point(side, float(column) / 32.0, float(row + 1) / 32.0)
			_closed_fabric_cell(fabric, a, b, c, d, row == 0, row == 31, column == 0, column == 31)
	var curtain := _finish("GatheredEntranceCanvas", fabric, _red_inside)
	curtain.position = Vector3(side * 4.14, 1.52, 2.35)
	var edging := _surface()
	for row in 32:
		var a := _curtain_point(side, 0.0, float(row) / 32.0) + curtain.position + Vector3(0, 0, 0.008)
		var b := _curtain_point(side, 0.0, float(row + 1) / 32.0) + curtain.position + Vector3(0, 0, 0.008)
		_beam_into(edging, a, b, 0.014)
	var tie_center := Vector3(side * 4.14, 1.495, 2.42)
	for row in 3:
		for segment in 24:
			var angle: float = float(segment) / 24.0 * TAU
			var next: float = float(segment + 1) / 24.0 * TAU
			var a := tie_center + Vector3(cos(angle) * 0.19, float(row) * 0.018, sin(angle) * 0.125)
			var b := tie_center + Vector3(cos(next) * 0.19, float(row) * 0.018, sin(next) * 0.125)
			_beam_into(edging, a, b, 0.014)
	_beam_into(edging, tie_center + Vector3(-side * 0.17, 0, -0.05), tie_center + Vector3(-side * 0.22, -0.44, -0.02), 0.018)
	_finish("CurtainWovenBinding", edging, _stitch)
	_cylinder("CurtainTassel", tie_center + Vector3(-side * 0.22, -0.49, -0.02), 0.036, 0.12, _stitch)


func _valance_point(u: float, v: float) -> Vector3:
	var x: float = lerpf(-4.39, 4.39, u)
	var top: float = ROOF_PEAK - absf(x) / 4.44 * (ROOF_PEAK - EAVE_HEIGHT) - 0.03
	var scallop: float = sin(fmod(u * 3.0, 1.0) * PI)
	var bottom: float = 2.98 - scallop * 0.14
	var fold: float = sin(u * TAU * 12.0 + v * 0.5) * (0.015 + v * 0.018)
	return Vector3(x, lerpf(bottom, top, v), 2.47 + fold)


func _valance() -> void:
	var fabric := _surface()
	var hem := _surface()
	for column in 72:
		for row in 12:
			var a := _valance_point(float(column) / 72.0, float(row) / 12.0)
			var b := _valance_point(float(column + 1) / 72.0, float(row) / 12.0)
			var c := _valance_point(float(column + 1) / 72.0, float(row + 1) / 12.0)
			var d := _valance_point(float(column) / 72.0, float(row + 1) / 12.0)
			_closed_fabric_cell(fabric, a, b, c, d, row == 0, row == 11, column == 0, column == 71)
		var a := _valance_point(float(column) / 72.0, 0.0)
		var b := _valance_point(float(column + 1) / 72.0, 0.0)
		_beam_into(hem, a + Vector3(0, 0.014, -0.025), b + Vector3(0, 0.014, -0.025), 0.018)
		_beam_into(hem, a + Vector3(0, 0.070, -0.025), b + Vector3(0, 0.070, -0.025), 0.008)
	_finish("EntranceCrimsonValance", fabric, _red)
	_finish("EntranceStitchedHem", hem, _stitch)
	for u: float in [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0]:
		var at := _valance_point(u, 0.0)
		_cylinder("ValanceTassel", at + Vector3(0, -0.065, -0.024), 0.026, 0.14, _stitch)


func _rug_point(u: float, v: float) -> Vector3:
	var x: float = (u - 0.5) * 5.3
	var z: float = (v - 0.5) * 4.36 + 0.08
	var edge: float = minf(minf(u, 1.0 - u), minf(v, 1.0 - v))
	var edge_wave: float = (1.0 - smoothstep(0.0, 0.035, edge)) * (0.005 + sin(x * 8.0 + z * 6.0) * 0.002)
	var corner: float = exp(-Vector2(x + 2.63, z + 2.08).length_squared() * 66.0) * 0.038
	return Vector3(x, 0.018 + sin(x * 1.4) * sin(z * 1.9) * 0.0015 + edge_wave + corner, z)


func _build_rug() -> void:
	var fabric := _surface()
	var back := _surface()
	for row in 40:
		for column in 48:
			var u0: float = float(column) / 48.0
			var u1: float = float(column + 1) / 48.0
			var v0: float = float(row) / 40.0
			var v1: float = float(row + 1) / 40.0
			var points: Array[Vector3] = [_rug_point(u0, v0), _rug_point(u1, v0), _rug_point(u1, v1), _rug_point(u0, v1)]
			var uvs: Array[Vector2] = [Vector2(u0, v0), Vector2(u1, v0), Vector2(u1, v1), Vector2(u0, v1)]
			for index: int in [0, 1, 2, 0, 2, 3]:
				fabric.set_uv(uvs[index])
				fabric.add_vertex(points[index])
			var down := Vector3.DOWN * 0.012
			_quad(back, points[0] + down, points[3] + down, points[2] + down, points[1] + down)
			if row == 0:
				_quad(back, points[0], points[0] + down, points[1] + down, points[1])
			if row == 39:
				_quad(back, points[2], points[2] + down, points[3] + down, points[3])
			if column == 0:
				_quad(back, points[3], points[3] + down, points[0] + down, points[0])
			if column == 47:
				_quad(back, points[1], points[1] + down, points[2] + down, points[2])
	var rug_material := ShaderMaterial.new()
	rug_material.shader = RUG_SHADER
	_finish("CommandWovenRug", fabric, rug_material)
	_finish("RugBoundEdgesAndBack", back, Materials.cloth(Color("572d2e")))
	var fringe := _surface()
	for index in 114:
		var u: float = (float(index) + 0.5) / 114.0
		for v: float in [0.0, 1.0]:
			var at := _rug_point(u, v)
			var sign_z: float = -1.0 if v == 0.0 else 1.0
			var length: float = 0.055 + float((index * 17) % 9) * 0.005
			var finish := at + Vector3(sin(float(index) * 7.2) * 0.016, -0.009, sign_z * length)
			_beam_into(fringe, at, finish, 0.006, 4)
	_finish("RugFrayedFringeBatch", fringe, Materials.cloth(Color("8a7555")))

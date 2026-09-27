extends Node3D
## Asset-free set dressing for the expedition command tent.
## Input and dashboard lifetime are owned by the camp controller.

const SAND := Color("bca477")
const RED := Color("681e25")
const BRONZE := Color("b28b4c")

var _highlight: Node3D
var _lamps: Array[OmniLight3D] = []
var _lamp_energy: Array[float] = []
var _elapsed: float = 0.0
var _wood: StandardMaterial3D
var _wood_dark: StandardMaterial3D
var _bronze: StandardMaterial3D
var _cloth: StandardMaterial3D
var _red: StandardMaterial3D


func _ready() -> void:
	_wood = _material(Color("493322"))
	_wood_dark = _material(Color("251c18"))
	_bronze = _material(BRONZE, 0.65, 0.4)
	_cloth = _material(Color("b7a17a"))
	_red = _material(RED)
	_build_ground()
	_build_tent()
	_build_table()
	_build_map()
	_build_supplies()
	_build_standards()
	_build_lighting()
	_build_camera()
	_build_highlight()


func _process(delta: float) -> void:
	_elapsed += delta
	for index in _lamps.size():
		var phase: float = float(index) * 2.7
		_lamps[index].light_energy = _lamp_energy[index] * (
			1.0 + sin(_elapsed * 1.35 + phase) * 0.025
			+ sin(_elapsed * 2.1 + phase) * 0.012
		)


func set_table_highlight(enabled: bool) -> void:
	if is_instance_valid(_highlight):
		_highlight.visible = enabled


func _material(color: Color, metallic: float = 0.0, roughness: float = 0.85) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.metallic = metallic
	material.roughness = roughness
	return material


func _mesh(node_name: String, mesh: Mesh, at: Vector3, material: Material, parent: Node3D = self) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = at
	instance.material_override = material
	parent.add_child(instance)
	return instance


func _box(node_name: String, at: Vector3, size: Vector3, material: Material, parent: Node3D = self) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	return _mesh(node_name, mesh, at, material, parent)


func _cylinder(node_name: String, at: Vector3, radius: float, height: float, material: Material, top_radius: float = -1.0, parent: Node3D = self) -> MeshInstance3D:
	var mesh := CylinderMesh.new()
	mesh.bottom_radius = radius
	mesh.top_radius = radius if top_radius < 0.0 else top_radius
	mesh.height = height
	mesh.radial_segments = 16
	return _mesh(node_name, mesh, at, material, parent)


func _sphere(node_name: String, at: Vector3, radius: float, material: Material, parent: Node3D = self) -> MeshInstance3D:
	var mesh := SphereMesh.new()
	mesh.radius = radius
	mesh.height = radius * 2.0
	mesh.radial_segments = 12
	mesh.rings = 6
	return _mesh(node_name, mesh, at, material, parent)


func _beam(node_name: String, start: Vector3, finish: Vector3, radius: float, material: Material) -> MeshInstance3D:
	var beam := _cylinder(node_name, (start + finish) * 0.5, radius, start.distance_to(finish), material)
	var direction := (finish - start).normalized()
	var side := Vector3.FORWARD
	if absf(direction.dot(side)) > 0.95:
		side = Vector3.RIGHT
	var across := direction.cross(side).normalized()
	beam.basis = Basis(across, direction, across.cross(direction).normalized())
	return beam


func _build_ground() -> void:
	_box("DesertGround", Vector3(0, -0.17, 0), Vector3(80, 0.3, 80), _material(SAND))
	var pad := _cylinder("CompactedTentGround", Vector3(0, -0.025, -0.6), 7.0, 0.055, _material(Color("a48b64")))
	pad.scale.z = 0.83
	_box("CommandRug", Vector3(0, 0.022, 0.1), Vector3(5.15, 0.025, 4.05), _red)
	var rug_trim := _material(Color("b08a4e"))
	for x: float in [-2.40, 2.40]:
		_box("RugLongBorder", Vector3(x, 0.039, 0.1), Vector3(0.055, 0.008, 3.75), rug_trim)
	for z: float in [-1.73, 1.93]:
		_box("RugShortBorder", Vector3(0, 0.039, z), Vector3(4.83, 0.008, 0.055), rug_trim)
	for index in 21:
		var x: float = -2.35 + float(index) * 0.235
		for z: float in [-1.98, 2.18]:
			_box("RugFringe", Vector3(x, 0.03, z), Vector3(0.025, 0.02, 0.14), rug_trim)
	var stone_material := _material(Color("8d8069"))
	for index in 35:
		var angle: float = float(index) * 2.39996
		var radius: float = 7.8 + float(index % 6) * 1.55
		var stone := _sphere("DesertStone", Vector3(cos(angle) * radius, 0.02, sin(angle) * radius), 0.11 + float(index % 4) * 0.035, stone_material)
		stone.scale = Vector3(1.5, 0.5, 0.85)
	for index in 5:
		var paver := _box("EntranceStone", Vector3(-0.1 + float(index % 2) * 0.15, 0.012, 3.15 + float(index) * 0.78), Vector3(1.12, 0.065, 0.53), _material(Color("a7977d")))
		paver.rotation.y = -0.06 + float(index % 3) * 0.06


func _build_tent() -> void:
	var rope := _material(Color("796241"))
	# The entire front is open. The high pitched canopy stays above the view of the map.
	for x: float in [-4.3, 4.3]:
		for z: float in [-4.1, 2.35]:
			_cylinder("TentPost", Vector3(x, 2.0, z), 0.095, 4.0, _wood)
			_cylinder("PostFoot", Vector3(x, 0.16, z), 0.14, 0.30, _bronze)
			_cylinder("PostCap", Vector3(x, 4.05, z), 0.13, 0.14, _bronze)
			_beam("GuyRope", Vector3(x, 3.75, z), Vector3(x * 1.38, 0.12, z + 0.5), 0.022, rope)
			_cylinder("TentPeg", Vector3(x * 1.38, 0.13, z + 0.5), 0.045, 0.3, _wood_dark)
		_beam("SideRail", Vector3(x, 3.93, -4.2), Vector3(x, 3.93, 2.5), 0.08, _wood)
	_beam("RidgePole", Vector3(0, 5.72, -4.35), Vector3(0, 5.72, 2.55), 0.09, _wood)
	for z: float in [-4.13, 2.38]:
		_beam("RoofRafter", Vector3(-4.35, 3.98, z), Vector3(0, 5.72, z), 0.075, _wood)
		_beam("RoofRafter", Vector3(4.35, 3.98, z), Vector3(0, 5.72, z), 0.075, _wood)
	var roof_angle: float = atan2(1.74, 4.35)
	var roof_width: float = Vector2(4.35, 1.74).length()
	for side: float in [-1.0, 1.0]:
		var roof := _box("CanvasRoof", Vector3(side * 2.175, 4.90, -0.87), Vector3(roof_width + 0.13, 0.07, 6.75), _cloth)
		roof.rotation.z = -side * roof_angle
		var edge := _box("CrimsonCanopyEdge", Vector3(side * 2.175, 4.89, 2.48), Vector3(roof_width + 0.15, 0.19, 0.07), _red)
		edge.rotation.z = -side * roof_angle
		for z: float in [-3.7, -2.35, -1.0, 0.35, 1.7]:
			_beam("CanvasRoofSeam", Vector3(side * 4.32, 4.045, z), Vector3(0, 5.775, z), 0.013, rope)
	_box("RearCanvas", Vector3(0, 1.92, -4.17), Vector3(8.55, 3.8, 0.065), _cloth)
	_box("RearCrimsonBand", Vector3(0, 0.42, -4.12), Vector3(8.55, 0.72, 0.035), _red)
	for x: float in [-3.2, -2.1, -1.0, 0.0, 1.0, 2.1, 3.2]:
		_box("CanvasWallSeam", Vector3(x, 2.05, -4.115), Vector3(0.022, 3.45, 0.012), rope)
	# Short side panels leave the entrance and its right-hand view unobstructed.
	for side: float in [-1.0, 1.0]:
		_box("SideCanvas", Vector3(side * 4.23, 1.78, -2.8), Vector3(0.065, 3.5, 2.7), _cloth)
		_box("SideCrimsonBand", Vector3(side * 4.19, 0.42, -2.8), Vector3(0.045, 0.72, 2.7), _red)
		var curtain := _box("GatheredEntranceCanvas", Vector3(side * 4.02, 2.1, 2.32), Vector3(0.5, 3.6, 0.19), _cloth)
		curtain.rotation.z = -side * 0.045
		_box("CurtainTie", Vector3(side * 4.02, 1.6, 2.42), Vector3(0.52, 0.12, 0.08), _bronze)


func _build_table() -> void:
	for x: float in [-1.46, 1.46]:
		for z: float in [-0.86, 0.86]:
			_box("TableLeg", Vector3(x, 0.60, z), Vector3(0.23, 1.17, 0.23), _wood)
			_box("TableBronzeFoot", Vector3(x, 0.14, z), Vector3(0.26, 0.25, 0.26), _bronze)
		_box("TableTrestle", Vector3(x, 0.38, 0), Vector3(0.20, 0.16, 2.12), _wood_dark)
	_box("TableStretcher", Vector3(0, 0.46, 0), Vector3(3.13, 0.16, 0.18), _wood_dark)
	_box("TableApron", Vector3(0, 1.11, 0), Vector3(3.50, 0.27, 2.2), _wood_dark)
	_box("TableTop", Vector3(0, 1.25, 0), Vector3(3.8, 0.20, 2.5), _wood)
	for x: float in [-1.88, 1.88]:
		_box("TableBronzeRim", Vector3(x, 1.355, 0), Vector3(0.045, 0.035, 2.51), _bronze)
	for z: float in [-1.23, 1.23]:
		_box("TableBronzeRim", Vector3(0, 1.355, z), Vector3(3.76, 0.035, 0.045), _bronze)
	for x: float in [-1.7, 1.7]:
		for z: float in [-1.07, 1.07]:
			_cylinder("TableRivet", Vector3(x, 1.365, z), 0.028, 0.016, _bronze)
	_box("RearBenchSeat", Vector3(0, 0.59, -2.67), Vector3(2.65, 0.16, 0.48), _wood)
	for x: float in [-1.04, 1.04]:
		_box("BenchLeg", Vector3(x, 0.27, -2.67), Vector3(0.17, 0.56, 0.39), _wood_dark)


func _flat_polygon(node_name: String, points: PackedVector2Array, height: float, material: Material) -> void:
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	for point: Vector2 in points:
		vertices.append(Vector3(point.x, height, point.y))
		normals.append(Vector3.UP)
	var indices: PackedInt32Array = Geometry2D.triangulate_polygon(points)
	# Counterclockwise 2D triangles become clockwise from above on the X/Z plane,
	# matching Godot's front-face winding without reversing their indices.
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	_mesh(node_name, mesh, Vector3.ZERO, material)


func _map_line(node_name: String, start: Vector2, finish: Vector2, width: float, material: Material, height: float = 1.390) -> void:
	var delta: Vector2 = finish - start
	var line := _box(node_name, Vector3((start.x + finish.x) * 0.5, height, (start.y + finish.y) * 0.5), Vector3(width, 0.006, delta.length()), material)
	line.rotation.y = atan2(delta.x, delta.y)


func _build_map() -> void:
	var parchment := _material(Color("d4bc84"))
	var sea := _material(Color("5c817c"))
	var land := _material(Color("b29d66"))
	var ink := _material(Color("6d6545"))
	_box("ParchmentMap", Vector3(0, 1.369, 0), Vector3(3.14, 0.023, 1.93), parchment)
	_box("MapSea", Vector3(-0.04, 1.383, -0.02), Vector3(2.88, 0.003, 1.68), sea)
	_flat_polygon("WesternCoast", PackedVector2Array([
		Vector2(-1.48, -0.86), Vector2(-0.45, -0.86), Vector2(-0.31, -0.57),
		Vector2(-0.64, -0.43), Vector2(-0.53, -0.17), Vector2(-0.18, -0.06),
		Vector2(-0.48, 0.16), Vector2(-0.39, 0.40), Vector2(-0.79, 0.35),
		Vector2(-0.90, 0.68), Vector2(-1.15, 0.48), Vector2(-1.48, 0.67)
	]), 1.388, land)
	_flat_polygon("EasternCoast", PackedVector2Array([
		Vector2(-0.04, -0.86), Vector2(1.40, -0.86), Vector2(1.40, 0.83),
		Vector2(0.76, 0.83), Vector2(0.81, 0.59), Vector2(0.52, 0.46),
		Vector2(0.63, 0.22), Vector2(0.30, 0.09), Vector2(0.49, -0.17),
		Vector2(0.12, -0.39), Vector2(0.20, -0.59)
	]), 1.388, land)
	for x: float in [-0.06, 0.19, 0.31, -0.16]:
		var island := _cylinder("MapIsland", Vector3(x, 1.391, 0.15 + x * 1.2), 0.065, 0.006, land)
		island.scale.z = 0.48
	var grid := _material(Color("8f9a7b"))
	for index in range(1, 7):
		var x: float = -1.48 + float(index) * 0.41
		_map_line("MapMeridian", Vector2(x, -0.85), Vector2(x, 0.82), 0.004, grid, 1.397)
	for index in range(1, 4):
		var z: float = -0.85 + float(index) * 0.42
		_map_line("MapLatitude", Vector2(-1.47, z), Vector2(1.40, z), 0.004, grid, 1.397)
	var route: Array[Vector2] = [Vector2(-1.08, -0.51), Vector2(-0.53, -0.65), Vector2(0.20, -0.69), Vector2(0.67, -0.31), Vector2(1.0, 0.19), Vector2(1.08, 0.58)]
	for index in route.size() - 1:
		var start: Vector2 = route[index]
		var finish: Vector2 = route[index + 1]
		for dash in 4:
			_map_line("CampaignRoute", start.lerp(finish, float(dash) / 4.0), start.lerp(finish, (float(dash) + 0.52) / 4.0), 0.018, _red, 1.404)
	for index in route.size():
		var point: Vector2 = route[index]
		_cylinder("ArmyTokenBase", Vector3(point.x, 1.426, point.y), 0.098, 0.04, _bronze)
		_cylinder("ArmyToken", Vector3(point.x, 1.500, point.y), 0.07, 0.11, _red if index < 3 else _wood_dark, 0.044)
		_sphere("ArmyTokenCrest", Vector3(point.x, 1.567, point.y), 0.04, _bronze)
	for at: Vector2 in [Vector2(-1.25, 0.14), Vector2(0.85, -0.57), Vector2(1.22, -0.39)]:
		_cylinder("MapMountain", Vector3(at.x, 1.42, at.y), 0.10, 0.062, ink, 0.0)
	# Rolled parchments and writing tools stay outside the map surface.
	for x: float in [-1.68, 1.68]:
		var scroll := _cylinder("RolledParchment", Vector3(x, 1.43, 0.25), 0.064, 1.40, parchment)
		scroll.rotation.x = PI * 0.5
		var tie := _cylinder("ScrollTie", Vector3(x, 1.43, 0.22), 0.068, 0.09, _red)
		tie.rotation.x = PI * 0.5
	_cylinder("InkPot", Vector3(-1.30, 1.435, 1.09), 0.065, 0.12, _wood_dark)
	_beam("WritingStylus", Vector3(-1.05, 1.38, 1.05), Vector3(-0.55, 1.38, 1.13), 0.015, _bronze)
	_cylinder("WaxSeal", Vector3(1.31, 1.381, 1.04), 0.075, 0.02, _red)


func _crate(at: Vector3, size: Vector3, angle: float) -> void:
	var crate := Node3D.new()
	crate.name = "SupplyCrate"
	crate.position = at
	crate.rotation.y = angle
	add_child(crate)
	_box("CrateBody", Vector3(0, size.y * 0.5, 0), size, _wood, crate)
	for side: float in [-1.0, 1.0]:
		for x: float in [-0.31, 0.31]:
			_box("CrateIronStrap", Vector3(x * size.x, size.y * 0.5, side * (size.z * 0.5 + 0.007)), Vector3(0.06, size.y, 0.025), _bronze, crate)
		_box("CrateTopStrap", Vector3(side * size.x * 0.31, size.y + 0.012, 0), Vector3(0.06, 0.025, size.z), _bronze, crate)
	for index in range(1, 4):
		_box("CratePlankGap", Vector3(0, size.y * float(index) / 4.0, size.z * 0.5 + 0.01), Vector3(size.x, 0.015, 0.013), _wood_dark, crate)


func _build_supplies() -> void:
	_crate(Vector3(-3.12, 0.0, -2.65), Vector3(1.05, 0.74, 0.82), 0.10)
	_crate(Vector3(-3.04, 0.75, -2.69), Vector3(0.84, 0.61, 0.70), -0.05)
	_crate(Vector3(-3.3, 0, -1.45), Vector3(0.86, 0.60, 0.72), -0.13)
	_crate(Vector3(3.22, 0, -2.81), Vector3(1.03, 0.74, 0.81), -0.06)
	_crate(Vector3(3.05, 0, -1.68), Vector3(0.72, 0.53, 0.68), 0.14)
	var pottery := _material(Color("9e6945"))
	for at: Vector3 in [Vector3(-3.63, 0, -0.38), Vector3(3.56, 0, -3.68)]:
		var jar := _sphere("SupplyAmphora", at + Vector3(0, 0.39, 0), 0.28, pottery)
		jar.scale.y = 1.4
		_cylinder("AmphoraNeck", at + Vector3(0, 0.81, 0), 0.105, 0.22, pottery, 0.12)
		_cylinder("AmphoraOpening", at + Vector3(0, 0.925, 0), 0.086, 0.006, _wood_dark)
		for side: float in [-1.0, 1.0]:
			var handle := TorusMesh.new()
			handle.inner_radius = 0.075
			handle.outer_radius = 0.115
			handle.rings = 12
			handle.ring_segments = 8
			var mesh := _mesh("AmphoraHandle", handle, at + Vector3(side * 0.16, 0.72, 0), pottery)
			mesh.rotation.x = PI * 0.5
	for index in 4:
		var x: float = 2.50 + float(index) * 0.17
		_beam("StackedSpear", Vector3(x - 0.17, 0.07, -3.9), Vector3(x + 0.10, 3.30, -3.88), 0.019, _wood)
		_cylinder("SpearHead", Vector3(x + 0.11, 3.45, -3.88), 0.055, 0.30, _bronze, 0.0)
	var shield := _cylinder("RoundShield", Vector3(-2.78, 0.63, -3.90), 0.52, 0.08, _bronze)
	shield.rotation.x = PI * 0.43
	var boss := _sphere("ShieldBoss", Vector3(-2.78, 0.64, -3.82), 0.17, _bronze)
	boss.scale.z = 0.5


func _build_standards() -> void:
	var shader := Shader.new()
	shader.code = """
shader_type spatial;
render_mode cull_disabled;
uniform vec4 cloth_color : source_color = vec4(0.36, 0.055, 0.075, 1.0);
uniform vec4 gold_color : source_color = vec4(0.72, 0.52, 0.24, 1.0);
uniform float phase = 0.0;
void vertex() {
	float free_edge = UV.y * UV.y;
	VERTEX.z += sin(TIME * 1.15 + UV.y * 5.4 + UV.x * 2.8 + phase) * 0.042 * free_edge;
	VERTEX.x += sin(TIME * 0.83 + UV.y * 4.0 + phase) * 0.016 * free_edge;
}
void fragment() {
	vec2 p = (UV - vec2(0.5, 0.46)) * vec2(1.0, 1.85);
	float r = length(p);
	float angle = atan(p.y, p.x);
	float disc = 1.0 - smoothstep(0.081, 0.086, r);
	float rays = (1.0 - step(0.18, abs(sin(angle * 8.0)))) * step(0.105, r) * (1.0 - step(0.285, r));
	float ring = step(0.098, r) * (1.0 - step(0.109, r));
	float edge = step(UV.x, 0.025) + step(0.975, UV.x) + step(UV.y, 0.016) + step(0.974, UV.y);
	float emblem = clamp(disc + rays + ring + edge, 0.0, 1.0);
	ALBEDO = mix(cloth_color.rgb, gold_color.rgb, emblem);
	ROUGHNESS = 0.88;
}
"""
	for side: float in [-1.0, 1.0]:
		var x: float = side * 2.03
		_cylinder("StandardBase", Vector3(x, 0.075, -3.71), 0.28, 0.14, _bronze)
		_cylinder("StandardPole", Vector3(x, 2.19, -3.71), 0.043, 4.26, _wood)
		_sphere("StandardFinial", Vector3(x, 4.38, -3.71), 0.095, _bronze)
		_beam("StandardCrossbar", Vector3(x - 0.61, 4.06, -3.67), Vector3(x + 0.61, 4.06, -3.67), 0.035, _bronze)
		var plane := PlaneMesh.new()
		plane.orientation = PlaneMesh.FACE_Z
		plane.size = Vector2(1.06, 1.97)
		plane.subdivide_width = 8
		plane.subdivide_depth = 16
		var material := ShaderMaterial.new()
		material.shader = shader
		material.set_shader_parameter("phase", side * 1.6)
		_mesh("ExpeditionBanner", plane, Vector3(x, 3.06, -3.61), material)


func _build_lighting() -> void:
	var environment_node := WorldEnvironment.new()
	environment_node.name = "CampAtmosphere"
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color("817565")
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("bcc3c9")
	environment.ambient_light_energy = 0.47
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.ssao_enabled = true
	environment.ssao_radius = 1.3
	environment.ssao_intensity = 1.5
	environment_node.environment = environment
	add_child(environment_node)
	var sun := DirectionalLight3D.new()
	sun.name = "LateAfternoonSun"
	sun.rotation_degrees = Vector3(-47, -32, 0)
	sun.light_color = Color("ffe0a7")
	sun.light_energy = 1.05
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 36.0
	add_child(sun)
	var table_light := OmniLight3D.new()
	table_light.name = "MapWarmFill"
	table_light.position = Vector3(0.1, 3.6, 1.1)
	table_light.light_color = Color("ffdfa6")
	table_light.light_energy = 2.1
	table_light.omni_range = 6.6
	table_light.omni_attenuation = 1.0
	add_child(table_light)
	var ember := _material(Color("ed8633"))
	ember.emission_enabled = true
	ember.emission = Color("ffab46")
	ember.emission_energy_multiplier = 2.5
	for side: float in [-1.0, 1.0]:
		var at := Vector3(side * 3.05, 0, 0.60)
		_cylinder("BrazierFoot", at + Vector3(0, 0.07, 0), 0.29, 0.14, _bronze)
		_cylinder("BrazierStem", at + Vector3(0, 0.65, 0), 0.061, 1.2, _bronze)
		_cylinder("BrazierBowl", at + Vector3(0, 1.27, 0), 0.15, 0.25, _bronze, 0.32)
		_cylinder("BrazierCoals", at + Vector3(0, 1.397, 0), 0.27, 0.025, _wood_dark)
		for index in 7:
			var angle: float = float(index) * 2.39996
			var coal := _sphere("GlowingCoal", at + Vector3(cos(angle) * 0.15, 1.421, sin(angle) * 0.15), 0.063, ember)
			coal.scale.y = 0.55
		var light := OmniLight3D.new()
		light.name = "BrazierGlow"
		light.position = at + Vector3(0, 1.67, 0)
		light.light_color = Color("ffbd74")
		light.light_energy = 2.3
		light.omni_range = 4.5
		light.omni_attenuation = 1.6
		add_child(light)
		_lamps.append(light)
		_lamp_energy.append(light.light_energy)


func _build_camera() -> void:
	var camera := Camera3D.new()
	camera.name = "CampCamera"
	camera.position = Vector3(6.0, 5.3, 8.8)
	camera.fov = 49.0
	camera.near = 0.1
	camera.far = 100.0
	add_child(camera)
	camera.look_at(Vector3(0, 1.3, -0.5), Vector3.UP)
	camera.current = true


func _build_highlight() -> void:
	_highlight = Node3D.new()
	_highlight.name = "TableHighlight"
	_highlight.visible = false
	add_child(_highlight)
	var material := _material(Color("f7cd79"), 0.3, 0.3)
	material.emission_enabled = true
	material.emission = Color("e9b659")
	material.emission_energy_multiplier = 1.6
	for x: float in [-1.92, 1.92]:
		_box("SelectionEdge", Vector3(x, 1.38, 0), Vector3(0.035, 0.035, 2.56), material, _highlight)
	for z: float in [-1.28, 1.28]:
		_box("SelectionEdge", Vector3(0, 1.38, z), Vector3(3.87, 0.035, 0.035), material, _highlight)

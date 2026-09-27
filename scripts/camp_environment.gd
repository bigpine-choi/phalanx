extends Node3D
## Asset-free set dressing for the expedition command tent.
## Input and dashboard lifetime are owned by the camp controller.

const SAND := Color("bca477")
const RED := Color("681e25")
const BRONZE := Color("b28b4c")
const Materials := preload("res://scripts/camp_materials.gd")
const Backdrop := preload("res://scripts/camp_backdrop.gd")
const Architecture := preload("res://scripts/camp_architecture.gd")
const CommandTable := preload("res://scripts/camp_table.gd")
const Lighting := preload("res://scripts/camp_lighting.gd")

var _highlight: Node3D
var _wood: Material
var _wood_vertical: Material
var _wood_dark: Material
var _bronze: Material
var _cloth: Material
var _red: Material


func _ready() -> void:
	get_viewport().msaa_3d = Viewport.MSAA_4X
	get_viewport().use_taa = true
	_wood = Materials.wood(Color("60452f"))
	_wood_vertical = Materials.wood(Color("59432f"), true)
	_wood_dark = Materials.wood(Color("362b23"))
	_bronze = Materials.bronze(Color("957345"))
	_cloth = Materials.cloth(Color("9e8c6d"))
	_red = Materials.cloth(Color("511d28"))
	_build_ground()
	add_child(Architecture.new())
	add_child(CommandTable.new())
	_build_supplies()
	_build_standards()
	add_child(Lighting.new())
	_build_highlight()
	add_child(Backdrop.new())


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
	parent.add_child(instance, true)
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
	_box("DesertGround", Vector3(0, -0.29, 0), Vector3(220, 0.3, 220), Materials.ground(Color("9b886d")))
	var pad := _cylinder("CompactedTentGround", Vector3(0, -0.16, -0.6), 7.0, 0.055, Materials.ground(Color("87765d")))
	pad.scale.z = 0.83
	var stone_material := _material(Color("8d8069"))
	for index in 35:
		var angle: float = float(index) * 2.39996
		var radius: float = 7.8 + float(index % 6) * 1.55
		var stone := _sphere("DesertStone", Vector3(cos(angle) * radius, -0.115, sin(angle) * radius), 0.11 + float(index % 4) * 0.035, stone_material)
		stone.scale = Vector3(1.5, 0.5, 0.85)
	for index in 5:
		var paver := _box("EntranceStone", Vector3(-0.1 + float(index % 2) * 0.15, -0.135, 3.95 + float(index) * 0.52), Vector3(1.12, 0.065, 0.53), _material(Color("a7977d")))
		paver.rotation.y = -0.06 + float(index % 3) * 0.06


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
		var x: float = side * 3.65
		_cylinder("StandardBase", Vector3(x, 0.075, -3.71), 0.28, 0.14, _bronze)
		_cylinder("StandardPole", Vector3(x, 1.5, -3.71), 0.043, 2.94, _wood)
		_sphere("StandardFinial", Vector3(x, 3.04, -3.71), 0.095, _bronze)
		_beam("StandardCrossbar", Vector3(x - 0.61, 2.86, -3.67), Vector3(x + 0.61, 2.86, -3.67), 0.035, _bronze)
		var plane := PlaneMesh.new()
		plane.orientation = PlaneMesh.FACE_Z
		plane.size = Vector2(0.98, 1.65)
		plane.subdivide_width = 8
		plane.subdivide_depth = 16
		var material := ShaderMaterial.new()
		material.shader = shader
		material.set_shader_parameter("phase", side * 1.6)
		_mesh("ExpeditionBanner", plane, Vector3(x, 2.02, -3.61), material)


func _build_highlight() -> void:
	_highlight = Node3D.new()
	_highlight.name = "TableHighlight"
	_highlight.visible = false
	add_child(_highlight)
	var material := _material(Color("f7cd79"), 0.3, 0.3)
	material.emission_enabled = true
	material.emission = Color("e9b659")
	material.emission_energy_multiplier = 0.55
	for x: float in [-1.92, 1.92]:
		_box("SelectionEdge", Vector3(x, CommandTable.TABLE_TOP + 0.016, 0), Vector3(0.018, 0.018, 2.56), material, _highlight)
	for z: float in [-1.28, 1.28]:
		_box("SelectionEdge", Vector3(0, CommandTable.TABLE_TOP + 0.016, z), Vector3(3.87, 0.018, 0.018), material, _highlight)

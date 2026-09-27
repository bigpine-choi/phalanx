extends Node3D
## Small camp silhouettes beyond the open entrance. No physics or input ownership.

const Materials = preload("res://scripts/camp_materials.gd")

var _canvas: Array[ShaderMaterial] = []
var _timber: StandardMaterial3D
var _red: ShaderMaterial
var _rope: StandardMaterial3D
var _opening: StandardMaterial3D


func _ready() -> void:
	name = "ExpeditionBackdrop"
	_timber = _material(Color("514332"))
	_red = Materials.cloth(Color("623038"))
	_rope = _material(Color("8a775d"))
	_opening = _material(Color("3d3534"))
	for tint: String in ["ae9a78", "98866a", "baa889"]:
		_canvas.append(Materials.cloth(Color(tint)))
	_build_terrain()
	# Leave an irregular open lane between the tent clusters.
	_tent(Vector3(-5.3, 0, 8.4), 0.80, 0.14, 0)
	_tent(Vector3(0.3, 0, 10.5), 0.77, -0.30, 1)
	_tent(Vector3(-9.0, 0, 12.4), 0.83, 0.22, 2)
	_tent(Vector3(-4.0, 0, 15.5), 0.68, -0.18, 1)
	_tent(Vector3(-12.0, 0, 17.7), 0.71, 0.25, 0)
	_tent(Vector3(0.4, 0, 18.1), 0.64, -0.12, 2)
	_flag(Vector3(-6.7, 0, 8.7), 2.60, 0.0)
	_flag(Vector3(-9.8, 0, 14.2), 2.40, 2.0)
	_flag(Vector3(-1.3, 0, 17.8), 2.25, 4.0)


func _material(tint: Color, unshaded: bool = false) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = tint
	material.roughness = 0.98
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	if unshaded:
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	return material


func _mesh(node_name: String, mesh: Mesh, at: Vector3, material: Material, parent: Node3D = self) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = at
	instance.material_override = material
	parent.add_child(instance, true)
	return instance


func _surface(node_name: String, vertices: PackedVector3Array, indices: PackedInt32Array, material: Material, parent: Node3D = self) -> MeshInstance3D:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for vertex: Vector3 in vertices:
		surface.set_uv(Vector2(vertex.x, vertex.z))
		surface.add_vertex(vertex)
	for index: int in indices:
		surface.add_index(index)
	surface.generate_normals()
	return _mesh(node_name, surface.commit(), Vector3.ZERO, material, parent)


func _beam(node_name: String, start: Vector3, finish: Vector3, radius: float, material: Material, parent: Node3D = self) -> void:
	var mesh := CylinderMesh.new()
	mesh.bottom_radius = radius
	mesh.top_radius = radius
	mesh.height = start.distance_to(finish)
	mesh.radial_segments = 6
	var instance := _mesh(node_name, mesh, (start + finish) * 0.5, material, parent)
	var up: Vector3 = (finish - start).normalized()
	var reference: Vector3 = Vector3.RIGHT if absf(up.dot(Vector3.FORWARD)) > 0.95 else Vector3.FORWARD
	var right: Vector3 = up.cross(reference).normalized()
	instance.basis = Basis(right, up, right.cross(up).normalized())


func _build_terrain() -> void:
	var ground := PlaneMesh.new()
	ground.size = Vector2(150, 110)
	_mesh("DistantSand", ground, Vector3(-15, -0.045, 60), Materials.ground(Color("8d7d64")))
	# Overlapping rounded landforms rise smoothly out of the ground. All perimeter
	# vertices are buried below it, so no billboard bases or disconnected bars show.
	for layer in 3:
		var vertices := PackedVector3Array()
		var indices := PackedInt32Array()
		for row in 25:
			var depth_fraction: float = float(row) / 24.0
			for column in 81:
				var x: float = -100.0 + float(column) * 2.5
				var phase: float = x * 0.077 + float(layer) * 1.7
				var ridge_height: float = 2.8 + float(layer) * 1.7 + sin(phase) * 1.35 + sin(phase * 2.2 + 0.6) * 0.62
				var profile: float = pow(maxf(0.0, sin(depth_fraction * PI)), 1.65)
				var edge_falloff: float = smoothstep(0.0, 12.0, 100.0 - absf(x))
				var z: float = 23.0 + float(layer) * 18.0 + depth_fraction * 32.0 + sin(phase * 0.8) * 3.0
				vertices.append(Vector3(x, -0.14 + profile * ridge_height * edge_falloff, z))
				if row > 0 and column > 0:
					var i: int = row * 81 + column
					indices.append_array(PackedInt32Array([i - 82, i - 81, i - 1, i - 81, i, i - 1]))
		var tints: Array[Color] = [Color("6b5c4c"), Color("50565b"), Color("394753")]
		var ridge := _surface("DistantRidge%d" % layer, vertices, indices, _material(tints[layer]))
		ridge.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


func _tent(at: Vector3, size: float, angle: float, tint: int) -> void:
	var tent := Node3D.new()
	tent.name = "CampTent"
	tent.position = at
	tent.scale = Vector3.ONE * size
	tent.rotation.y = angle
	add_child(tent, true)
	# The roof sags between the ridge and staked eaves; a scalloped hem breaks the silhouette.
	for side: float in [-1.0, 1.0]:
		var vertices := PackedVector3Array()
		var indices := PackedInt32Array()
		for row in 9:
			var v: float = float(row) / 8.0
			for column in 9:
				var u: float = float(column) / 8.0
				var y: float = lerpf(2.3, 0.22, u) - sin(u * PI) * 0.26 - sin(v * PI) * 0.10
				y += sin(v * 7.0 * PI + u) * sin(u * PI) * 0.024
				vertices.append(Vector3(side * u * 1.45, y, lerpf(-1.8, 1.8, v)))
				if row > 0 and column > 0:
					var i: int = row * 9 + column
					if side > 0.0:
						indices.append_array(PackedInt32Array([i - 10, i - 9, i - 1, i - 9, i, i - 1]))
					else:
						indices.append_array(PackedInt32Array([i - 10, i - 1, i - 9, i - 9, i - 1, i]))
		_surface("DrapedCanvas", vertices, indices, _canvas[tint], tent)
		for end: float in [-1.8, 1.8]:
			_beam("CrimsonHem", Vector3(0, 2.31, end), Vector3(side * 1.45, 0.21, end), 0.045, _red, tent)
			_beam("GuyLine", Vector3(side * 1.42, 0.24, end), Vector3(side * 1.9, 0.03, end + signf(end) * 0.22), 0.012, _rope, tent)
	# Rear panel and a loosely folded two-piece front curtain.
	for end: float in [1.77]:
		_surface("TentEndCanvas", PackedVector3Array([
			Vector3(-1.4, 0.05, end), Vector3(0, 2.27, end), Vector3(1.4, 0.05, end)
		]), PackedInt32Array([0, 1, 2]), _canvas[tint], tent)
	for side: float in [-1.0, 1.0]:
		var vertices := PackedVector3Array()
		var indices := PackedInt32Array()
		for row in 9:
			var v: float = float(row) / 8.0
			for column in 9:
				var u: float = float(column) / 8.0
				var x: float = side * lerpf(0.38, 1.4, u) * (1.0 - v)
				var z: float = -1.80 + sin(u * 4.0 * PI) * (1.0 - v) * 0.046
				vertices.append(Vector3(x, lerpf(0.045, 2.27, v), z))
				if row > 0 and column > 0:
					var i: int = row * 9 + column
					indices.append_array(PackedInt32Array([i - 10, i - 9, i - 1, i - 9, i, i - 1]))
		_surface("FoldedTentCurtain", vertices, indices, _canvas[tint], tent)
	_surface("TentDoorShadow", PackedVector3Array([
		Vector3(-0.40, 0.03, -1.76), Vector3(0.0, 2.27, -1.76), Vector3(0.40, 0.03, -1.76)
	]), PackedInt32Array([0, 1, 2]), _opening, tent)
	_beam("TentRidge", Vector3(0, 2.32, -1.95), Vector3(0, 2.32, 1.95), 0.028, _timber, tent)
	for end: float in [-1.86, 1.86]:
		_beam("TentPole", Vector3(0, 0, end), Vector3(0, 2.43, end), 0.039, _timber, tent)


func _flag(at: Vector3, height: float, phase: float) -> void:
	_beam("CampFlagPole", at, at + Vector3(0, height, 0), 0.027, _timber)
	var cloth := PlaneMesh.new()
	cloth.orientation = PlaneMesh.FACE_Z
	cloth.size = Vector2(0.63, 0.35)
	cloth.subdivide_width = 6
	cloth.subdivide_depth = 3
	var shader := Shader.new()
	shader.code = """
shader_type spatial;
render_mode cull_disabled;
uniform float phase = 0.0;
void vertex() {
	VERTEX.z += sin(TIME * 1.1 + UV.x * 6.0 + phase) * UV.x * 0.055;
	VERTEX.y -= UV.x * 0.055;
}
void fragment() {
	ALBEDO = mix(vec3(0.28, 0.075, 0.085), vec3(0.55, 0.39, 0.20), step(0.91, UV.y));
	ROUGHNESS = 0.98;
}
"""
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("phase", phase)
	_mesh("CampPennant", cloth, at + Vector3(0.33, height - 0.25, 0), material)

extends Node3D
## Inaccessible expedition camp, river valley and distant ridges. No input or physics.
## Close tents have folded geometry; repeated middle-distance tents share batched meshes.

const Materials = preload("res://scripts/camp_materials.gd")
const PENNANT_SHADER = preload("res://shaders/camp_distant_pennant.gdshader")
const WATER_SHADER = preload("res://shaders/camp_valley_water.gdshader")

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
	# The near camp frames a lane toward the river. Nothing enters the player's
	# x +/-7, z <=6.5 walk area, including the front tent's guy ropes.
	_tent(Vector3(-5.6, -0.08, 9.4), 0.91, 0.20, 0)
	_tent(Vector3(5.8, -0.08, 10.1), 0.86, -0.18, 2)
	_tent(Vector3(-9.1, -0.08, 12.7), 0.92, 0.13, 1)
	_tent(Vector3(9.9, -0.08, 14.0), 0.97, -0.23, 0)
	_tent(Vector3(-3.8, -0.08, 16.4), 0.85, 0.18, 2)
	_tent(Vector3(8.3, -0.08, 19.2), 0.85, -0.21, 1)
	_tent(Vector3(-13.4, -0.08, 18.0), 1.01, 0.22, 0)
	_tent(Vector3(13.1, -0.08, 21.1), 0.95, -0.13, 2)
	_flag(Vector3(-3.45, -0.08, 10.0), 3.7, 0.0)
	_flag(Vector3(4.1, -0.08, 11.4), 3.3, 1.0)
	_flag(Vector3(-10.8, -0.08, 17.0), 3.5, 2.0)
	_flag(Vector3(7.3, -0.08, 19.5), 3.1, 3.0)
	_flag(Vector3(-1.6, -0.08, 22.6), 2.9, 4.0)
	_build_middle_camp()
	_build_valley_trees()


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
	ground.size = Vector2(270, 170)
	_mesh("DistantSand", ground, Vector3(0, -0.16, 87), Materials.ground(Color("817461")))
	_build_river()
	# Seeded, low-frequency erosion replaces periodic absolute-sine saw teeth.
	# Each ridge has a broad shoulder and real slopes on both sides.
	for layer in 3:
		var erosion := FastNoiseLite.new()
		erosion.seed = 1709 + layer * 743
		erosion.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
		erosion.frequency = 0.035
		erosion.fractal_octaves = 3
		erosion.fractal_gain = 0.30
		var vertices := PackedVector3Array()
		var indices := PackedInt32Array()
		for row in 33:
			var depth_fraction: float = float(row) / 32.0
			for column in 225:
				var x: float = -140.0 + float(column) * 1.25
				var mass: float = erosion.get_noise_2d(x, 11.0) * 0.5 + 0.5
				var valley: float = 1.0 - exp(-pow((x - 9.0 - layer * 5.0) / 27.0, 2.0)) * (0.66 if layer == 0 else 0.32)
				var ridge_height: float = (5.0 + float(layer) * 3.8 + mass * (12.0 + layer * 3.0)) * valley
				var crest: float = 0.43 + erosion.get_noise_2d(x * 0.62, 93.0) * 0.13
				var shoulder: float = clampf(1.0 - absf(depth_fraction - crest) / (crest if depth_fraction < crest else 1.0 - crest), 0.0, 1.0)
				var profile: float = smoothstep(0.0, 1.0, shoulder)
				var spur: float = sin(depth_fraction * PI) * erosion.get_noise_2d(x * 1.6, depth_fraction * 55.0) * 1.4
				var edge_falloff: float = smoothstep(0.0, 20.0, 140.0 - absf(x))
				var z: float = 46.0 + float(layer) * 29.0 + depth_fraction * 43.0 + erosion.get_noise_2d(x, 160.0) * 5.0
				vertices.append(Vector3(x, -0.15 + maxf(0.0, profile * ridge_height + spur) * edge_falloff, z))
				if row > 0 and column > 0:
					var i: int = row * 225 + column
					indices.append_array(PackedInt32Array([i - 226, i - 225, i - 1, i - 225, i, i - 1]))
		var tints: Array[Color] = [Color("77796c"), Color("7d8990"), Color("98a4b2")]
		var rock := _material(tints[layer])
		# Distant air adds a small cool floor to shadow colour, confined to the
		# unreachable landscape rather than a scene-wide fog/ambient wash.
		rock.emission_enabled = true
		rock.emission = Color("718191")
		rock.emission_energy_multiplier = 0.06 + float(layer) * 0.045
		var ridge := _surface("DistantRidge%d" % layer, vertices, indices, rock)
		ridge.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


func _river_center(z: float) -> float:
	return sin((z - 24.0) * 0.045) * 6.8 + sin(z * 0.10) * 0.8


func _river_width(z: float) -> float:
	return maxf(0.08, smoothstep(18.0, 25.0, z)) * (2.8 + (z - 18.0) * 0.065 + sin(z * 0.079) * 0.5)


func _build_river() -> void:
	var vertices := PackedVector3Array()
	var indices := PackedInt32Array()
	for row in 49:
		var z: float = 18.0 + float(row) * 1.75
		var center: float = _river_center(z)
		var half_width: float = _river_width(z)
		for column in 9:
			vertices.append(Vector3(center + lerpf(-half_width, half_width, float(column) / 8.0), -0.09, z))
			if row > 0 and column > 0:
				var i: int = row * 9 + column
				indices.append_array(PackedInt32Array([i - 10, i - 9, i - 1, i - 9, i, i - 1]))
	var water := ShaderMaterial.new()
	water.shader = WATER_SHADER
	var river := _surface("ValleyRiver", vertices, indices, water)
	river.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for side: float in [-1.0, 1.0]:
		vertices = PackedVector3Array()
		indices = PackedInt32Array()
		for row in 49:
			var z: float = 18.0 + float(row) * 1.75
			var edge: float = _river_center(z) + _river_width(z) * side
			vertices.append(Vector3(edge, -0.10, z))
			vertices.append(Vector3(edge + side * 0.85, -0.04 + sin(z * 0.29) * 0.025, z))
			vertices.append(Vector3(edge + side * 4.0, -0.135, z))
			if row > 0:
				for column in 2:
					var i: int = row * 3 + column
					if side > 0.0:
						indices.append_array(PackedInt32Array([i - 3, i, i - 2, i - 2, i, i + 1]))
					else:
						indices.append_array(PackedInt32Array([i - 3, i - 2, i, i - 2, i + 1, i]))
		_surface("RiverBank", vertices, indices, Materials.ground(Color("6e705b")))


func _build_middle_camp() -> void:
	# 36 tents, six draw calls for shared canvas and recessed doorway meshes.
	# Their 3D roofs retain depth when the player walks across the entrance.
	var roof := _middle_tent_mesh(false)
	var door := _middle_tent_mesh(true)
	for group in 3:
		var transforms: Array[Transform3D] = []
		for i in 12:
			var side: float = -1.0 if i % 2 == 0 else 1.0
			var row: int = i / 2
			var z: float = 26.0 + float(row) * 4.35 + float(group) * 1.4
			var x: float = _river_center(z) + side * (_river_width(z) + 3.6 + float(group) * 3.7 + sin(float(i * 3 + group)) * 0.65)
			var scale_factor: float = 0.65 + 0.08 * sin(float(i + group * 7))
			var basis_value := Basis(Vector3.UP, -side * 0.12 + sin(float(i * 5)) * 0.10).scaled(Vector3.ONE * scale_factor)
			transforms.append(Transform3D(basis_value, Vector3(x, -0.08, z)))
		_batch("MiddleCampCanvas%d" % group, roof, _canvas[group], transforms)
		_batch("MiddleCampDoorways%d" % group, door, _opening, transforms)


func _middle_tent_mesh(door_only: bool) -> ArrayMesh:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	var faces: Array[PackedVector3Array] = []
	if door_only:
		faces.append(PackedVector3Array([Vector3(-0.28, 0.03, -1.82), Vector3(0, 1.53, -1.82), Vector3(0.28, 0.03, -1.82)]))
	else:
		for side: float in [-1.0, 1.0]:
			var a := Vector3(0, 2.12, -1.8)
			var b := Vector3(side * 1.37, 0.14, -1.8)
			var c := Vector3(side * 1.37, 0.14, 1.8)
			var d := Vector3(0, 2.12, 1.8)
			faces.append(PackedVector3Array([a, b, c]) if side < 0 else PackedVector3Array([a, c, b]))
			faces.append(PackedVector3Array([a, c, d]) if side < 0 else PackedVector3Array([a, d, c]))
		faces.append(PackedVector3Array([Vector3(-1.37, 0.14, -1.8), Vector3(0, 2.12, -1.8), Vector3(1.37, 0.14, -1.8)]))
		faces.append(PackedVector3Array([Vector3(1.37, 0.14, 1.8), Vector3(0, 2.12, 1.8), Vector3(-1.37, 0.14, 1.8)]))
	for face: PackedVector3Array in faces:
		for point: Vector3 in face:
			surface.set_uv(Vector2(point.x, point.z))
			surface.add_vertex(point)
	surface.generate_normals()
	return surface.commit()


func _batch(node_name: String, mesh: Mesh, material: Material, transforms: Array[Transform3D]) -> void:
	var batch := MultiMesh.new()
	batch.transform_format = MultiMesh.TRANSFORM_3D
	batch.mesh = mesh
	batch.instance_count = transforms.size()
	for i in transforms.size():
		batch.set_instance_transform(i, transforms[i])
	var instance := MultiMeshInstance3D.new()
	instance.name = node_name
	instance.multimesh = batch
	instance.material_override = material
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(instance)


func _build_valley_trees() -> void:
	# Slender cypress-like silhouettes provide a scale cue, not an impassable wall.
	var crown := SphereMesh.new()
	crown.radius = 0.48
	crown.height = 3.4
	crown.radial_segments = 7
	crown.rings = 5
	var transforms: Array[Transform3D] = []
	for i in 32:
		var z: float = 32.0 + float(i / 2) * 2.2
		var side: float = -1.0 if i % 2 == 0 else 1.0
		var x: float = _river_center(z) + side * (_river_width(z) + 2.8 + sin(float(i) * 1.9) * 1.4)
		var scale_factor: float = 0.68 + (sin(float(i) * 2.4) * 0.5 + 0.5) * 0.52
		transforms.append(Transform3D(Basis.IDENTITY.scaled(Vector3(0.8, scale_factor, 0.8)), Vector3(x, scale_factor * 1.53 - 0.08, z)))
	_batch("RiverCypressGroves", crown, _material(Color("505746")), transforms)


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
	_merge_tent_geometry(tent)


func _merge_tent_geometry(tent: Node3D) -> void:
	# Retain the real folds/ropes/poles while submitting one surface per material,
	# not a draw call for every narrow hem and guy line in each of eight tents.
	var groups: Dictionary = {}
	for child: Node in tent.get_children():
		if child is MeshInstance3D:
			var instance := child as MeshInstance3D
			var material: Material = instance.material_override
			if not groups.has(material):
				groups[material] = []
			groups[material].append(instance)
	for material: Material in groups:
		var surface := SurfaceTool.new()
		surface.begin(Mesh.PRIMITIVE_TRIANGLES)
		for instance: MeshInstance3D in groups[material]:
			surface.append_from(instance.mesh, 0, instance.transform)
			instance.free()
		_mesh("MergedTentDetail", surface.commit(), Vector3.ZERO, material, tent)


func _flag(at: Vector3, height: float, phase: float) -> void:
	_beam("CampFlagPole", at, at + Vector3(0, height, 0), 0.027, _timber)
	var cloth := PlaneMesh.new()
	cloth.orientation = PlaneMesh.FACE_Z
	cloth.size = Vector2(0.63, 0.35)
	cloth.subdivide_width = 6
	cloth.subdivide_depth = 3
	var material := ShaderMaterial.new()
	material.shader = PENNANT_SHADER
	material.set_shader_parameter("phase", phase)
	_mesh("CampPennant", cloth, at + Vector3(0.33, height - 0.25, 0), material)

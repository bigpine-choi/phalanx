extends Node3D
## Standing-height operations furniture and a physical, hand-drawn campaign map.
## Geometry is deterministic; it has no input, dashboard or collision responsibilities.

const Materials := preload("res://scripts/camp_materials.gd")
const Scroll := preload("res://scripts/camp_scroll.gd")
const TABLE_TOP: float = 0.94
const MAP_HEIGHT: float = TABLE_TOP + 0.009
const PAPER_THICKNESS: float = 0.006

var _wood: Material
var _dark: Material
var _vertical: Material
var _bronze: Material
var _red: Material
var _paper: Material
var _ink_surfaces: Dictionary = {}
var _ink_names: Dictionary = {}


func _ready() -> void:
	name = "OperationsFurniture"
	_wood = Materials.wood(Color("574030"))
	_dark = Materials.wood(Color("453226"))
	_vertical = Materials.wood(Color("4c3929"), true)
	_bronze = Materials.bronze(Color("8e7046"))
	_red = Materials.cloth(Color("591f29"))
	_paper = Materials.parchment(Color("d0bd96"))
	_build_table()
	_build_map()
	_flush_ink()
	_build_writing_tools()


func _mesh(node_name: String, geometry: Mesh, at: Vector3, material: Material) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = geometry
	instance.position = at
	instance.material_override = material
	add_child(instance, true)
	return instance


func _box(node_name: String, at: Vector3, size: Vector3, material: Material) -> MeshInstance3D:
	var geometry := BoxMesh.new()
	geometry.size = size
	return _mesh(node_name, geometry, at, material)


func _cylinder(node_name: String, at: Vector3, radius: float, height: float, material: Material) -> MeshInstance3D:
	var geometry := CylinderMesh.new()
	geometry.bottom_radius = radius
	geometry.top_radius = radius
	geometry.height = height
	geometry.radial_segments = 16
	return _mesh(node_name, geometry, at, material)


func _mat(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.94
	material.metallic_specular = 0.12
	return material


func _triangle(surface: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, normal: Vector3) -> void:
	# Godot's front-face winding is clockwise. Explicit normals keep the closed
	# paper underside and timber bevels lit correctly from every walking angle.
	var points: Array[Vector3] = [a, b, c]
	if (b - a).cross(c - a).dot(normal) > 0.0:
		points = [a, c, b]
	for point: Vector3 in points:
		surface.set_normal(normal)
		surface.set_uv(Vector2(point.x, point.z))
		surface.add_vertex(point)


func _quad(surface: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, normal: Vector3) -> void:
	_triangle(surface, a, b, c, normal)
	_triangle(surface, a, c, d, normal)


func _outline(size: Vector2, corner: float, y: float) -> Array[Vector3]:
	var x: float = size.x * 0.5
	var z: float = size.y * 0.5
	return [Vector3(-x + corner, y, -z), Vector3(x - corner, y, -z),
		Vector3(x, y, -z + corner), Vector3(x, y, z - corner),
		Vector3(x - corner, y, z), Vector3(-x + corner, y, z),
		Vector3(-x, y, z - corner), Vector3(-x, y, -z + corner)]


func _beveled_box(node_name: String, at: Vector3, size: Vector3, bevel: float, material: Material) -> MeshInstance3D:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	var width := Vector2(size.x, size.z)
	var inset := width - Vector2.ONE * bevel * 2.0
	var rings: Array[Array] = [
		_outline(inset, bevel, -size.y * 0.5),
		_outline(width, bevel * 1.4, -size.y * 0.5 + bevel),
		_outline(width, bevel * 1.4, size.y * 0.5 - bevel),
		_outline(inset, bevel, size.y * 0.5)]
	for ring_index in 3:
		for index in 8:
			var next: int = (index + 1) % 8
			var a: Vector3 = rings[ring_index][index]
			var b: Vector3 = rings[ring_index][next]
			var c: Vector3 = rings[ring_index + 1][next]
			var d: Vector3 = rings[ring_index + 1][index]
			var normal: Vector3 = (d - a).cross(b - a).normalized()
			_quad(surface, a, b, c, d, normal)
	for index in 8:
		var next: int = (index + 1) % 8
		_triangle(surface, Vector3(0, size.y * 0.5, 0), rings[3][index], rings[3][next], Vector3.UP)
		_triangle(surface, Vector3(0, -size.y * 0.5, 0), rings[0][index], rings[0][next], Vector3.DOWN)
	return _mesh(node_name, surface.commit(), at, material)


func _build_table() -> void:
	# A broad, chamfered slab gives weight without a deep apron blocking the map.
	_beveled_box("TableTopCore", Vector3(0, TABLE_TOP - 0.075, 0), Vector3(3.8, 0.13, 2.5), 0.024, _dark)
	for index in 7:
		var z: float = -1.205 + (float(index) + 0.5) * 2.41 / 7.0
		var wood: Material = Materials.wood(Color("604734").darkened(float(index % 3) * 0.035))
		_beveled_box("TableTopPlank", Vector3(0, TABLE_TOP - 0.017, z), Vector3(3.72, 0.034, 2.41 / 7.0 - 0.005), 0.005, wood)
	for z: float in [-1.065, 1.065]:
		_beveled_box("TableApron", Vector3(0, 0.735, z), Vector3(3.40, 0.14, 0.12), 0.018, _dark)
		_box("TableApronInlay", Vector3(0, 0.756, z + signf(z) * 0.063), Vector3(3.08, 0.008, 0.006), _wood)
	for x: float in [-1.43, 1.43]:
		_beveled_box("TableTrestleFoot", Vector3(x, 0.105, 0), Vector3(0.38, 0.17, 2.12), 0.032, _dark)
		_beveled_box("TableTrestle", Vector3(x, 0.715, 0), Vector3(0.30, 0.18, 2.17), 0.025, _wood)
		for z: float in [-0.82, 0.82]:
			_beveled_box("TableLeg", Vector3(x, 0.43, z), Vector3(0.24, 0.70, 0.24), 0.030, _vertical)
			_beveled_box("TableBronzeFoot", Vector3(x, 0.18, z), Vector3(0.255, 0.14, 0.255), 0.014, _bronze)
			_beveled_box("TableJoinCollar", Vector3(x, 0.70, z), Vector3(0.31, 0.09, 0.31), 0.012, _wood)
			_box("TableMortisePeg", Vector3(x + signf(x) * 0.144, 0.68, z), Vector3(0.025, 0.07, 0.075), _dark)
		_beveled_box("TableStretcherJoint", Vector3(x, 0.33, 0), Vector3(0.35, 0.25, 0.25), 0.018, _vertical)
	_beveled_box("TableStretcher", Vector3(0, 0.32, 0), Vector3(3.18, 0.18, 0.20), 0.014, _wood)
	# Short corner straps, not a reflective border around the whole map.
	for x: float in [-1.76, 1.76]:
		for z: float in [-1.12, 1.12]:
			_beveled_box("TableCornerPlate", Vector3(x, TABLE_TOP + 0.004, z), Vector3(0.17, 0.009, 0.14), 0.002, _bronze)
			_beveled_box("TableCornerStrap", Vector3(x, TABLE_TOP - 0.068, signf(z) * 1.249), Vector3(0.15, 0.085, 0.010), 0.0015, _bronze)
			for offset: float in [-0.045, 0.045]:
				_cylinder("TableRivet", Vector3(x + offset, TABLE_TOP + 0.011, z), 0.011, 0.007, _bronze)
	# Retain existing bench placement and names: collision discovery uses these.
	_box("SideBenchSeat", Vector3(-3.35, 0.59, -1.25), Vector3(0.48, 0.16, 2.0), _wood)
	for z: float in [-2.0, -0.5]:
		_box("BenchLeg", Vector3(-3.35, 0.27, z), Vector3(0.39, 0.56, 0.17), _dark)


func _paper_height(point: Vector2) -> float:
	# Keep the inked field flat; only the unpainted margin rolls up. Otherwise
	# long coast triangles would cut through the paper or float above the sea.
	var edge_x: float = pow(maxf(0.0, (absf(point.x) - 1.42) / 0.12), 3.0)
	var edge_z: float = pow(maxf(0.0, (absf(point.y) - 0.80) / 0.12), 3.0)
	return MAP_HEIGHT + edge_x * (0.023 + 0.017 * sin(point.y * 6.0 + 0.5)) + edge_z * (0.020 + 0.012 * cos(point.x * 4.2))


func _paper_point(column: int, row: int) -> Vector3:
	var u: float = float(column) / 40.0
	var v: float = float(row) / 24.0
	var x: float = (u - 0.5) * 3.08
	var z: float = (v - 0.5) * 1.84
	# A cut sheet with tiny uneven edges and independently lifted corners.
	x += pow(absf(u - 0.5) * 2.0, 14.0) * (sin(v * 32.0 + 1.0) * 0.009 + sin(v * 77.0) * 0.004)
	z += pow(absf(v - 0.5) * 2.0, 14.0) * (sin(u * 27.0 + 0.6) * 0.008 + sin(u * 69.0) * 0.003)
	return Vector3(x, _paper_height(Vector2(x, z)), z)


func _build_paper() -> void:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in 24:
		for column in 40:
			var a: Vector3 = _paper_point(column, row)
			var b: Vector3 = _paper_point(column + 1, row)
			var c: Vector3 = _paper_point(column + 1, row + 1)
			var d: Vector3 = _paper_point(column, row + 1)
			var normal: Vector3 = (d - a).cross(b - a).normalized()
			_quad(surface, a, b, c, d, normal)
			_quad(surface, a - Vector3.UP * PAPER_THICKNESS, b - Vector3.UP * PAPER_THICKNESS, c - Vector3.UP * PAPER_THICKNESS, d - Vector3.UP * PAPER_THICKNESS, -normal)
	var border: Array[Vector3] = []
	for column in 41:
		border.append(_paper_point(column, 0))
	for row in range(1, 25):
		border.append(_paper_point(40, row))
	for column in range(39, -1, -1):
		border.append(_paper_point(column, 24))
	for row in range(23, 0, -1):
		border.append(_paper_point(0, row))
	for index in border.size():
		var a: Vector3 = border[index]
		var b: Vector3 = border[(index + 1) % border.size()]
		var down: Vector3 = Vector3.DOWN * PAPER_THICKNESS
		var normal: Vector3 = Vector3.UP.cross(b - a).normalized()
		_quad(surface, a, b, b + down, a + down, normal)
	_mesh("ParchmentMap", surface.commit(), Vector3.ZERO, _paper)


func _polygon(node_name: String, points: PackedVector2Array, material: Material, lift: float) -> void:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	var indices: PackedInt32Array = Geometry2D.triangulate_polygon(points)
	for index in range(0, indices.size(), 3):
		var triangle: Array[Vector3] = []
		for vertex in 3:
			var point: Vector2 = points[indices[index + vertex]]
			triangle.append(Vector3(point.x, _paper_height(point) + lift, point.y))
		_triangle(surface, triangle[0], triangle[1], triangle[2], Vector3.UP)
	_mesh(node_name, surface.commit(), Vector3.ZERO, material)


func _line(node_name: String, start: Vector2, finish: Vector2, width: float, material: Material, lift: float = 0.003) -> void:
	# Ink shares a handful of meshes/materials instead of a draw call per dash.
	if not _ink_surfaces.has(material):
		var surface := SurfaceTool.new()
		surface.begin(Mesh.PRIMITIVE_TRIANGLES)
		_ink_surfaces[material] = surface
		_ink_names[material] = node_name
	var delta: Vector2 = (finish - start).normalized()
	var side := Vector2(-delta.y, delta.x) * width * 0.5
	var points: Array[Vector3] = []
	for point: Vector2 in [start + side, finish + side, finish - side, start - side]:
		points.append(Vector3(point.x, _paper_height(point) + lift, point.y))
	_quad(_ink_surfaces[material], points[0], points[1], points[2], points[3], Vector3.UP)


func _flush_ink() -> void:
	for material: Material in _ink_surfaces:
		var surface: SurfaceTool = _ink_surfaces[material]
		_mesh(_ink_names[material], surface.commit(), Vector3.ZERO, material)
	_ink_surfaces.clear()
	_ink_names.clear()


func _coast(points: PackedVector2Array, material: Material) -> void:
	for index in points.size():
		_line("CoastlineInk", points[index], points[(index + 1) % points.size()], 0.0032, material, 0.004)


func _coast_detail(points: PackedVector2Array) -> PackedVector2Array:
	# Round the broad geographic sketch first, then break its coast with unequal
	# coves. This avoids repeating saw teeth and keeps the same campaign layout.
	var rounded: PackedVector2Array = points
	for iteration in 2:
		var next := PackedVector2Array()
		for index in rounded.size():
			var a: Vector2 = rounded[index]
			var b: Vector2 = rounded[(index + 1) % rounded.size()]
			if absf(a.x) > 1.38 and absf(b.x) > 1.38 or absf(a.y) > 0.74 and absf(b.y) > 0.74:
				next.append(a)
			else:
				next.append(a.lerp(b, 0.22))
				next.append(a.lerp(b, 0.78))
		rounded = next
	var detailed := PackedVector2Array()
	for index in rounded.size():
		var a: Vector2 = rounded[index]
		var b: Vector2 = rounded[(index + 1) % rounded.size()]
		var delta: Vector2 = b - a
		var tangent: Vector2 = delta.normalized()
		var normal := Vector2(-tangent.y, tangent.x)
		var segments: int = maxi(1, ceili(delta.length() / 0.024))
		var boundary: bool = absf(a.x) > 1.38 and absf(b.x) > 1.38 or absf(a.y) > 0.74 and absf(b.y) > 0.74
		for segment in segments:
			var t: float = float(segment) / float(segments)
			var point: Vector2 = a.lerp(b, t)
			var seed: float = float(index) * 1.782
			var irregularity: float = sin(t * PI) * (sin(seed + t * 7.0) * 0.003 + sin(seed * 2.7 + t * 4.0) * 0.002)
			if not boundary:
				point += normal * irregularity
			detailed.append(point)
	return detailed


func _ridge_point(start: Vector2, finish: Vector2, width: float, height: float, u: float, v: float) -> Vector3:
	var direction: Vector2 = (finish - start).normalized()
	var across := Vector2(-direction.y, direction.x)
	var taper: float = sin(u * PI)
	var center: Vector2 = start.lerp(finish, u)
	center += across * sin(u * 12.0 + 0.5) * width * 0.32 * taper
	var p: Vector2 = center + across * v * width * (0.28 + taper * 0.72)
	# Overlapping unequal summits form a small relief range, not a straight bar.
	var summits: float = 0.0
	for index in 5:
		var center_u: float = 0.13 + float(index) * 0.175
		var center_v: float = sin(float(index) * 2.31) * 0.29
		var along: float = (u - center_u) / (0.075 + float(index % 2) * 0.032)
		var transverse: float = (v - center_v) / (0.43 + float(index % 3) * 0.09)
		summits += exp(-along * along - transverse * transverse) * (0.55 + float(index % 3) * 0.19)
	var edge_taper: float = pow(maxf(0.0, 1.0 - absf(v)), 0.7)
	var elevation: float = height * minf(summits, 1.15) * taper * edge_taper
	return Vector3(p.x, MAP_HEIGHT + 0.005 + elevation, p.y)


func _ridge(start: Vector2, finish: Vector2, width: float, height: float, material: Material, ink: Material) -> void:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in 30:
		for column in 12:
			var u: float = float(row) / 30.0
			var next_u: float = float(row + 1) / 30.0
			var v: float = -1.0 + float(column) / 6.0
			var next_v: float = -1.0 + float(column + 1) / 6.0
			var a: Vector3 = _ridge_point(start, finish, width, height, u, v)
			var b: Vector3 = _ridge_point(start, finish, width, height, next_u, v)
			var c: Vector3 = _ridge_point(start, finish, width, height, next_u, next_v)
			var d: Vector3 = _ridge_point(start, finish, width, height, u, next_v)
			var normal1: Vector3 = (c - a).cross(b - a).normalized()
			var normal2: Vector3 = (d - a).cross(c - a).normalized()
			if normal1.y < 0.0:
				normal1 = -normal1
			if normal2.y < 0.0:
				normal2 = -normal2
			_triangle(surface, a, b, c, normal1)
			_triangle(surface, a, c, d, normal2)
	surface.generate_normals()
	surface.index()
	_mesh("MapTerrainRidge", surface.commit(), Vector3.ZERO, material)
	# Engraver-like short strokes suggest slopes beyond the physical relief.
	var along: Vector2 = (finish - start).normalized()
	var across := Vector2(-along.y, along.x)
	for index in 16:
		var t: float = 0.09 + float(index) * 0.052
		var center: Vector2 = start.lerp(finish, t)
		var sway: float = sin(t * 12.0 + 0.5) * width * 0.32 * sin(t * PI)
		center += across * sway
		for side: float in [-1.0, 1.0]:
			var near: Vector2 = center + across * side * width * (0.32 + sin(t * PI) * 0.72)
			var far: Vector2 = near + across * side * (0.014 + 0.009 * sin(float(index) * 2.7)) + along * 0.006
			_line("TerrainHachure", near, far, 0.0021, ink, 0.005)


func _map_town(at: Vector2, ink: Material, major: bool = false) -> void:
	var radius: float = 0.018 if major else 0.011
	for index in 12:
		var angle: float = float(index) * TAU / 12.0
		var next_angle: float = float(index + 1) * TAU / 12.0
		_line("MapSettlement", at + Vector2(cos(angle), sin(angle)) * radius, at + Vector2(cos(next_angle), sin(next_angle)) * radius, 0.0025, ink, 0.005)
	if major:
		_line("MapSettlement", at + Vector2(-.004, -.004), at + Vector2(.004, .004), .003, ink, .005)
		_line("MapSettlement", at + Vector2(-.004, .004), at + Vector2(.004, -.004), .003, ink, .005)


func _legion_marker(at: Vector2, color: Material, facing: float) -> void:
	var marker := Node3D.new()
	marker.name = "LegionMarker"
	marker.position = Vector3(at.x, MAP_HEIGHT + 0.010, at.y)
	marker.rotation.y = facing
	add_child(marker, true)
	# Small rectangular formation pieces, rather than generic cone pawns.
	var base := _beveled_box("LegionBase", Vector3(0, 0.014, 0), Vector3(0.18, 0.028, 0.13), 0.007, _bronze)
	base.reparent(marker, false)
	for rank in 2:
		for file in 3:
			var troop := _box("LegionRank", Vector3(-0.049 + float(file) * 0.049, 0.044, -0.028 + float(rank) * 0.047), Vector3(0.032, 0.031, 0.031), color)
			troop.reparent(marker, false)
	var pole := _cylinder("LegionStandardPole", Vector3(0.05, 0.094, 0.014), 0.004, 0.16, _bronze)
	pole.reparent(marker, false)
	var standard := _box("LegionStandard", Vector3(0.024, 0.139, 0.015), Vector3(0.052, 0.041, 0.004), color)
	standard.reparent(marker, false)
	var crest := _cylinder("LegionStandardCrest", Vector3(0.05, 0.183, 0.014), 0.008, 0.010, _bronze)
	crest.reparent(marker, false)


func _build_map() -> void:
	_build_paper()
	var sea: Material = Materials.parchment(Color("6d8583"))
	var land: Material = Materials.parchment(Color("b2a17f"))
	var ink: Material = _mat(Color("5f513a"))
	var pale_ink: Material = _mat(Color("918364"))
	var route_ink: Material = _mat(Color("7e3430"))
	_polygon("MapSea", PackedVector2Array([Vector2(-1.41, -0.77), Vector2(1.40, -0.77), Vector2(1.42, 0.75), Vector2(-1.42, 0.77)]), sea, 0.001)
	# Evokes an eastern Mediterranean campaign chart; not a surveyed historical map.
	var west := PackedVector2Array([Vector2(-1.41,-0.77), Vector2(-0.38,-0.77), Vector2(-0.40,-0.66), Vector2(-0.57,-0.63), Vector2(-0.47,-0.54), Vector2(-0.59,-0.47), Vector2(-0.53,-0.38), Vector2(-0.39,-0.30), Vector2(-0.45,-0.23), Vector2(-0.60,-0.25), Vector2(-0.66,-0.12), Vector2(-0.58,0.00), Vector2(-0.61,0.13), Vector2(-0.73,0.17), Vector2(-0.80,0.10), Vector2(-0.81,0.27), Vector2(-0.96,0.20), Vector2(-0.97,0.03), Vector2(-1.07,0.14), Vector2(-1.14,0.29), Vector2(-1.24,0.36), Vector2(-1.31,0.55), Vector2(-1.42,0.56)])
	var east := PackedVector2Array([Vector2(-0.15,-0.77), Vector2(1.40,-0.77), Vector2(1.42,0.75), Vector2(0.71,0.75), Vector2(0.65,0.64), Vector2(0.78,0.49), Vector2(0.66,0.33), Vector2(0.68,0.16), Vector2(0.53,0.09), Vector2(0.49,-0.05), Vector2(0.31,-0.10), Vector2(0.19,-0.17), Vector2(0.03,-0.15), Vector2(-0.10,-0.21), Vector2(-0.19,-0.36), Vector2(-0.08,-0.40), Vector2(-0.23,-0.50), Vector2(-0.13,-0.58), Vector2(-0.26,-0.68)])
	west = _coast_detail(west)
	east = _coast_detail(east)
	_polygon("WesternCoast", west, land, 0.002)
	_polygon("EasternCoast", east, land, 0.002)
	_coast(west, ink)
	_coast(east, ink)
	for index in 11:
		var x: float = -0.30 + sin(float(index) * 2.39996) * (0.16 + float(index % 3) * 0.077)
		var z: float = 0.15 + cos(float(index) * 2.39996) * (0.13 + float(index % 4) * 0.060)
		var island := _coast_detail(PackedVector2Array([Vector2(x-.035,z-.017), Vector2(x+.011,z-.033), Vector2(x+.044,z+.007), Vector2(x+.003,z+.025)]))
		_polygon("MapIsland", island, land, 0.003)
		_coast(island, pale_ink)
	var southern_island := _coast_detail(PackedVector2Array([Vector2(-.43,.59),Vector2(-.20,.53),Vector2(.13,.57),Vector2(.17,.62),Vector2(-.14,.64)]))
	_polygon("SouthernIsland", southern_island, land, 0.003)
	_coast(southern_island, ink)
	# Relief is deliberately low: coastlines and the route remain the visual priority.
	_ridge(Vector2(-1.26,-0.51), Vector2(-0.96,-0.07), 0.078, 0.066, Materials.parchment(Color("938361")), pale_ink)
	_ridge(Vector2(0.11,-0.58), Vector2(1.12,-0.33), 0.10, 0.090, Materials.parchment(Color("99835f")), pale_ink)
	_ridge(Vector2(0.96,-0.05), Vector2(1.15,0.40), 0.072, 0.067, Materials.parchment(Color("95815e")), pale_ink)
	for at: Vector2 in [Vector2(-.66,-.58),Vector2(-.81,-.10),Vector2(-1.23,.12),Vector2(.07,-.36),Vector2(.32,-.27),Vector2(.64,.06),Vector2(1.02,.23),Vector2(1.29,.55)]:
		_map_town(at, ink, true)
	for at: Vector2 in [Vector2(-1.31,-.60),Vector2(-.85,-.68),Vector2(-1.12,.20),Vector2(.14,-.63),Vector2(.58,-.59),Vector2(.38,-.22),Vector2(1.28,-.19),Vector2(.98,.57)]:
		_map_town(at, pale_ink)
	var river: Array[Vector2] = [Vector2(.78,-.44),Vector2(.73,-.22),Vector2(.86,-.06),Vector2(.82,.17),Vector2(.94,.37),Vector2(.86,.59)]
	for index in river.size() - 1:
		_line("MapRiver", river[index], river[index + 1], 0.008, sea, 0.004)
	var route: Array[Vector2] = [Vector2(-1.07,-.53),Vector2(-.65,-.69),Vector2(-.18,-.68),Vector2(.29,-.36),Vector2(.53,-.17),Vector2(1.04,.24)]
	for index in route.size() - 1:
		for dash in 7:
			var a: Vector2 = route[index].lerp(route[index + 1], float(dash) / 7.0)
			var b: Vector2 = route[index].lerp(route[index + 1], (float(dash) + 0.57) / 7.0)
			_line("CampaignRoute", a, b, 0.012, route_ink, 0.005)
	# A compass rose and restrained ticks replace the old full rectangular grid.
	var compass := Vector2(-1.16, 0.62)
	for index in 8:
		var angle: float = float(index) * TAU / 8.0
		var direction := Vector2(cos(angle), sin(angle))
		_line("CompassRay", compass + direction * .025, compass + direction * (.12 if index % 2 == 0 else .075), .005, pale_ink, .005)
	for index in 13:
		var x: float = -1.20 + float(index) * .20
		_line("MapScaleTick", Vector2(x,-.84), Vector2(x,-.819 if index % 2 == 0 else -.828), .004, pale_ink)
	_legion_marker(Vector2(-.89,-.55), _red, -0.20)
	_legion_marker(Vector2(.31,-.36), _red, 0.37)
	_legion_marker(Vector2(1.08,.35), _dark, -0.35)


func _build_writing_tools() -> void:
	var scroll_mesh := Scroll.create_mesh(1.39)
	for x: float in [-1.66, 1.66]:
		_mesh("RolledParchment", scroll_mesh, Vector3(x, TABLE_TOP + .065, .18), _paper)
		var tie := _cylinder("ScrollTie", Vector3(x, TABLE_TOP + .065, .18), .064, .065, _red)
		tie.rotation.x = PI * .5
		var knot := _beveled_box("ScrollBindingKnot", Vector3(x, TABLE_TOP + .133, .18), Vector3(.068,.018,.055), .005, _red)
		knot.rotation.y = 0.3 * signf(x)
	_cylinder("InkPot", Vector3(-1.31, TABLE_TOP + .064, 1.077), .056, .12, _dark)
	_cylinder("InkPotOpening", Vector3(-1.31, TABLE_TOP + .126, 1.077), .038, .005, _mat(Color("17191a")))
	var stylus := _cylinder("WritingStylus", Vector3(-.78, TABLE_TOP + .012, 1.079), .012, .50, _bronze)
	stylus.rotation = Vector3(PI * .5, 1.40, 0)
	_cylinder("WaxSeal", Vector3(1.25, TABLE_TOP + .011, 1.07), .068, .020, _red)

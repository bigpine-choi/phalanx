extends RefCounted
## A wound sheet with a hollow centre, layered ends and a loose outer lip.
## Local Z is the scroll axis. Both paper faces and all cut edges are geometry.

const THICKNESS := 0.0022
const WINDING_STEPS := 144
const AXIAL_STEPS := 12

static func _point(t: float, v: float, length: float, inside: bool = false) -> Vector3:
	var angle := t * TAU * 2.75 + 0.5
	var radius := 0.022 + t * 0.040 - (THICKNESS if inside else 0.0)
	# The lip relaxes along the length; the two cut ends do not form perfect discs.
	radius += sin(v * 7.0 + t * 3.0) * 0.0018 * t * t
	var cut_edge := pow(absf(v - 0.5) * 2.0, 10.0) * sin(angle * 2.3) * 0.007
	return Vector3(cos(angle) * radius, sin(angle) * radius, (v - 0.5) * length + cut_edge)

static func _quad(surface: SurfaceTool, points: Array[Vector3], normal: Vector3) -> void:
	var order: Array[int] = [0, 1, 2, 0, 2, 3]
	if (points[1] - points[0]).cross(points[2] - points[0]).dot(normal) > 0.0:
		order = [0, 2, 1, 0, 3, 2]
	for index in order:
		surface.set_normal(normal)
		surface.set_uv(Vector2(points[index].x, points[index].z))
		surface.add_vertex(points[index])

static func create_mesh(length: float) -> ArrayMesh:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for winding in WINDING_STEPS:
		var t0 := float(winding) / WINDING_STEPS
		var t1 := float(winding + 1) / WINDING_STEPS
		var angle := (t0 + t1) * 0.5 * TAU * 2.75 + 0.5
		var outward := Vector3(cos(angle), sin(angle), 0)
		for axial in AXIAL_STEPS:
			var v0 := float(axial) / AXIAL_STEPS
			var v1 := float(axial + 1) / AXIAL_STEPS
			var outer: Array[Vector3] = [_point(t0, v0, length), _point(t1, v0, length), _point(t1, v1, length), _point(t0, v1, length)]
			var inner: Array[Vector3] = [_point(t0, v0, length, true), _point(t1, v0, length, true), _point(t1, v1, length, true), _point(t0, v1, length, true)]
			_quad(surface, outer, outward)
			_quad(surface, inner, -outward)
			if axial == 0:
				_quad(surface, [outer[0], inner[0], inner[1], outer[1]], Vector3.FORWARD)
			if axial == AXIAL_STEPS - 1:
				_quad(surface, [outer[3], outer[2], inner[2], inner[3]], Vector3.BACK)
			if winding == 0:
				_quad(surface, [outer[0], outer[3], inner[3], inner[0]], Vector3(sin(angle), -cos(angle), 0))
			if winding == WINDING_STEPS - 1:
				_quad(surface, [outer[1], inner[1], inner[2], outer[2]], Vector3(-sin(angle), cos(angle), 0))
	surface.index()
	return surface.commit()

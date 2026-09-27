extends Node3D
## Simple solid proxies keep movement and sight queries independent of set dressing.

var _built := false


func build(environment: Node3D) -> void:
	if _built:
		return
	_built = true
	_box("Ground", Vector3(0, -0.26, 1.25), Vector3(15.0, 0.24, 14.0))
	_box("TimberPlatform", Vector3(0, -0.075, -0.75), Vector3(8.6, 0.15, 7.1))
	# A shallow full-width ramp connects both aisles to the lower camp terrain.
	var ramp := ConvexPolygonShape3D.new()
	ramp.points = PackedVector3Array([
		Vector3(-4.3, 0, 2.8), Vector3(4.3, 0, 2.8),
		Vector3(-4.3, -0.14, 3.6), Vector3(4.3, -0.14, 3.6),
		Vector3(-4.3, -0.16, 2.8), Vector3(4.3, -0.16, 2.8),
		Vector3(-4.3, -0.16, 3.6), Vector3(4.3, -0.16, 3.6)
	])
	_body("EntranceRamp", Vector3.ZERO, ramp)
	_box("TentRearWall", Vector3(0, 1.95, -4.13), Vector3(8.65, 3.9, 0.32))
	_box("TentSideWallLeft", Vector3(-4.17, 1.8, -1.8), Vector3(0.40, 3.6, 4.7))
	_box("TentSideWallRight", Vector3(4.17, 1.8, -1.8), Vector3(0.40, 3.6, 4.7))
	# A solid table volume prevents walking between legs or clipping into the apron.
	_box("TableSolid", Vector3(0, 0.51, 0), Vector3(3.8, 1.02, 2.5))
	for mesh: MeshInstance3D in environment.find_children("*", "MeshInstance3D", true, false):
		var mesh_name := String(mesh.name)
		if mesh_name.begins_with("TentPost"):
			_cylinder_proxy("TentPostSolid", mesh, 0.15, mesh.mesh.get_aabb().size.y)
		elif mesh_name == "CrateBody":
			_mesh_box("SupplyCrateSolid", mesh)
		elif mesh_name.begins_with("SideBenchSeat"):
			var size: Vector3 = mesh.mesh.get_aabb().size
			_box("BenchSolid", to_local(mesh.global_position) * Vector3(1, 0, 1) + Vector3(0, 0.34, 0), Vector3(size.x, 0.68, size.z))
		elif mesh_name.begins_with("BrazierBowl"):
			var at := to_local(mesh.global_position)
			_cylinder("BrazierSolid", Vector3(at.x, 0.72, at.z), 0.33, 1.44)
		elif mesh_name.begins_with("GatheredEntranceCanvas"):
			var at := to_local(mesh.global_position)
			_box("EntranceCurtainSolid", Vector3(at.x, 1.96, at.z), Vector3(0.62, 3.92, 0.22))
			_box("CurtainSkirtSolid", Vector3(signf(at.x) * 4.06, 0.40, at.z), Vector3(0.83, 0.8, 0.35))
		elif mesh_name.begins_with("SupplyAmphora"):
			var at := to_local(mesh.global_position)
			_cylinder("AmphoraSolid", Vector3(at.x, 0.49, at.z), 0.29, 0.98)
		elif mesh_name.begins_with("StandardPole"):
			_cylinder_proxy("StandardPoleSolid", mesh, 0.10, mesh.mesh.get_aabb().size.y)
	# The current exploration slice ends before the decorative camp tents.
	_box("ExplorationBoundaryLeft", Vector3(-7.0, 2, 0.75), Vector3(0.3, 4, 11.8))
	_box("ExplorationBoundaryRight", Vector3(7.0, 2, 0.75), Vector3(0.3, 4, 11.8))
	_box("ExplorationBoundaryRear", Vector3(0, 2, -5.0), Vector3(14.3, 4, 0.3))
	_box("ExplorationBoundaryFront", Vector3(0, 2, 6.5), Vector3(14.3, 4, 0.3))


func _body(node_name: String, at: Vector3, shape: Shape3D) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = at
	body.collision_layer = 1
	body.collision_mask = 0
	add_child(body, true)
	var collider := CollisionShape3D.new()
	collider.name = "Shape"
	collider.shape = shape
	body.add_child(collider)
	return body


func _box(node_name: String, at: Vector3, size: Vector3) -> StaticBody3D:
	var shape := BoxShape3D.new()
	shape.size = size
	return _body(node_name, at, shape)


func _cylinder(node_name: String, at: Vector3, radius: float, height: float) -> StaticBody3D:
	var shape := CylinderShape3D.new()
	shape.radius = radius
	shape.height = height
	return _body(node_name, at, shape)


func _mesh_box(node_name: String, mesh: MeshInstance3D) -> void:
	var bounds := mesh.mesh.get_aabb()
	var body := _box(node_name, Vector3.ZERO, bounds.size)
	body.global_transform = mesh.global_transform
	body.position += body.basis * bounds.get_center()


func _cylinder_proxy(node_name: String, mesh: MeshInstance3D, radius: float, height: float) -> void:
	var body := _cylinder(node_name, Vector3.ZERO, radius, height)
	body.global_transform = mesh.global_transform

extends SceneTree
## Structural/framing regression checks. Headless checks do not replace visual art QA.

const CampMaterials = preload("res://scripts/camp_materials.gd")

var failures: int = 0

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _settle() -> void:
	await process_frame
	await physics_frame
	await process_frame
	await process_frame

func _check_materials() -> void:
	var materials: Array[ShaderMaterial] = [
		CampMaterials.wood(Color.WHITE), CampMaterials.cloth(Color.WHITE),
		CampMaterials.bronze(Color.WHITE), CampMaterials.parchment(Color.WHITE),
		CampMaterials.ground(Color.WHITE)
	]
	for material: ShaderMaterial in materials:
		check(material != null and material.shader != null, "Procedural material factory must return a usable shader material")
		if material == null or material.shader == null:
			continue
		check(material.shader.resource_path.begins_with("res://shaders/"), "Material shaders must be bundled with the project")
		for uniform: Dictionary in material.shader.get_shader_uniform_list():
			check(uniform.get("type") != TYPE_OBJECT, "Procedural camp materials must not require external textures")

func _check_roofs(environment: Node) -> void:
	var roofs: Array[Node] = environment.find_children("SaggingCanvasRoof*", "MeshInstance3D", false, false)
	check(roofs.size() == 2, "Command tent must retain both sagging canvas roof panels")
	for roof_node: Node in roofs:
		var roof: MeshInstance3D = roof_node as MeshInstance3D
		check(roof.mesh != null and roof.mesh.get_surface_count() > 0, "Canopy must have mesh geometry")
		if roof.mesh == null or roof.mesh.get_surface_count() == 0:
			continue
		var arrays: Array = roof.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		check(vertices.size() > 300, "Canopy must retain enough vertices for a sagging silhouette")
		check(normals.size() == vertices.size(), "Canopy vertices must have normals for lighting")
		var upward: int = 0
		for normal: Vector3 in normals:
			if normal.y > 0.5:
				upward += 1
		check(not normals.is_empty() and float(upward) / float(maxi(1, normals.size())) > 0.95, "Canopy normals must generally face upward")

func _check_framing(camera: Camera3D, window_size: Vector2i) -> void:
	root.size = window_size
	await _settle()
	var screen_min := Vector2(INF, INF)
	var screen_max := Vector2(-INF, -INF)
	for x: float in [-1.9, 1.9]:
		for z: float in [-1.25, 1.25]:
			var corner := Vector3(x, 1.35, z)
			check(not camera.is_position_behind(corner), "All tabletop corners must stay in front of the camera")
			var projected: Vector2 = camera.unproject_position(corner)
			screen_min = screen_min.min(projected)
			screen_max = screen_max.max(projected)
	var width_fraction: float = (screen_max.x - screen_min.x) / float(window_size.x)
	check(width_fraction >= 0.40 and width_fraction <= 0.80, "Table must occupy 40–80%% of viewport width at %s (actual %.1f%%)" % [window_size, width_fraction * 100.0])
	var safe_area := Rect2(Vector2(24, 64), Vector2(window_size.x - 48, window_size.y - 164))
	for height: float in [1.35, 1.389]:
		check(safe_area.has_point(camera.unproject_position(Vector3(0, height, 0))), "Table and map centers must remain clear of viewport edges and bottom HUD at %s" % window_size)
	print("CAMP_FRAMING %s: table width %.1f%%, center %s" % [window_size, width_fraction * 100.0, camera.unproject_position(Vector3(0, 1.35, 0))])

func _run() -> void:
	root.content_scale_factor = 1.0
	_check_materials()
	var packed: PackedScene = load("res://scenes/command_camp.tscn") as PackedScene
	if packed == null:
		check(false, "Camp scene must load")
		_finish()
		return
	var camp: Node = packed.instantiate()
	root.add_child(camp)
	current_scene = camp
	await _settle()
	var environment: Node = camp.get("environment") as Node
	if environment == null:
		check(false, "Camp environment must build successfully")
		_finish()
		return
	_check_roofs(environment)
	var backdrop: Node = environment.get_node_or_null("ExpeditionBackdrop")
	check(backdrop != null, "Open entrance must have an expedition camp backdrop")
	if backdrop != null:
		check(backdrop.find_children("CampTent*", "Node3D", false, false).size() == 6, "Backdrop must include six tents")
		check(backdrop.find_children("CampPennant*", "MeshInstance3D", false, false).size() == 3, "Backdrop must include three pennants")
	var camera: Camera3D = environment.get_node_or_null("CampCamera") as Camera3D
	check(camera != null and camera.current, "Camp must have its fixed active camera")
	if camera != null:
		check(camera.global_position.z < 2.35, "Camera must remain inside the tent entrance")
		check((-camera.global_basis.z).z > 0.0, "Camera must look toward the camp beyond the positive-Z entrance")
		for window_size: Vector2i in [Vector2i(1280, 720), Vector2i(1440, 960)]:
			await _check_framing(camera, window_size)
	camp.queue_free()
	await _settle()
	_finish()

func _finish() -> void:
	print("PHALANX_CAMP_VISUAL_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

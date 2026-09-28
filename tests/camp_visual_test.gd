extends SceneTree
## HISTORICAL: art pass B first-person composition; not validation of the current quarter-view flow.
## Current scene-flow regression: res://tests/quarter_flow_test.gd.
## Structural/framing regression checks. Headless checks do not replace visual art QA.

const CampMaterials = preload("res://scripts/camp_materials.gd")
const CampTable = preload("res://scripts/camp_table.gd")

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
	var roofs: Array[Node] = environment.find_children("SaggingCanvasRoof*", "MeshInstance3D", true, false)
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

func _check_first_person_hud(camp: Node, camera: Camera3D, window_size: Vector2i) -> void:
	root.size = window_size
	await _settle()
	var bounds := Rect2(Vector2.ZERO, Vector2(window_size))
	var hint: Label = camp.get("hover_hint") as Label
	check(hint != null and bounds.encloses(hint.get_global_rect()), "Exploration instructions must fit at %s" % window_size)
	var prompt: Control = camp.get("capture_prompt")
	check(prompt.visible and bounds.encloses(prompt.get_global_rect()), "The sole capture prompt must fit at %s" % window_size)
	check(prompt.get_global_rect().position.y > window_size.y * 0.80, "Capture prompt must leave the map and centre view clear")
	var crosshair: Control = camp.get("crosshair") as Control
	check(crosshair != null, "First-person HUD must have a crosshair")
	if crosshair != null:
		check(bounds.encloses(crosshair.get_global_rect()), "Crosshair must stay in bounds at %s" % window_size)
		check(crosshair.get_global_rect().get_center().distance_to(bounds.get_center()) < 3.0, "Crosshair must be centered at %s" % window_size)
	check(not camera.is_position_behind(Vector3(0, 1.04, 0)), "Initial view must face the operations table")
	check(bounds.has_point(camera.unproject_position(Vector3(0, 1.04, 0))), "Table center must be visible from initial human-eye view at %s" % window_size)
	var near_map := camera.unproject_position(Vector3(0, CampTable.MAP_HEIGHT, -0.80))
	var far_map := camera.unproject_position(Vector3(0, CampTable.MAP_HEIGHT, 0.75))
	check(near_map.y - far_map.y > window_size.y * 0.15, "The readable map field must occupy at least 15% of the view height")
	check(near_map.y < window_size.y * 0.80 and far_map.y > window_size.y * 0.45, "Map must sit in the lower half above the instructions")
	print("CAMP_FIRST_PERSON_HUD %s: eye %s, table center %s" % [window_size, camera.global_position, camera.unproject_position(Vector3(0, 1.04, 0))])

func _check_pass_a_geometry(camp: Node, environment: Node) -> void:
	var furniture := environment.get_node_or_null("OperationsFurniture")
	check(furniture != null, "Map and table must have their own geometry owner")
	if furniture != null:
		var top := furniture.get_node("TableTopPlank") as MeshInstance3D
		var top_y := top.position.y + top.mesh.get_aabb().end.y
		check(absf(top_y - CampTable.TABLE_TOP) < 0.002, "Tabletop must match its standing-height collision volume")
		var paper := furniture.get_node("ParchmentMap") as MeshInstance3D
		var normals: PackedVector3Array = paper.mesh.surface_get_arrays(0)[Mesh.ARRAY_NORMAL]
		var underside := false
		var upper_side := false
		for normal in normals:
			underside = underside or normal.y < -0.5
			upper_side = upper_side or normal.y > 0.5
		check(underside and upper_side and paper.mesh.get_aabb().size.y > 0.006, "Paper must have physical curls, top and backing geometry")
		check(furniture.find_children("LegionMarker*", "Node3D", false, false).size() == 3, "Map must retain three restrained legion markers")
	var pavilion := environment.get_node_or_null("CommandPavilion")
	check(pavilion != null, "Tent and platform must have their own geometry owner")
	if pavilion != null:
		check(pavilion.find_children("CanopyInteriorAndHem*", "MeshInstance3D", false, false).size() == 2, "Both roof panels must have modeled undersides and hems")
	var review := camp.get_node_or_null("ReviewCamera") as Camera3D
	check(review != null and not review.current, "Fixed review camera must leave the player camera active")
	var solid := camp.get_node("CampCollision/TableSolid/Shape") as CollisionShape3D
	check(absf(solid.shape.size.y - CampTable.TABLE_TOP) < 0.002, "Movement proxy must match the new tabletop height")

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
	_check_pass_a_geometry(camp, environment)
	var backdrop: Node = environment.get_node_or_null("ExpeditionBackdrop")
	check(backdrop != null, "Open entrance must have an expedition camp backdrop")
	if backdrop != null:
		check(backdrop.find_children("CampTent*", "Node3D", false, false).size() >= 6, "Backdrop must include nearby camp tents")
		check(backdrop.find_children("CampPennant*", "MeshInstance3D", false, false).size() >= 3, "Backdrop must include multiple pennants")
	var player: Node3D = camp.get("player") as Node3D
	check(player is CharacterBody3D, "Camp must have a first-person character body")
	var camera: Camera3D = player.get("camera") as Camera3D if player != null else null
	check(camera != null and camera.current, "Player must own the active first-person camera")
	if camera != null:
		check(camera.global_position.y >= 1.55 and camera.global_position.y <= 1.9, "Initial camera must be at human eye height")
		check(camera.global_position.z < -1.8 and camera.global_position.z > -4.0, "Initial player must be safely behind the operations table")
		check((-camera.global_basis.z).z > 0.0, "Initial camera must face toward the table and entrance")
		for window_size: Vector2i in [Vector2i(1280, 720), Vector2i(1440, 960)]:
			await _check_first_person_hud(camp, camera, window_size)
	camp.queue_free()
	await _settle()
	_finish()

func _finish() -> void:
	print("PHALANX_CAMP_VISUAL_TEST: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
	quit(0 if failures == 0 else 1)

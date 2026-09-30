extends SceneTree

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE", "1")
	OS.set_environment("PHALANX_RESEARCH_OFFLINE", "1")
	OS.set_environment("PHALANX_WORKSPACE_PATH", OS.get_environment("TEMP").path_join("phalanx-chest-placement-%s.json" % OS.get_process_id()))
	call_deferred("_run")

func _run() -> void:
	var app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	await process_frame
	var camp = app.camp
	var chest = camp.supply_chest
	var navigation = camp.navigation
	var clear := app.headquarters.get_node_or_null("HeadquartersSupplyChest") == null
	clear = clear and chest.get_parent() == camp
	clear = clear and not navigation.is_walkable(chest.position)
	clear = clear and not camp._is_visible_ground(chest.position + Vector2(0, -16))
	var route: PackedVector2Array = navigation.path_to(chest.position + Vector2(0, 95), chest.position - Vector2(0, 95))
	clear = clear and route.size() > 2
	for i in range(route.size() - 1):
		clear = clear and navigation.line_is_clear(route[i], route[i + 1])
	print("CAMP_CHEST_PLACEMENT: %s; route_points=%d; analysis_room_empty=%s" % ["PASS" if clear else "FAIL", route.size(), app.headquarters.get_node_or_null("HeadquartersSupplyChest") == null])
	quit(0 if clear else 1)

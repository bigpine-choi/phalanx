extends Node2D
## Fixed oblique camp stage. All art, hit polygons and paths share authored space.

signal headquarters_requested
signal proximity_changed(near_entrance: bool)

const NavigationScript = preload("res://scripts/camp_navigation.gd")
const AvatarScript = preload("res://scripts/camp_avatar.gd")
const AtmosphereScript = preload("res://scripts/scene_atmosphere.gd")
const ForegroundScript = preload("res://scripts/camp_foreground.gd")
const LightFieldScript = preload("res://scripts/camp_light_field.gd")
const SupplyChestScript = preload("res://scripts/camp_supply_chest.gd")
const BACKGROUND_PATH := "res://assets/art/quarter_camp.png"
const CANVAS_SIZE := Vector2(1600, 900)
const SOURCE_SIZE := Vector2(1672, 941)
const ART_SCALE := 1600.0 / 1672.0
const ART_OFFSET := Vector2(0, (900.0 - 941.0 * ART_SCALE) * 0.5)

var avatar: Node2D
var navigation: RefCounted
var light_field := LightFieldScript.new()
var atmosphere: Node2D
var supply_chest: Node2D
var active := true
var entrance_position := Vector2(683, 386) * ART_SCALE + ART_OFFSET
var spawn_position := Vector2(984, 714) * ART_SCALE + ART_OFFSET
var entry_polygon := _art_polygon(PackedVector2Array([
	Vector2(563, 147), Vector2(698, 141), Vector2(735, 293),
	Vector2(791, 350), Vector2(699, 389), Vector2(578, 361), Vector2(556, 295)
]))
# Polygons below are traced in source-image pixels, then mapped uniformly with art.
# The playable clearing stops at scenery; distant tents are intentionally backdrop.
var walk_polygon := _art_polygon(PackedVector2Array([
	Vector2(372, 411), Vector2(579, 369), Vector2(746, 347), Vector2(1046, 320),
	Vector2(1190, 337), Vector2(1220, 431), Vector2(1330, 505), Vector2(1460, 575),
	Vector2(1408, 667), Vector2(1310, 745), Vector2(1293, 823), Vector2(1154, 930),
	Vector2(950, 930), Vector2(837, 853), Vector2(754, 730), Vector2(580, 680),
	Vector2(354, 601), Vector2(335, 476)
]))
var blocked_polygons: Array[PackedVector2Array] = [
	# Headquarters left facade, brazier and supplies; open stair/ramp stays clear.
	_art_polygon(PackedVector2Array([Vector2(185, 90), Vector2(574, 105), Vector2(571, 325), Vector2(585, 369), Vector2(516, 392), Vector2(382, 404), Vector2(210, 432)])),
	_art_polygon(PackedVector2Array([Vector2(747, 120), Vector2(1015, 223), Vector2(1033, 311), Vector2(789, 341), Vector2(758, 301)])),
	# Tree trunk, low branches and rocks occupy ground; upper canopy is a depth mask.
	_art_polygon(PackedVector2Array([Vector2(420, 527), Vector2(547, 539), Vector2(622, 577), Vector2(640, 642), Vector2(551, 670), Vector2(399, 595)])),
	_art_polygon(PackedVector2Array([Vector2(205, 516), Vector2(386, 502), Vector2(423, 553), Vector2(392, 622), Vector2(202, 611)])),
	# Right supply stacks, satellite tent and the separate foreground chest.
	_art_polygon(PackedVector2Array([Vector2(1182, 399), Vector2(1282, 389), Vector2(1340, 440), Vector2(1347, 483), Vector2(1262, 481), Vector2(1181, 448)])),
	_art_polygon(PackedVector2Array([Vector2(1330, 348), Vector2(1668, 398), Vector2(1668, 549), Vector2(1473, 575), Vector2(1324, 480)])),
	_art_polygon(PackedVector2Array([Vector2(1349, 589), Vector2(1437, 586), Vector2(1463, 620), Vector2(1435, 655), Vector2(1348, 637)]))
]
var background_texture: Texture2D
var foreground_masks: Array[Polygon2D] = []
var click_blocking_polygons: Array[PackedVector2Array] = []
var _destination := Vector2.ZERO
var _marker_life := 0.0
var _hovering_entrance := false
var _was_near := false
var _time := 0.0


func _ready() -> void:
	name = "QuarterCamp"
	if ResourceLoader.exists(BACKGROUND_PATH):
		background_texture = load(BACKGROUND_PATH) as Texture2D
	# A ground prop beside the right supply stacks, clear of the central route.
	supply_chest = SupplyChestScript.new()
	supply_chest.name = "CampSupplyChest"
	supply_chest.position = Vector2(1150, 493) * ART_SCALE + ART_OFFSET
	supply_chest.sunlight = light_field.sunlight_at(supply_chest.position)
	supply_chest.z_index = int(supply_chest.position.y)
	add_child(supply_chest)
	blocked_polygons.append(supply_chest.ground_polygon)
	click_blocking_polygons.append(supply_chest.silhouette_polygon)
	navigation = NavigationScript.new()
	navigation.configure(walk_polygon, blocked_polygons)
	avatar = AvatarScript.new()
	avatar.lighting_field = light_field
	avatar.position = spawn_position
	add_child(avatar)
	_create_foreground()
	atmosphere = AtmosphereScript.new()
	atmosphere.flames.assign([Vector2(545, 304) * ART_SCALE + ART_OFFSET, Vector2(811, 264) * ART_SCALE + ART_OFFSET])
	atmosphere.dust_rect = Rect2(385, 220, 860, 460)
	atmosphere.z_index = 360
	add_child(atmosphere)
	_create_entrance_label()
	queue_redraw()


func set_active(value: bool) -> void:
	active = value
	visible = value
	set_process_unhandled_input(value)
	if avatar != null:
		avatar.set_active(value)
	if atmosphere != null:
		atmosphere.enabled = value
	if supply_chest != null:
		supply_chest.set_render_active(value)
	if not value:
		_hovering_entrance = false
		_marker_life = 0.0
		Input.set_default_cursor_shape(Input.CURSOR_ARROW)
	queue_redraw()


func restore_position(point: Vector2) -> void:
	if avatar == null:
		return
	avatar.stop()
	avatar.position = point if navigation.is_walkable(point) else spawn_position
	avatar.sync_lighting(0.0, true)


func get_actor_position() -> Vector2:
	return avatar.position if avatar != null else spawn_position


func is_near_entrance() -> bool:
	return avatar != null and avatar.position.distance_to(entrance_position) <= 84.0


func try_enter() -> bool:
	if not active or not is_near_entrance():
		return false
	avatar.stop()
	headquarters_requested.emit()
	return true


func walk_to(destination: Vector2) -> bool:
	if not active or avatar == null:
		return false
	var path: PackedVector2Array = navigation.path_to(avatar.position, destination)
	if path.is_empty():
		return false
	avatar.move_along(path)
	_destination = destination
	_marker_life = 1.5
	queue_redraw()
	return true


func _create_foreground() -> void:
	# Exact-source textured cutouts share the same registration as the painting.
	# Their ground baselines order the actor in front of or behind each object.
	foreground_masks = ForegroundScript.build(background_texture, ART_SCALE, ART_OFFSET)
	for mask: Polygon2D in foreground_masks:
		add_child(mask)
		# Small gaps within leaves remain conservative click blockers: a visible
		# leaf must never send the actor to unrelated dirt behind the canopy.
		click_blocking_polygons.append(mask.polygon)


func _create_entrance_label() -> void:
	var label := Label.new()
	label.name = "EntrancePlaque"
	label.text = "사령부"
	label.position = Vector2(583, 207) * ART_SCALE + ART_OFFSET
	label.size = Vector2(140, 36)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_color_override("font_color", Color("edcf8d"))
	label.add_theme_color_override("font_outline_color", Color("211c16"))
	label.add_theme_constant_override("outline_size", 5)
	label.add_theme_font_size_override("font_size", 23)
	label.z_index = 1200
	add_child(label)


static func _art_polygon(source_points: PackedVector2Array) -> PackedVector2Array:
	var result := PackedVector2Array()
	for point: Vector2 in source_points:
		result.append(point * ART_SCALE + ART_OFFSET)
	return result


func _unhandled_input(event: InputEvent) -> void:
	if not active:
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		var point: Vector2 = get_global_transform_with_canvas().affine_inverse() * event.position
		if Geometry2D.is_point_in_polygon(point, entry_polygon):
			if not try_enter():
				walk_to(entrance_position)
			get_viewport().set_input_as_handled()
		elif _is_visible_ground(point) and walk_to(point):
			get_viewport().set_input_as_handled()


func _is_visible_ground(point: Vector2) -> bool:
	for polygon: PackedVector2Array in click_blocking_polygons:
		if Geometry2D.is_point_in_polygon(point, polygon):
			return false
	return true


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT and avatar != null:
		avatar.stop()
		_marker_life = 0.0


func _process(delta: float) -> void:
	if not active:
		return
	_time += delta
	_marker_life = maxf(0.0, _marker_life - delta)
	var near := is_near_entrance()
	if near != _was_near:
		_was_near = near
		proximity_changed.emit(near)
	var pointer := get_local_mouse_position()
	var hover := Geometry2D.is_point_in_polygon(pointer, entry_polygon)
	if hover != _hovering_entrance:
		_hovering_entrance = hover
		Input.set_default_cursor_shape(Input.CURSOR_POINTING_HAND if hover else Input.CURSOR_ARROW)
	queue_redraw()


func _draw() -> void:
	if background_texture != null:
		draw_texture_rect(background_texture, Rect2(ART_OFFSET, SOURCE_SIZE * ART_SCALE), false)
	else:
		draw_rect(Rect2(Vector2.ZERO, CANVAS_SIZE), Color("554e3b"))
		draw_colored_polygon(walk_polygon, Color("89775a"))
		for obstacle: PackedVector2Array in blocked_polygons:
			draw_colored_polygon(obstacle, Color("682d27"))
	# A ring on the threshold reads as an interaction affordance without a crosshair.
	var emphasis := 0.80 if _hovering_entrance or _was_near else 0.42
	draw_set_transform(entrance_position, 0.0, Vector2(1.0, 0.32))
	draw_arc(Vector2.ZERO, 49.0, 0.0, TAU, 64, Color(0.94, 0.79, 0.45, emphasis), 2.0, true)
	draw_set_transform(Vector2.ZERO)
	if _marker_life > 0.0:
		var fade := minf(_marker_life * 2.0, 0.8)
		draw_set_transform(_destination, 0.0, Vector2(1.0, 0.40))
		draw_arc(Vector2.ZERO, 14.0 + (1.5 - _marker_life) * 8.0, 0.0, TAU, 32, Color(0.98, 0.86, 0.52, fade), 2.0, true)
		draw_set_transform(Vector2.ZERO)

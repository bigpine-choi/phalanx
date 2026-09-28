extends Node2D
## Fixed picture-plane staging: art, hotspot and feedback use identical coordinates.

signal activated
signal hover_changed(value: bool)

const Atmosphere := preload("res://scripts/scene_atmosphere.gd")
var table_polygon := PackedVector2Array([Vector2(505, 486), Vector2(1248, 502), Vector2(1580, 800), Vector2(266, 742)])
var table_center := Vector2(850, 630)
var is_hovered := false
var active := false
var background: Sprite2D
var atmosphere: Node2D
var _pressed := false
var _pulse := 0.0

func _ready() -> void:
	name = "FixedHeadquarters"
	background = Sprite2D.new()
	background.name = "HeadquartersArtwork"
	# Parent draws the map highlight; keep artwork behind that feedback layer.
	background.show_behind_parent = true
	if ResourceLoader.exists("res://assets/art/headquarters.png"):
		background.texture = load("res://assets/art/headquarters.png")
		background.position = Vector2(800, 450)
		background.scale = Vector2.ONE * (1600.0 / background.texture.get_width())
	add_child(background)
	atmosphere = Atmosphere.new()
	atmosphere.name = "InteriorAtmosphere"
	atmosphere.flames.assign([Vector2(96, 405), Vector2(1512, 422)])
	add_child(atmosphere)

func set_active(value: bool) -> void:
	active = value
	visible = value
	_pressed = false
	if is_instance_valid(atmosphere):
		atmosphere.enabled = value
	_set_hover(false)

func _process(delta: float) -> void:
	_pulse = maxf(0.0, _pulse - delta * 3.5)
	if active:
		queue_redraw()

func _set_hover(value: bool) -> void:
	if is_hovered == value:
		return
	is_hovered = value
	Input.set_default_cursor_shape(Input.CURSOR_POINTING_HAND if value else Input.CURSOR_ARROW)
	hover_changed.emit(value)
	queue_redraw()

func _input(event: InputEvent) -> void:
	# UI gets first refusal: only an unhandled motion can restore map hover.
	if active and event is InputEventMouseMotion:
		_set_hover(false)

func _unhandled_input(event: InputEvent) -> void:
	if not active:
		return
	if event is InputEventMouseMotion:
		var point: Vector2 = get_global_transform_with_canvas().affine_inverse() * event.position
		_set_hover(Geometry2D.is_point_in_polygon(point, table_polygon))
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		var point: Vector2 = get_global_transform_with_canvas().affine_inverse() * event.position
		var hit := Geometry2D.is_point_in_polygon(point, table_polygon)
		if event.pressed:
			_pressed = hit
			if hit:
				_pulse = 1.0
				get_viewport().set_input_as_handled()
		elif _pressed:
			_pressed = false
			get_viewport().set_input_as_handled()
			if hit:
				activated.emit()

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		_pressed = false
		_set_hover(false)

func _draw() -> void:
	if not active or not is_hovered:
		return
	draw_colored_polygon(table_polygon, Color(1.0, 0.80, 0.42, 0.035 + _pulse * 0.055))
	var border := table_polygon.duplicate()
	border.append(border[0])
	draw_polyline(border, Color(0.91, 0.72, 0.37, 0.68), 1.5, true)

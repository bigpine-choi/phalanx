extends Node2D
## Fixed picture-plane staging: art, hotspot and feedback use identical coordinates.

signal activated
signal hover_changed(value: bool)
signal journal_requested
signal journal_hover_changed(value: bool)

const Atmosphere := preload("res://scripts/scene_atmosphere.gd")
var table_polygon := PackedVector2Array([Vector2(505, 486), Vector2(1248, 502), Vector2(1580, 800), Vector2(266, 742)])
var table_center := Vector2(850, 630)
var journal_polygon := PackedVector2Array([Vector2(18,590),Vector2(150,564),Vector2(295,610),Vector2(175,675),Vector2(18,690)])
var journal_center := Vector2(130,625)
var journal_label: Label
var is_journal_hovered := false
var is_hovered := false
var active := false
var background: Sprite2D
var atmosphere: Node2D
var _pressed := ""
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
	journal_label = Label.new()
	journal_label.text = "◆  작전 일지"
	journal_label.position = Vector2(65,715)
	journal_label.size = Vector2(180,34)
	journal_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	journal_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	journal_label.add_theme_font_size_override("font_size",19)
	journal_label.add_theme_color_override("font_color",Color("e4c58b"))
	journal_label.add_theme_color_override("font_outline_color",Color("24180f"))
	journal_label.add_theme_constant_override("outline_size",7)
	add_child(journal_label)

func set_active(value: bool) -> void:
	active = value
	visible = value
	_pressed = ""
	if is_instance_valid(atmosphere):
		atmosphere.enabled = value
	_set_hover(false)

func _process(delta: float) -> void:
	_pulse = maxf(0.0, _pulse - delta * 3.5)
	if active:
		queue_redraw()

func _set_hover(value: bool, journal_hover := false) -> void:
	if is_hovered == value and is_journal_hovered == journal_hover:
		return
	is_hovered = value
	is_journal_hovered = journal_hover
	Input.set_default_cursor_shape(Input.CURSOR_POINTING_HAND if value or journal_hover else Input.CURSOR_ARROW)
	hover_changed.emit(value)
	journal_hover_changed.emit(journal_hover)
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
		var hit := _hit_target(point)
		_set_hover(hit == "map",hit == "journal")
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		var point: Vector2 = get_global_transform_with_canvas().affine_inverse() * event.position
		var hit := _hit_target(point)
		if event.pressed:
			_pressed = hit
			if not hit.is_empty():
				_pulse = 1.0
				get_viewport().set_input_as_handled()
		elif not _pressed.is_empty():
			var pressed_target := _pressed
			_pressed = ""
			get_viewport().set_input_as_handled()
			if hit == pressed_target:
				if hit == "journal":
					journal_requested.emit()
				else:
					activated.emit()

func _hit_target(point: Vector2) -> String:
	if Geometry2D.is_point_in_polygon(point,journal_polygon) or journal_label.get_rect().has_point(point):
		return "journal"
	return "map" if Geometry2D.is_point_in_polygon(point,table_polygon) else ""

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		_pressed = ""
		_set_hover(false)

func _draw() -> void:
	if not active or (not is_hovered and not is_journal_hovered):
		return
	var polygon := journal_polygon if is_journal_hovered else table_polygon
	draw_colored_polygon(polygon, Color(1.0, 0.80, 0.42, 0.035 + _pulse * 0.055))
	var border := polygon.duplicate()
	border.append(border[0])
	draw_polyline(border, Color(0.91, 0.72, 0.37, 0.68), 1.5, true)

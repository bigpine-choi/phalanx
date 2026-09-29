extends Control
## Scene flow owns only the two persistent views and dashboard modality.
## 1600×900 artwork, sprites and click polygons share one uniform transform.

const CampScene := preload("res://scripts/quarter_camp.gd")
const Headquarters := preload("res://scripts/fixed_headquarters.gd")
const Hud := preload("res://scripts/phalanx_hud.gd")
const Overlay := preload("res://scripts/dashboard_overlay.gd")
const Transition := preload("res://scripts/scene_transition.gd")
const ART_SIZE := Vector2(1600, 900)

var mode := "camp"
var world: Node2D
var camp: Node2D
var headquarters: Node2D
var dashboard_overlay: CanvasLayer
var hud: Control
var return_button: Button
var enter_button: Button
var _camp_return_position := Vector2.ZERO
var scene_transition: CanvasLayer
var _view_zoom := 1.0
var _view_focus := ART_SIZE * 0.5

func _ready() -> void:
	get_viewport().gui_embed_subwindows = true
	get_window().title = "Phalanx — 원정 야영지 / 사령부"
	get_window().min_size = Vector2i(960, 680)
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var matte := ColorRect.new()
	matte.color = Color("0c100e")
	matte.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	matte.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(matte)
	world = Node2D.new()
	world.name = "FixedPicturePlane"
	add_child(world)
	camp = CampScene.new()
	world.add_child(camp)
	headquarters = Headquarters.new()
	world.add_child(headquarters)
	headquarters.set_active(false)
	camp.headquarters_requested.connect(enter_headquarters)
	headquarters.activated.connect(_open_dashboard)
	headquarters.journal_requested.connect(_open_journal)
	hud = Hud.new()
	hud.name = "SceneHUD"
	add_child(hud)
	return_button = hud.return_button
	enter_button = hud.enter_button
	hud.return_requested.connect(return_to_camp)
	hud.enter_requested.connect(func() -> void: camp.try_enter())
	headquarters.hover_changed.connect(hud.set_table_hover)
	headquarters.journal_hover_changed.connect(func(value: bool) -> void:
		if value:
			hud.instruction_label.text = "클릭  ·  지난 작전 일지 열기")
	dashboard_overlay = Overlay.new()
	dashboard_overlay.framed_interior = true
	dashboard_overlay.name = "DashboardOverlay"
	add_child(dashboard_overlay)
	dashboard_overlay.opened.connect(_dashboard_opened)
	dashboard_overlay.closed.connect(_dashboard_closed)
	scene_transition = Transition.new()
	scene_transition.name = "SceneTransition"
	add_child(scene_transition)
	scene_transition.finished.connect(_location_arrived)
	get_viewport().size_changed.connect(_fit_world)
	_fit_world()
	camp.set_active(true)

func _fit_world() -> void:
	var viewport_size := get_viewport_rect().size
	var factor := minf(viewport_size.x / ART_SIZE.x, viewport_size.y / ART_SIZE.y)
	world.scale = Vector2.ONE * factor * _view_zoom
	world.position = (viewport_size - ART_SIZE * factor) * 0.5 + _view_focus * factor * (1.0 - _view_zoom)

func world_to_view(point: Vector2) -> Vector2:
	return world.get_global_transform_with_canvas() * point

func view_to_world(point: Vector2) -> Vector2:
	return world.get_global_transform_with_canvas().affine_inverse() * point

func enter_headquarters() -> void:
	if is_transitioning() or mode != "camp" or not camp.is_near_entrance() or dashboard_overlay.is_open():
		return
	_camp_return_position = camp.get_actor_position()
	camp.set_active(false)
	camp.show()
	hud.hide()
	_view_focus = camp.entrance_position
	Input.set_default_cursor_shape(Input.CURSOR_ARROW)
	scene_transition.play("원정군 사령부", "HEADQUARTERS  /  전략의 시작", func() -> void:
		camp.hide()
		mode = "headquarters"
		headquarters.show()
		_view_focus = headquarters.table_center, _transition_motion)

func return_to_camp() -> void:
	if is_transitioning() or mode != "headquarters" or dashboard_overlay.is_open():
		return
	headquarters.set_active(false)
	headquarters.show()
	hud.hide()
	_view_focus = headquarters.table_center
	Input.set_default_cursor_shape(Input.CURSOR_ARROW)
	scene_transition.play("원정 야영지", "EXPEDITION CAMP  /  다시, 전선으로", func() -> void:
		headquarters.hide()
		mode = "camp"
		camp.restore_position(_camp_return_position)
		camp.show()
		_view_focus = camp.entrance_position, _transition_motion)

func _transition_motion(progress: float, arrived: bool) -> void:
	_view_zoom = lerpf(1.045, 1.0, smoothstep(0.44, 1.0, progress)) if arrived else lerpf(1.0, 1.065, smoothstep(0.0, 0.44, progress))
	_fit_world()

func _location_arrived() -> void:
	_view_zoom = 1.0
	_fit_world()
	if mode == "camp":
		camp.set_active(true)
	else:
		headquarters.set_active(true)
	hud.set_location(mode)
	if mode == "camp":
		hud.set_near_entrance(camp.is_near_entrance())
	hud.show()

func is_transitioning() -> bool:
	return (is_instance_valid(scene_transition) and scene_transition.busy) or (is_instance_valid(dashboard_overlay) and dashboard_overlay.is_transitioning())

func _open_dashboard() -> void:
	if mode == "headquarters" and not is_transitioning():
		dashboard_overlay.open_dashboard(world_to_view(headquarters.table_center))

func _dashboard_opened() -> void:
	headquarters.set_active(false)
	# Keep the authored interior visible beneath the modal if its frame exposes it.
	headquarters.show()
	hud.hide()
	Input.set_default_cursor_shape(Input.CURSOR_ARROW)

func _open_journal() -> void:
	if mode == "headquarters" and not is_transitioning():
		dashboard_overlay.open_dashboard(world_to_view(headquarters.journal_center),true)

func _dashboard_closed() -> void:
	if mode == "headquarters":
		headquarters.set_active(true)
		hud.show()
		hud.set_location(mode)

func _process(_delta: float) -> void:
	if mode == "camp":
		hud.set_near_entrance(camp.is_near_entrance())

func _unhandled_input(event: InputEvent) -> void:
	# DashboardOverlay consumes popup/dashboard Escape in _input first.
	if event is InputEventKey and event.keycode == KEY_ESCAPE and event.pressed:
		if event.echo:
			get_viewport().set_input_as_handled()
		elif mode == "headquarters" and not dashboard_overlay.is_open():
			return_to_camp()
			get_viewport().set_input_as_handled()

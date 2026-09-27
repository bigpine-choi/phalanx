extends Area3D
## Only the operations table is pickable. Physics queries stay on physics frames.

signal hover_changed(value: bool)
signal activated

var camera: Camera3D
var interaction_enabled := true
var hovered := false
var _mouse_position := Vector2(-1, -1)
var _pending_click := false
var _click_position := Vector2.ZERO

func set_interaction_enabled(value: bool) -> void:
	interaction_enabled = value
	_pending_click = false
	# The pointer can move across the modal while unhandled input is blocked.
	_mouse_position = get_viewport().get_mouse_position() if value else Vector2(-1, -1)
	if not value:
		_set_hovered(false)

func _unhandled_input(event: InputEvent) -> void:
	if not interaction_enabled:
		return
	if event is InputEventMouseMotion:
		_mouse_position = event.position
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		_mouse_position = event.position
		_click_position = event.position
		_pending_click = true

func _physics_process(_delta: float) -> void:
	if not interaction_enabled or not is_instance_valid(camera):
		return
	_set_hovered(_hits_table(_mouse_position))
	if _pending_click:
		_pending_click = false
		if _hits_table(_click_position):
			activated.emit()

func _hits_table(screen_position: Vector2) -> bool:
	if not get_viewport().get_visible_rect().has_point(screen_position):
		return false
	var origin := camera.project_ray_origin(screen_position)
	var ray_end := origin + camera.project_ray_normal(screen_position) * 100.0
	var query := PhysicsRayQueryParameters3D.create(origin, ray_end, collision_layer)
	query.collide_with_areas = true
	query.collide_with_bodies = false
	var hit := get_world_3d().direct_space_state.intersect_ray(query)
	return hit.get("collider") == self

func _set_hovered(value: bool) -> void:
	if hovered == value:
		return
	hovered = value
	Input.set_default_cursor_shape(Input.CURSOR_POINTING_HAND if value else Input.CURSOR_ARROW)
	hover_changed.emit(value)

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_MOUSE_EXIT or what == NOTIFICATION_WM_WINDOW_FOCUS_OUT:
		_mouse_position = Vector2(-1, -1)
		_pending_click = false
		_set_hovered(false)

func _exit_tree() -> void:
	Input.set_default_cursor_shape(Input.CURSOR_ARROW)

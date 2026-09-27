extends Area3D
## A short centre-view ray selects the table only when no solid object intervenes.

signal hover_changed(value: bool)
signal activated

const REACH := 2.2

var camera: Camera3D
var interaction_enabled := false
var hovered := false
var _pending_activation := false

func set_interaction_enabled(value: bool) -> void:
	interaction_enabled = value
	_pending_activation = false
	if not value:
		_set_hovered(false)

func _unhandled_input(event: InputEvent) -> void:
	if not interaction_enabled:
		return
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_E or event.keycode == KEY_E:
			_pending_activation = true
			get_viewport().set_input_as_handled()

func _physics_process(_delta: float) -> void:
	if not interaction_enabled or not is_instance_valid(camera):
		return
	_set_hovered(_hits_table())
	if _pending_activation:
		_pending_activation = false
		# Recheck at activation time instead of trusting last frame's hover.
		if hovered:
			activated.emit()

func _hits_table() -> bool:
	var origin := camera.global_position
	var ray_end := origin - camera.global_basis.z * REACH
	# Layer 1 is the solid camp; layer 2 is this interaction area. Player uses layer 4.
	var query := PhysicsRayQueryParameters3D.create(origin, ray_end, 3)
	query.collide_with_areas = true
	query.collide_with_bodies = true
	query.hit_from_inside = true
	var hit := get_world_3d().direct_space_state.intersect_ray(query)
	return hit.get("collider") == self

func _set_hovered(value: bool) -> void:
	if hovered == value:
		return
	hovered = value
	hover_changed.emit(value)

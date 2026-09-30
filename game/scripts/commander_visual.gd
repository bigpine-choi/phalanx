extends Node2D
## Only the actor is 3D. Its transparent render joins the original 2D depth order.
const Model := preload("res://scripts/commander_model.gd")
const Gait := preload("res://scripts/commander_gait.gd")
var viewport: SubViewport
var camera: Camera3D
var model: Node3D
var sprite: Sprite2D
var _left := Vector3(-0.105, 0, 0)
var _right := Vector3(0.105, 0, 0)
var _yaw := PI
var key: DirectionalLight3D
var fill: DirectionalLight3D
var environment: Environment
var sunlight := 1.0
var target_sunlight := 1.0

func _ready() -> void:
	viewport = SubViewport.new()
	viewport.name = "CommanderRender"
	viewport.size = Vector2i(384, 448)
	viewport.own_world_3d = true
	viewport.transparent_bg = true
	viewport.msaa_3d = Viewport.MSAA_4X
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(viewport)
	var stage := Node3D.new()
	viewport.add_child(stage)
	model = Model.new()
	stage.add_child(model)
	var world_environment := WorldEnvironment.new()
	var env := Environment.new()
	environment = env
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0, 0, 0, 0)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("b6b6a9")
	env.ambient_light_energy = 0.40
	env.ssao_enabled = true
	env.ssao_radius = 0.30
	env.ssao_intensity = 1.5
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	world_environment.environment = env
	stage.add_child(world_environment)
	key = DirectionalLight3D.new()
	key.light_color = Color("ffe0ae")
	key.light_energy = 1.65
	key.shadow_enabled = true
	stage.add_child(key)
	key.position = Vector3(4, 6, -4)
	key.look_at(Vector3.ZERO)
	fill = DirectionalLight3D.new()
	fill.light_color = Color("c0c8cb")
	fill.light_energy = 0.32
	stage.add_child(fill)
	fill.position = Vector3(2, 3, 5)
	fill.look_at(Vector3(0, 0.9, 0))
	camera = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 2.9
	camera.near = 0.05
	camera.far = 30.0
	stage.add_child(camera)
	var aim := Vector3(0, 0.88, 0)
	camera.position = aim + Vector3(0, sin(Gait.ELEVATION), cos(Gait.ELEVATION)) * 7.0
	camera.look_at(aim)
	camera.current = true
	sprite = Sprite2D.new()
	sprite.name = "CommanderComposite"
	sprite.texture = viewport.get_texture()
	sprite.centered = false
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	add_child(sprite)
	# Camera-derived feet registration is shared by every direction and pose.
	var ground := camera.unproject_position(Vector3.ZERO)
	var unit := camera.unproject_position(Vector3.RIGHT)
	var factor := Gait.PIXELS_PER_METRE / maxf(absf(unit.x - ground.x), 1.0)
	sprite.scale = Vector2.ONE * factor
	sprite.position = -ground * factor
	model.rotation.y = PI
	queue_redraw()

func present(gait: RefCounted, time: float) -> void:
	_yaw = gait.yaw
	_left = gait.left_foot
	_right = gait.right_foot
	model.rotation.y = _yaw
	model.apply_pose(_left, _right, fposmod(gait.phase, 1.0) * TAU, gait.walk_blend, gait.turn_lean, time)
	queue_redraw()

## Input is sun visibility at the actor's authored ground footprint. A small
## temporal response softens walking boundaries; teleports/restores snap so an
## old location cannot light the first frame after returning to camp.
func update_lighting(visibility: float, delta: float, immediate := false) -> void:
	target_sunlight = clampf(visibility, 0.0, 1.0)
	sunlight = target_sunlight if immediate else lerpf(sunlight, target_sunlight, 1.0 - exp(-12.0 * maxf(delta, 0.0)))
	key.light_energy = 1.65 * sunlight
	fill.light_energy = lerpf(0.22, 0.32, sunlight)
	fill.light_color = Color("9baec2").lerp(Color("c0c8cb"), sunlight)
	environment.ambient_light_color = Color("929fae").lerp(Color("b6b6a9"), sunlight)
	environment.ambient_light_energy = lerpf(0.30, 0.40, sunlight)
	queue_redraw()

func lighting_snapshot() -> Dictionary:
	return {"sunlight": sunlight, "target_sunlight": target_sunlight,
		"key_energy": key.light_energy, "fill_energy": fill.light_energy,
		"cast_opacity": 0.032 * sunlight, "contact_opacity": 0.26}

func set_render_active(value: bool) -> void:
	if viewport != null:
		viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS if value else SubViewport.UPDATE_DISABLED

func _ground_point(foot: Vector3) -> Vector2:
	var rotated := Basis(Vector3.UP, _yaw) * foot
	return Vector2(rotated.x, rotated.z * sin(Gait.ELEVATION)) * Gait.PIXELS_PER_METRE

func _ellipse(at: Vector2, extent: Vector2, alpha: float) -> void:
	draw_set_transform(at, 0.0, extent)
	draw_circle(Vector2.ZERO, 1.0, Color(0.12, 0.095, 0.061, alpha))
	draw_set_transform(Vector2.ZERO)

func _draw() -> void:
	# Painted sun comes from upper-right: cast shadow runs lower-left. Shade removes direct cast shadow, while foot contact remains.
	for layer in range(4, 0, -1):
		var softness := float(layer)
		_ellipse(Vector2(-26, 15), Vector2(33 + softness * 2.0, 12 + softness), 0.032 * sunlight)
	_ellipse(Vector2(-2, 2), Vector2(18, 6), lerpf(0.08, 0.13, sunlight))
	for foot in [_left, _right]:
		var contact := 1.0 - clampf(foot.y / 0.13, 0.0, 1.0)
		_ellipse(_ground_point(foot), Vector2(7.4, 3.1), 0.26 * contact)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2(1, 0.36))
	draw_arc(Vector2.ZERO, 24, 0, TAU, 64, Color(0.91, 0.76, 0.42, 0.26), 1.1, true)
	draw_set_transform(Vector2.ZERO)

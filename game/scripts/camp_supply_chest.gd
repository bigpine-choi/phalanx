extends Node2D
## Static imported prop, composited onto the authored camp picture plane.
## Ground registration uses the camera projection, matching commander_visual.gd.

const CHEST := preload("res://assets/props/supply_chest/supply_chest.glb")
const Gait := preload("res://scripts/commander_gait.gd")
const PIXELS_PER_METRE := Gait.PIXELS_PER_METRE
var viewport: SubViewport
var sprite: Sprite2D
var sunlight := 1.0
var ground_polygon := PackedVector2Array()
var silhouette_polygon := PackedVector2Array()

func _ready() -> void:
	viewport = SubViewport.new()
	viewport.name = "SupplyChestRender"
	viewport.size = Vector2i(256, 224)
	viewport.own_world_3d = true
	viewport.transparent_bg = true
	viewport.msaa_3d = Viewport.MSAA_4X
	viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
	add_child(viewport)
	var stage := Node3D.new()
	viewport.add_child(stage)
	var chest := CHEST.instantiate() as Node3D
	chest.name = "SupplyChestModel"
	stage.add_child(chest)
	var environment := WorldEnvironment.new()
	var ambient := Environment.new()
	ambient.background_mode = Environment.BG_COLOR
	ambient.background_color = Color(0, 0, 0, 0)
	ambient.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	ambient.ambient_light_color = Color("929fae").lerp(Color("b6b6a9"), sunlight)
	ambient.ambient_light_energy = lerpf(0.30, 0.40, sunlight)
	ambient.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.environment = ambient
	stage.add_child(environment)
	var key := DirectionalLight3D.new()
	key.light_color = Color("ffe0ae")
	key.light_energy = 1.65 * sunlight
	key.shadow_enabled = true
	stage.add_child(key)
	key.position = Vector3(4, 6, -4)
	key.look_at(Vector3(0, 0.25, 0))
	var fill := DirectionalLight3D.new()
	fill.light_color = Color("9baec2").lerp(Color("c0c8cb"), sunlight)
	fill.light_energy = lerpf(0.22, 0.32, sunlight)
	stage.add_child(fill)
	fill.position = Vector3(3, 2, 4)
	fill.look_at(Vector3(0, 0.25, 0))
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 1.22
	camera.near = 0.05
	camera.far = 12.0
	stage.add_child(camera)
	var aim := Vector3(0, 0.275, 0)
	camera.position = aim + Vector3(sin(0.4) * cos(Gait.ELEVATION), sin(Gait.ELEVATION), cos(0.4) * cos(Gait.ELEVATION)) * 5.0
	camera.look_at(aim)
	camera.current = true
	sprite = Sprite2D.new()
	sprite.name = "SupplyChestComposite"
	sprite.texture = viewport.get_texture()
	sprite.centered = false
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	add_child(sprite)
	var ground := camera.unproject_position(Vector3.ZERO)
	# Measure in the camera's horizontal plane, so yaw does not change prop scale.
	var right := camera.unproject_position(camera.global_basis.x)
	var factor := PIXELS_PER_METRE / maxf(ground.distance_to(right), 1.0)
	sprite.scale = Vector2.ONE * factor
	sprite.position = -ground * factor
	# Project the same model envelope for navigation and visible click blocking.
	# The asset is 0.90 m wide, 0.50 m deep and 0.55 m high, grounded at zero.
	var corners := [Vector3(-0.45, 0, -0.25), Vector3(0.45, 0, -0.25), Vector3(0.45, 0, 0.25), Vector3(-0.45, 0, 0.25)]
	var silhouette := PackedVector2Array()
	for corner: Vector3 in corners:
		var foot := position + (camera.unproject_position(corner) - ground) * factor
		ground_polygon.append(foot)
		silhouette.append(foot)
		silhouette.append(position + (camera.unproject_position(corner + Vector3.UP * 0.55) - ground) * factor)
	silhouette_polygon = Geometry2D.convex_hull(silhouette)
	queue_redraw()

func set_render_active(value: bool) -> void:
	if viewport != null:
		# The chest and lighting are static: keep the completed texture, not a live loop.
		viewport.render_target_update_mode = SubViewport.UPDATE_ONCE if value else SubViewport.UPDATE_DISABLED

func _draw() -> void:
	for layer in range(4, 0, -1):
		draw_set_transform(Vector2(-3, 2), 0, Vector2(30 + layer * 2, 10 + layer))
		draw_circle(Vector2.ZERO, 1, Color(0.09, 0.065, 0.04, 0.08))
	draw_set_transform(Vector2.ZERO)

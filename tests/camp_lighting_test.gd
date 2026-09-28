extends SceneTree
## Behavioral light-field regression. GPU adds a same-pose pixel luminance check.
const Field := preload("res://scripts/camp_light_field.gd")
var checks := 0
var failures := 0
var app: Control
var camp: Node2D
var avatar: Node2D

func _initialize() -> void:
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func frames(count: int) -> void:
	for index: int in count:
		await process_frame

func ground(source: Vector2) -> Vector2:
	return source * Field.ART_SCALE + Field.ART_OFFSET

func mean_actor_luminance() -> float:
	await RenderingServer.frame_post_draw
	var image: Image = avatar.visual.viewport.get_texture().get_image()
	var sum := 0.0
	var pixels := 0
	for y: int in image.get_height():
		for x: int in image.get_width():
			var color := image.get_pixel(x,y)
			if color.a > 0.95:
				sum += color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722
				pixels += 1
	check(pixels > 1500, "GPU must render an opaque actor before brightness can be evaluated")
	return sum / maxf(pixels,1)

func run() -> void:
	root.size = Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await frames(8)
	camp = app.camp
	avatar = camp.avatar
	var field: RefCounted = camp.light_field
	var sunny := ground(Vector2(984,714))
	var shaded := ground(Vector2(1090,550))
	check(field.sunlight_at(sunny) > 0.98, "Open courtyard must receive sunlight")
	check(field.sunlight_at(shaded) < 0.20, "Painted right canopy shadow must block direct sunlight")
	check(field.sunlight_at(ground(Vector2(1040,389))) < 0.3, "Wall-side tree shadow must shade the actor")
	check(field.sunlight_at(ground(Vector2(701,572))) < 0.35, "Olive canopy must shade an actor before the foliage depth mask")
	check(camp.navigation.is_walkable(sunny) and camp.navigation.is_walkable(shaded), "Sun/shade review fixtures must be genuinely reachable ground")
	var max_change := 0.0
	var prior: float = field.sunlight_at(ground(Vector2(1090,440)))
	var intermediate := 0
	for y: int in range(441,721):
		var sample: float = field.sunlight_at(ground(Vector2(1090,y)))
		max_change = maxf(max_change,absf(sample-prior))
		if sample > 0.3 and sample < 0.8:
			intermediate += 1
		prior = sample
	check(max_change < 0.065 and intermediate > 12, "A boundary must have a spatial penumbra, not an on/off polygon edge")
	for resolution: Vector2i in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = resolution
		await frames(3)
		var roundtrip: Vector2 = app.view_to_world(app.world_to_view(shaded))
		check(absf(field.sunlight_at(roundtrip)-field.sunlight_at(shaded)) < 0.0001, "Lighting must stay registered to authored ground after resizing")
	avatar.set_physics_process(false)
	camp.restore_position(sunny)
	var sun: Dictionary = avatar.visual.lighting_snapshot()
	camp.restore_position(shaded)
	var shade: Dictionary = avatar.visual.lighting_snapshot()
	check(shade.key_energy < sun.key_energy * 0.25, "Shade must reduce the actual 3D directional light, not only a status value")
	check(shade.cast_opacity < sun.cast_opacity * 0.25, "Actor's cast shadow must weaken beneath existing canopy shadow")
	check(shade.contact_opacity == sun.contact_opacity and shade.fill_energy > 0.15, "Foot contact and readable ambient fill must survive in deep shade")
	check(is_equal_approx(shade.sunlight,shade.target_sunlight), "Position restore must not flash with previous-location lighting")
	avatar.visual.update_lighting(1.0, 0.0, true)
	avatar.visual.update_lighting(0.14,1.0/60.0)
	check(avatar.visual.sunlight > 0.8 and avatar.visual.sunlight < 1.0, "One walking frame must ease into shade")
	for index: int in 30:
		avatar.visual.update_lighting(0.14,1.0/60.0)
	check(absf(avatar.visual.sunlight-0.14) < 0.005, "Lighting must settle promptly without trailing far behind the actor")
	var shade_before: float = avatar.visual.sunlight
	avatar.gait.yaw = PI * 0.5
	avatar.visual.present(avatar.gait,0.0)
	check(is_equal_approx(avatar.visual.sunlight,shade_before), "Turning in place must not change ground occlusion")
	if DisplayServer.get_name() != "headless":
		avatar.gait.yaw = 0.0
		avatar.gait.walk_blend = 0.0
		avatar.visual.present(avatar.gait,0.0)
		avatar.visual.update_lighting(1.0,0.0,true)
		await frames(5)
		var light_pixels := await mean_actor_luminance()
		avatar.visual.update_lighting(0.14,0.0,true)
		await frames(5)
		var shade_pixels := await mean_actor_luminance()
		print("GPU_SHADE_LUMINANCE sun=",light_pixels," shade=",shade_pixels," ratio=",shade_pixels/light_pixels)
		check(shade_pixels < light_pixels * 0.78 and shade_pixels > light_pixels * 0.20, "Actual shaded render must be visibly darker without becoming a black silhouette")
	app.queue_free()
	await frames(3)
	print("PHALANX_CAMP_LIGHTING_TEST: %s (%d checks; %s)" % ["PASS" if failures == 0 else "FAIL",checks,DisplayServer.get_name()])
	quit(0 if failures == 0 else 1)

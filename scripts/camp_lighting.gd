extends Node3D
## Sunset and small fires share a direction/colour story; no fog or bloom veil.

const Materials = preload("res://scripts/camp_materials.gd")
const FIRE = preload("res://shaders/camp_fire.gdshader")
const SKY = preload("res://shaders/camp_sky.gdshader")
const SUN_ROTATION := Vector3(-13.5, 24, 0)
var _lamps: Array[OmniLight3D] = []
var _elapsed := 0.0

func _ready() -> void:
	name = "CampLighting"
	_atmosphere()
	for side: float in [-1.0, 1.0]:
		_brazier(Vector3(side * 3.05, 0, 0.60))

func _process(delta: float) -> void:
	_elapsed += delta
	for i in _lamps.size():
		_lamps[i].light_energy = 1.45 * (1.0 + sin(_elapsed * 1.8 + i * 2.7) * 0.035 + sin(_elapsed * 3.2) * 0.013)

func _atmosphere() -> void:
	var world := WorldEnvironment.new()
	world.name = "CampAtmosphere"
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	var sky_material := ShaderMaterial.new()
	sky_material.shader = SKY
	sky_material.set_shader_parameter("sun_direction", Basis.from_euler(SUN_ROTATION * PI / 180.0).z)
	var sky := Sky.new()
	sky.sky_material = sky_material
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("a7b5cb")
	environment.ambient_light_energy = 0.27
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	environment.ssao_enabled = true
	environment.ssao_radius = 0.9
	environment.ssao_intensity = 1.3
	environment.glow_enabled = false
	environment.fog_enabled = false
	world.environment = environment
	add_child(world)
	var sun := DirectionalLight3D.new()
	sun.name = "LateAfternoonSun"
	sun.rotation_degrees = SUN_ROTATION
	sun.light_color = Color("ffdfb3")
	sun.light_energy = 1.55
	sun.light_angular_distance = 1.0
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 70.0
	add_child(sun)
	# A restrained ceiling bounce keeps parchment readable inside the red canopy.
	var bounce := OmniLight3D.new()
	bounce.name = "MapWarmFill"
	bounce.position = Vector3(0, 2.75, 0.2)
	bounce.light_color = Color("f3dec3")
	bounce.light_energy = 1.05
	bounce.omni_range = 5.1
	bounce.omni_attenuation = 1.3
	bounce.shadow_enabled = true
	bounce.light_size = 1.2
	add_child(bounce)

func _mesh(node_name: String, mesh: Mesh, at: Vector3, material: Material) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = at
	instance.material_override = material
	add_child(instance, true)
	return instance

func _metal_cylinder(node_name: String, at: Vector3, radius: float, height: float, material: Material) -> void:
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius
	mesh.bottom_radius = radius
	mesh.height = height
	mesh.radial_segments = 20
	_mesh(node_name, mesh, at, material)

func _bowl(at: Vector3, bronze: Material) -> void:
	# Revolved solid section: underside, outer wall, rolled lip, inner basin.
	var profile := [Vector2(0.065, 1.15), Vector2(0.16, 1.15), Vector2(0.27, 1.24), Vector2(0.33, 1.37), Vector2(0.32, 1.405), Vector2(0.285, 1.38), Vector2(0.235, 1.27), Vector2(0.075, 1.21), Vector2(0.065, 1.15)]
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in profile.size():
		for column in 33:
			var angle := float(column) / 32.0 * TAU
			var point: Vector2 = profile[row]
			surface.set_uv(Vector2(float(column) / 32.0, float(row) / 8.0))
			surface.add_vertex(Vector3(cos(angle) * point.x, point.y, sin(angle) * point.x))
			if row > 0 and column > 0:
				var index := row * 33 + column
				for i in [index - 34, index - 33, index - 1, index - 33, index, index - 1]:
					surface.add_index(i)
	surface.generate_normals()
	_mesh("BrazierBowl", surface.commit(), at, bronze)

func _brazier(at: Vector3) -> void:
	var bronze := Materials.bronze(Color("977649"))
	_metal_cylinder("BrazierFoot", at + Vector3(0, 0.07, 0), 0.28, 0.14, bronze)
	_metal_cylinder("BrazierStem", at + Vector3(0, 0.65, 0), 0.055, 1.16, bronze)
	for y: float in [0.22, 1.04, 1.15]:
		_metal_cylinder("BrazierCollar", at + Vector3(0, y, 0), 0.09, 0.045, bronze)
	_bowl(at, bronze)
	var coal := StandardMaterial3D.new()
	coal.albedo_color = Color("29221e")
	coal.roughness = 1.0
	var ember := StandardMaterial3D.new()
	ember.albedo_color = Color("8c2912")
	ember.emission_enabled = true
	ember.emission = Color("c34212")
	ember.emission_energy_multiplier = 0.65
	for i in 11:
		var angle := float(i) * 2.39996
		var radius := 0.055 + float(i % 3) * 0.061
		var point := at + Vector3(cos(angle) * radius, 1.345, sin(angle) * radius)
		var chunk := PrismMesh.new()
		chunk.size = Vector3(0.10, 0.052, 0.077)
		var mesh := _mesh("Charcoal", chunk, point, coal)
		mesh.rotation = Vector3(0.1 * i, angle, 0.12 * i)
		var crack := BoxMesh.new()
		crack.size = Vector3(0.028, 0.003, 0.055)
		var glow := _mesh("CoalEmber", crack, point + Vector3(0.018, 0.021, 0), ember)
		glow.rotation.y = angle
	for i in 5:
		var angle := float(i) * 2.39996
		_flame(at + Vector3(cos(angle) * 0.10, 1.365, sin(angle) * 0.10), 0.28 + float(i % 3) * 0.08, float(i))
	var lamp := OmniLight3D.new()
	lamp.name = "BrazierGlow"
	lamp.position = at + Vector3(0, 1.64, 0)
	lamp.light_color = Color("ffc08a")
	lamp.light_energy = 1.45
	lamp.omni_range = 3.8
	lamp.omni_attenuation = 1.5
	lamp.light_size = 0.18
	lamp.shadow_enabled = true
	add_child(lamp)
	_lamps.append(lamp)

func _flame(at: Vector3, height: float, phase: float) -> void:
	# Tapered volumes remain flames from the back and sides, rather than camera cards.
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in 9:
		var t := float(row) / 8.0
		var radius := sin((t * 0.90 + 0.10) * PI) * 0.065 * (1.0 - t * 0.55)
		for column in 9:
			var angle := float(column) / 8.0 * TAU
			surface.set_uv(Vector2(float(column) / 8.0, t))
			surface.add_vertex(Vector3(cos(angle) * radius, height * t, sin(angle) * radius))
			if row > 0 and column > 0:
				var n := row * 9 + column
				for i in [n - 10, n - 1, n - 9, n - 9, n - 1, n]:
					surface.add_index(i)
	surface.generate_normals()
	var fire := ShaderMaterial.new()
	fire.shader = FIRE
	fire.set_shader_parameter("phase", phase)
	var flame := _mesh("BrazierFlame", surface.commit(), at, fire)
	flame.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

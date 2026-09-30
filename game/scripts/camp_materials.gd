extends RefCounted
## Reproducible, metre-scale materials; no image imports or random texture seeds.
## Keep separate shaders so canvas, timber, metal and soil age differently.

const WOOD: Shader = preload("res://shaders/camp_wood.gdshader")
const CLOTH: Shader = preload("res://shaders/camp_cloth.gdshader")
const BRONZE: Shader = preload("res://shaders/camp_bronze.gdshader")
const PARCHMENT: Shader = preload("res://shaders/camp_parchment.gdshader")
const GROUND: Shader = preload("res://shaders/camp_ground.gdshader")


static func wood(color: Color, vertical: bool = false) -> ShaderMaterial:
	var material := _make(WOOD, color)
	material.set_shader_parameter("vertical_grain", vertical)
	return material


static func cloth(color: Color) -> ShaderMaterial:
	return _make(CLOTH, color)


static func bronze(color: Color) -> ShaderMaterial:
	return _make(BRONZE, color)


static func parchment(color: Color) -> ShaderMaterial:
	return _make(PARCHMENT, color)


static func ground(color: Color) -> ShaderMaterial:
	return _make(GROUND, color)


static func _make(shader: Shader, color: Color) -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("base_color", color)
	return material

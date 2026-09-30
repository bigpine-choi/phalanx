shader_type spatial;
render_mode unshaded, cull_disabled, shadows_disabled, depth_draw_never;
uniform float phase = 0.0;
void vertex() {
	float tip = UV.y * UV.y;
	VERTEX.x += (sin(TIME * 3.6 + UV.y * 4.5 + phase) * 0.028 + sin(TIME * 1.6 + phase) * 0.012) * tip;
	VERTEX.z += cos(TIME * 2.7 + UV.y * 5.0 + phase) * 0.018 * tip;
	VERTEX.y *= 1.0 + sin(TIME * 4.1 + phase) * 0.055;
}
void fragment() {
	vec3 color = mix(vec3(1.0, 0.65, 0.19), vec3(0.9, 0.18, 0.025), smoothstep(0.1, 0.85, UV.y));
	ALBEDO = color;
	EMISSION = color * 0.8;
	ALPHA = (1.0 - smoothstep(0.55, 1.0, UV.y)) * 0.76;
}

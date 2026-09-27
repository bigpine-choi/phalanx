shader_type spatial;
render_mode cull_disabled;

uniform float phase = 0.0;

void vertex() {
	VERTEX.z += sin(TIME * 1.1 + UV.x * 6.0 + phase) * UV.x * 0.055;
	VERTEX.y -= UV.x * 0.055;
}

void fragment() {
	float border = max(step(0.92, UV.y), step(0.94, UV.x));
	ALBEDO = mix(vec3(0.28, 0.075, 0.085), vec3(0.55, 0.39, 0.20), border);
	ROUGHNESS = 0.98;
}

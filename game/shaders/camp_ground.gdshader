shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec4 base_color : source_color = vec4(0.54, 0.44, 0.30, 1.0);
varying vec3 world_position;

float hash21(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise2(vec2 p) {
	vec2 cell = floor(p);
	vec2 f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash21(cell), hash21(cell + vec2(1.0, 0.0)), u.x),
		mix(hash21(cell + vec2(0.0, 1.0)), hash21(cell + vec2(1.0)), u.x), u.y);
}

void vertex() { world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }

void fragment() {
	vec2 p = world_position.xz;
	float large_patch = noise2(p * 0.48 + vec2(7.0, 2.0));
	float small_patch = noise2(p * 3.1);
	float grit = noise2(p * 68.0);
	float grit_filter = 1.0 - smoothstep(0.3, 1.7, length(fwidth(p * 68.0)));
	// Only sheltered patches retain wind marks. Broad domain warping bends those
	// marks so a single regular wave cannot stripe the whole visible landscape.
	vec2 wind_warp = vec2(noise2(p * 0.13 + vec2(2.7, 8.1)), noise2(p * 0.11 + vec2(11.4, 3.5)));
	vec2 wind_position = p + (wind_warp - vec2(0.5)) * 2.3;
	float ripple_phase = dot(wind_position, vec2(5.3, 16.0)) + noise2(p * 0.7) * 3.0;
	float sheltered = smoothstep(0.30, 0.75, noise2(p * 0.24 + vec2(4.9, 2.3)));
	float trampled = 1.0 - smoothstep(0.42, 0.76, small_patch);
	float ripple = sin(ripple_phase) * sheltered * trampled;
	ripple *= 1.0 - smoothstep(0.7, 3.0, fwidth(ripple_phase));
	// Compacted earth patches dominate; sand grains and ridges remain subordinate.
	float value = 0.88 + large_patch * 0.18 + small_patch * 0.09;
	value += (grit - 0.5) * 0.08 * grit_filter + ripple * 0.0035;
	vec3 earth = base_color.rgb * vec3(0.90, 0.87, 0.82);
	ALBEDO = mix(base_color.rgb, earth, smoothstep(0.55, 0.9, small_patch) * 0.36) * value;
	ROUGHNESS = 0.97;
	SPECULAR = 0.13;
	float height = ripple * 0.00065 + small_patch * 0.004 + grit * 0.00028 * grit_filter;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 r1 = cross(dy, NORMAL);
	vec3 r2 = cross(NORMAL, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(NORMAL - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec4 base_color : source_color = vec4(0.30, 0.18, 0.095, 1.0);
uniform bool vertical_grain = false;
varying vec3 local_position;
varying vec3 local_normal;

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

void vertex() {
	local_position = VERTEX;
	local_normal = NORMAL;
}

void fragment() {
	vec3 face = abs(local_normal);
	// The first coordinate follows a board; the second crosses its fibres.
	vec2 p = face.y > 0.55 ? local_position.xz : local_position.xy;
	if (face.x > 0.55) { p = local_position.zy; }
	if (vertical_grain) {
		p = face.z > face.x ? local_position.yx : local_position.yz;
	}
	float board = floor((p.y + 0.14) / 0.28);
	float board_tone = hash21(vec2(board, 19.7));
	float warp = (noise2(vec2(p.x * 0.7, p.y * 2.4)) - 0.5) * 0.075;
	warp += sin(p.x * 1.65 + board_tone * 5.0) * 0.009;
	float grain_phase = (p.y + warp) * 245.0;
	float grain_filter = 1.0 - smoothstep(0.8, 3.4, fwidth(grain_phase));
	float grain = sin(grain_phase) * grain_filter;
	float finer_phase = (p.y + warp * 0.74) * 611.0;
	float fine = sin(finer_phase) * (1.0 - smoothstep(0.7, 3.0, fwidth(finer_phase)));
	float broad = noise2(vec2(p.x * 0.9, p.y * 17.0));
	float board_fraction = fract((p.y + 0.14) / 0.28);
	float seam_distance = min(board_fraction, 1.0 - board_fraction) * 0.28;
	float seam = 1.0 - smoothstep(0.001, 0.002 + fwidth(p.y), seam_distance);
	bool end_face = vertical_grain ? face.y > 0.65 : face.x > 0.65;
	if (end_face) {
		vec2 end_point = vertical_grain ? local_position.xz : local_position.zy;
		float ring_phase = length(end_point * vec2(1.0, 0.78) + vec2(0.12, 0.06)) * 172.0;
		ring_phase += noise2(end_point * 7.0) * 1.8;
		grain = sin(ring_phase) * (1.0 - smoothstep(0.8, 3.4, fwidth(ring_phase)));
		fine = 0.0;
		seam = 0.0;
	}
	// Sparse oval knots interrupt the long grain without peppering every surface.
	vec2 knot_center = vec2(0.63 + board_tone * 0.55, board * 0.28 - 0.025);
	float knot_radius = length((p - knot_center) * vec2(1.9, 6.5));
	float knot = (1.0 - smoothstep(0.09, 0.26, knot_radius)) * step(0.56, board_tone);
	float value = 0.94 + board_tone * 0.13 + grain * 0.064 + fine * 0.021;
	value += (broad - 0.5) * 0.17 - seam * 0.24 - knot * 0.23;
	ALBEDO = base_color.rgb * value;
	ROUGHNESS = clamp(0.79 + broad * 0.12 + seam * 0.07, 0.0, 1.0);
	SPECULAR = 0.24;
	float height = grain * 0.00022 + broad * 0.0008 - seam * 0.0012;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 r1 = cross(dy, NORMAL);
	vec3 r2 = cross(NORMAL, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(NORMAL - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

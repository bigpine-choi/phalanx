shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec4 base_color : source_color = vec4(0.78, 0.64, 0.41, 1.0);
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
	vec2 p = face.y > 0.55 ? local_position.xz : local_position.xy;
	if (face.x > 0.55) { p = local_position.zy; }
	float cloud = noise2(p * 3.8 + vec2(1.8, 4.1));
	float tide = smoothstep(0.43, 0.50, cloud) * (1.0 - smoothstep(0.50, 0.57, cloud));
	float fibers = noise2(p * vec2(170.0, 24.0));
	float fiber_filter = 1.0 - smoothstep(0.4, 1.8, length(fwidth(p * vec2(170.0, 24.0))));
	float grain = (fibers - 0.5) * fiber_filter;
	float value = 1.01 + (cloud - 0.5) * 0.22 - tide * 0.055 + grain * 0.047;
	ALBEDO = base_color.rgb * vec3(value, value - tide * 0.007, value - tide * 0.017);
	ROUGHNESS = 0.92;
	SPECULAR = 0.12;
	float height = cloud * 0.0006 + grain * 0.00018;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 r1 = cross(dy, NORMAL);
	vec3 r2 = cross(NORMAL, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(NORMAL - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

uniform vec4 base_color : source_color = vec4(0.61, 0.43, 0.21, 1.0);
varying vec3 local_position;

float hash31(vec3 p) {
	return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

float noise3(vec3 p) {
	vec3 cell = floor(p);
	vec3 f = fract(p);
	vec3 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(mix(hash31(cell), hash31(cell + vec3(1, 0, 0)), u.x),
		mix(hash31(cell + vec3(0, 1, 0)), hash31(cell + vec3(1, 1, 0)), u.x), u.y),
		mix(mix(hash31(cell + vec3(0, 0, 1)), hash31(cell + vec3(1, 0, 1)), u.x),
		mix(hash31(cell + vec3(0, 1, 1)), hash31(cell + vec3(1, 1, 1)), u.x), u.y), u.z);
}

void vertex() { local_position = VERTEX; }

void fragment() {
	float hammered = noise3(local_position * 82.0);
	float mottling = noise3(local_position * 19.0);
	float oxidation = smoothstep(0.53, 0.85, mottling) * 0.34;
	vec3 patina = base_color.rgb * vec3(0.54, 0.79, 0.82);
	ALBEDO = mix(base_color.rgb * (0.90 + hammered * 0.16), patina, oxidation);
	METALLIC = 0.65 - oxidation * 0.30;
	ROUGHNESS = 0.57 + mottling * 0.18 + oxidation * 0.16;
	SPECULAR = 0.30;
	float height = hammered * 0.00035;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 r1 = cross(dy, NORMAL);
	vec3 r2 = cross(NORMAL, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(NORMAL - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

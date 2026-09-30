shader_type sky;
uniform vec3 sun_direction = vec3(0.39, 0.23, 0.89);
uniform vec4 zenith_color : source_color = vec4(0.29, 0.39, 0.51, 1.0);
uniform vec4 horizon_color : source_color = vec4(0.83, 0.69, 0.51, 1.0);
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
	vec2 i = floor(p), f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0)), f.x), f.y);
}
void sky() {
	float elevation = max(EYEDIR.y, 0.0);
	vec3 color = mix(horizon_color.rgb, zenith_color.rgb, pow(clamp(elevation / 0.70, 0.0, 1.0), 0.58));
	float sun_dot = dot(EYEDIR, normalize(sun_direction));
	float glow = pow(max(sun_dot, 0.0), 28.0);
	color += vec3(0.22, 0.11, 0.035) * glow;
	vec2 p = EYEDIR.xz / max(0.10, elevation) * vec2(1.7, 5.2);
	float cloud = noise(p) * 0.57 + noise(p * 2.07 + 12.1) * 0.28 + noise(p * 4.3) * 0.15;
	float veil = smoothstep(0.48, 0.72, cloud) * smoothstep(0.035, 0.12, elevation) * (1.0 - smoothstep(0.42, 0.8, elevation));
	vec3 cloud_color = mix(vec3(0.27, 0.30, 0.36), vec3(0.68, 0.48, 0.29), glow);
	color = mix(color, cloud_color, veil * 0.43);
	float disc = smoothstep(0.99990, 0.999965, sun_dot);
	color += vec3(2.5, 1.8, 1.0) * disc;
	COLOR = mix(vec3(0.11, 0.105, 0.09), color, smoothstep(-0.05, 0.015, EYEDIR.y));
}

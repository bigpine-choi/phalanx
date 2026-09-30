shader_type spatial;
render_mode cull_disabled, diffuse_burley, specular_schlick_ggx;

uniform vec4 base_color : source_color = vec4(0.61, 0.49, 0.33, 1.0);
varying vec3 local_position;
varying vec3 local_normal;

void vertex() {
	local_position = VERTEX;
	local_normal = NORMAL;
}

void fragment() {
	vec3 face = abs(local_normal);
	vec2 p = face.y > 0.55 ? local_position.xz : local_position.xy;
	if (face.x > 0.55) { p = local_position.zy; }
	// Broad irregular folds, distinct from the cross-woven warp and weft.
	float crease_phase = p.x * 11.5 + sin(p.y * 1.9) * 0.45;
	float folds = sin(crease_phase) * 0.55 + sin(p.x * 23.0 + p.y * 1.3) * 0.18;
	float wear = sin(p.x * 1.7 + p.y * 0.55) * sin(p.y * 2.1 - p.x * 0.4);
	vec2 thread_phase = p * vec2(730.0, 805.0);
	vec2 thread_filter = vec2(1.0) - smoothstep(vec2(0.6), vec2(3.0), fwidth(thread_phase));
	float warp = sin(thread_phase.x) * thread_filter.x;
	float weft = sin(thread_phase.y) * thread_filter.y;
	float weave = (warp + weft) * 0.5;
	float cross_thread = warp * weft;
	ALBEDO = base_color.rgb * (0.99 + folds * 0.045 + wear * 0.045 + weave * 0.043 + cross_thread * 0.012);
	ROUGHNESS = clamp(0.91 + weave * 0.025, 0.0, 1.0);
	SPECULAR = 0.16;
	float height = folds * 0.004 + weave * 0.00012;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 n = FRONT_FACING ? NORMAL : -NORMAL;
	vec3 r1 = cross(dy, n);
	vec3 r2 = cross(n, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(n - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

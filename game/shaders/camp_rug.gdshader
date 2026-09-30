shader_type spatial;
render_mode diffuse_burley, specular_schlick_ggx;

// UV follows the woven surface, including its raised corner. Metre-scale motifs
// and filtered fibres keep the carpet readable both standing and close to it.
uniform vec4 red_color : source_color = vec4(0.30, 0.075, 0.095, 1.0);
uniform vec4 border_color : source_color = vec4(0.46, 0.335, 0.19, 1.0);
uniform vec4 dark_color : source_color = vec4(0.12, 0.07, 0.065, 1.0);

float hash21(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise2(vec2 p) {
	vec2 c = floor(p);
	vec2 f = fract(p);
	vec2 t = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash21(c), hash21(c + vec2(1.0, 0.0)), t.x),
		mix(hash21(c + vec2(0.0, 1.0)), hash21(c + vec2(1.0)), t.x), t.y);
}

float line(float distance_to_line, float width, float aa) {
	return 1.0 - smoothstep(width - aa, width + aa, distance_to_line);
}

void fragment() {
	vec2 p = UV * vec2(5.3, 4.36);
	vec2 edge = min(p, vec2(5.3, 4.36) - p);
	float d = min(edge.x, edge.y);
	float aa = max(length(fwidth(p)), 0.001);
	float field = smoothstep(0.42 - aa, 0.42 + aa, d);
	vec3 color = mix(dark_color.rgb, red_color.rgb, field);
	float borders = line(abs(d - 0.075), 0.012, aa) + line(abs(d - 0.37), 0.018, aa);
	float along_edge = edge.x < edge.y ? p.y : p.x;
	vec2 cell = vec2(fract(along_edge / 0.265), (d - 0.215) / 0.135);
	float diamond = abs(cell.x - 0.5) * 1.8 + abs(cell.y) * 0.55;
	float border_motif = line(abs(diamond - 0.50), 0.06, aa * 5.0);
	border_motif *= smoothstep(0.10, 0.125, d) * (1.0 - smoothstep(0.315, 0.34, d));
	vec2 field_cell = fract((p + vec2(0.08, 0.03)) / vec2(0.58, 0.58)) - 0.5;
	float field_diamond = abs(field_cell.x) + abs(field_cell.y);
	float field_motif = line(abs(field_diamond - 0.21), 0.018, aa * 1.8) * field;
	float wear = noise2(p * 2.1) * 0.55 + noise2(p * 9.0) * 0.25;
	float motif = clamp(borders + border_motif + field_motif * 0.22, 0.0, 1.0);
	color = mix(color, border_color.rgb, motif * (0.60 + wear * 0.32));
	vec2 phase = p * vec2(1250.0, 1370.0);
	vec2 filter_width = vec2(1.0) - smoothstep(vec2(0.8), vec2(3.0), fwidth(phase));
	float warp = sin(phase.x) * filter_width.x;
	float weft = sin(phase.y) * filter_width.y;
	float weave = (warp + weft) * 0.5;
	ALBEDO = color * (0.91 + wear * 0.15 + weave * 0.065);
	ROUGHNESS = 0.96;
	SPECULAR = 0.10;
	float height = weave * 0.00016 + motif * 0.0008;
	vec3 dx = dFdx(VERTEX);
	vec3 dy = dFdy(VERTEX);
	vec3 r1 = cross(dy, NORMAL);
	vec3 r2 = cross(NORMAL, dx);
	float det = dot(dx, r1);
	NORMAL = normalize(NORMAL - sign(det) * (dFdx(height) * r1 + dFdy(height) * r2) / max(abs(det), 0.00001));
}

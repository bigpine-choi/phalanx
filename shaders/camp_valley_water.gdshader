shader_type spatial;

varying vec3 world_position;

void vertex() {
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	VERTEX.y += sin(world_position.x * 2.4 + TIME * 0.35) * 0.004;
}

void fragment() {
	float ripples = sin(world_position.z * 13.0 + sin(world_position.x * 3.4) * 0.9 + TIME * 0.24);
	float broad_reflection = 0.5 + 0.5 * sin(world_position.x * 0.73 + world_position.z * 0.09);
	ALBEDO = mix(vec3(0.12, 0.22, 0.24), vec3(0.25, 0.31, 0.30), broad_reflection * 0.55);
	ALBEDO += vec3(0.038, 0.035, 0.030) * pow(max(0.0, ripples), 8.0);
	METALLIC = 0.02;
	SPECULAR = 0.12;
	ROUGHNESS = 0.47 + ripples * 0.045;
}

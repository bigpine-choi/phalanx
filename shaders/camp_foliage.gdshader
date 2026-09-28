shader_type canvas_item;
render_mode unshaded;

// This shader samples the unmodified camp painting in its original UV space.
// Olive leaves have much less red/green separation than the ochre dirt seen
// through them. A gradual key retains the source leaf colour while opening
// those dirt gaps; very dark branches are protected from the key.
void fragment() {
	vec4 painted = texture(TEXTURE, UV);
	float warmth = (painted.r - painted.g) / max(painted.g - painted.b, 0.035);
	float leaf_alpha = 1.0 - smoothstep(0.36, 0.69, warmth);
	float branch_alpha = 1.0 - smoothstep(0.16, 0.29, max(painted.r, max(painted.g, painted.b)));
	painted.a *= max(leaf_alpha, branch_alpha);
	COLOR = painted;
}

# Camp supply chest

Prototype prop created with Tripo H2.5 on 2026-09-29 and prepared in Blender 5.2.2 LTS.

- Source model: https://studio.tripo3d.ai/ko/workspace/generate/af81f1ef-a882-498c-be67-374fa72319d7
- Tripo Free plan: public generation; non-commercial use. This is a learning/prototype asset, not cleared for a commercial release. See https://www.tripo3d.ai/pricing for the plan conditions.
- Generation: 40 free credits; one GLB export. No paid subscription or add-on.
- Original: 501,110 triangles, 4K textures, 20,082,740 bytes.
- Game model: 12,000 triangles, 1K base colour/normal/roughness-metallic textures, 3,195,028 bytes.
- Approximate dimensions: 0.90 m wide × 0.50 m deep × 0.55 m high. Origin at ground centre. glTF uses metres and Y-up.
- Blender preparation: applied dimensions; Decimate collapse while retaining UVs; smooth normals; resized and packed textures; exported selected mesh as GLB.
- The editable `.blend` and untouched source GLB are delivered separately in the Codex task's `outputs/hq-chest` folder. The game only imports this optimized GLB.

`scripts/camp_supply_chest.gd` renders the static 3D asset to a transparent viewport once on camp entry, sharing the avatar camera elevation, world scale and authored sunlight field. `scripts/quarter_camp.gd` places it beside the right supply stacks at source-art coordinates (1150, 493). Its projected ground footprint blocks navigation, and its silhouette blocks movement clicks. The analysis-room placement was removed. It is decorative; no inventory interaction is added.

## Generation prompt

One standalone closed wooden military supply chest for a stylized ancient Macedonian headquarters. A squat rectangular chest made of thick dark walnut planks, aged bronze corner brackets, two bronze reinforcing bands, a simple central bronze latch, and recessed side handles. Restrained Hellenistic ornament, practical craftsmanship, subtle wear, rich brown wood and muted warm bronze. Strong readable silhouette with softly beveled edges. Width 0.9 m, depth 0.5 m, height 0.55 m. Flat solid underside. Lid closed. Complete geometry on all sides. PBR wood grain and metal roughness, neutral texture lighting without baked cast shadows. Single game prop only. No people, weapons, cloth, coins, terrain, pedestal, scenery, lettering, logos, or background geometry. No animation.

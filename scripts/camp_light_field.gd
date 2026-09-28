extends RefCounted
## Authored SUN OCCLUSION on the painted ground, not a brightness lookup.
## Coordinates are source-image pixels (1672 x 941), like the walk/foreground
## polygons. Dark dirt, props and UI must not become accidental shadow casters.
## Re-author these footprints if the camp painting or its sun direction changes.

const ART_SCALE := 1600.0 / 1672.0
const ART_OFFSET := Vector2(0, (900.0 - 941.0 * ART_SCALE) * 0.5)
var regions: Array[Dictionary] = [
	{"name": "right_canopy", "occlusion": 0.86, "feather": 16.0, "polygon": PackedVector2Array([
		Vector2(1233,414), Vector2(1175,426), Vector2(1108,434), Vector2(1090,453),
		Vector2(1013,465), Vector2(984,490), Vector2(924,505), Vector2(937,518),
		Vector2(850,539), Vector2(812,562), Vector2(847,580), Vector2(939,573),
		Vector2(991,601), Vector2(1042,615), Vector2(1134,608), Vector2(1211,631),
		Vector2(1282,601), Vector2(1328,538), Vector2(1390,532), Vector2(1360,464)])},
	{"name": "wall_tree", "occlusion": 0.78, "feather": 13.0, "polygon": PackedVector2Array([
		Vector2(1180,333), Vector2(1100,342), Vector2(1042,354), Vector2(949,366),
		Vector2(889,381), Vector2(890,398), Vector2(960,421), Vector2(1037,425),
		Vector2(1128,406), Vector2(1195,389)])},
	{"name": "foreground_cypress", "occlusion": 0.84, "feather": 15.0, "polygon": PackedVector2Array([
		Vector2(1337,704), Vector2(1222,735), Vector2(1174,765), Vector2(1188,787),
		Vector2(1240,787), Vector2(1233,828), Vector2(1170,861), Vector2(1073,892),
		Vector2(1013,941), Vector2(1181,941), Vector2(1301,847)])},
	{"name": "chest", "occlusion": 0.84, "feather": 7.0, "polygon": PackedVector2Array([
		Vector2(1372,616), Vector2(1322,627), Vector2(1282,641), Vector2(1224,651),
		Vector2(1166,674), Vector2(1186,692), Vector2(1253,688), Vector2(1304,670),
		Vector2(1354,676), Vector2(1411,650)])},
	{"name": "olive_canopy", "occlusion": 0.80, "feather": 18.0, "polygon": PackedVector2Array([
		Vector2(402,499), Vector2(447,450), Vector2(550,438), Vector2(622,456),
		Vector2(678,490), Vector2(718,548), Vector2(719,600), Vector2(684,617),
		Vector2(625,640), Vector2(579,648), Vector2(496,612), Vector2(434,572)])},
	{"name": "headquarters_threshold", "occlusion": 0.65, "feather": 8.0, "polygon": PackedVector2Array([
		Vector2(566,312), Vector2(695,282), Vector2(764,311), Vector2(787,349),
		Vector2(694,366), Vector2(623,350)])}
]

func sunlight_at(authored_ground: Vector2) -> float:
	var source := (authored_ground - ART_OFFSET) / ART_SCALE
	# A footprint, not a single texel. Texture grain cannot cause flickering.
	var sunlight := _sample_source(source) * 0.4
	for offset: Vector2 in [Vector2(-8,0), Vector2(8,0), Vector2(0,-5), Vector2(0,5)]:
		sunlight += _sample_source(source + offset) * 0.15
	return clampf(sunlight, 0.0, 1.0)

func _sample_source(point: Vector2) -> float:
	var blocked := 0.0
	for region: Dictionary in regions:
		var polygon: PackedVector2Array = region.polygon
		var distance := INF
		for index: int in polygon.size():
			var closest := Geometry2D.get_closest_point_to_segment(point, polygon[index], polygon[(index + 1) % polygon.size()])
			distance = minf(distance, point.distance_to(closest))
		if not Geometry2D.is_point_in_polygon(point, polygon):
			distance = -distance
		var coverage := smoothstep(-float(region.feather), float(region.feather), distance)
		# Overlapping silhouettes describe the same sun; don't double-darken them.
		blocked = maxf(blocked, coverage * float(region.occlusion))
	return 1.0 - blocked

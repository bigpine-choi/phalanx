extends RefCounted
## A few registered cutouts of the existing painting, not a second background.
## Coordinates and depth baselines are authored in the source image's pixels.

const FOLIAGE_SHADER = preload("res://shaders/camp_foliage.gdshader")


static func build(texture: Texture2D, art_scale: float, art_offset: Vector2) -> Array[Polygon2D]:
	var result: Array[Polygon2D] = []
	if texture == null:
		return result
	# The olive canopy follows clusters instead of spanning them with a broad hull.
	# Its shader reveals the dirt visible between branches; trunks remain solid.
	result.append(_cutout(texture, art_scale, art_offset, "OliveCanopy", PackedVector2Array([
		Vector2(388, 452), Vector2(410, 446), Vector2(411, 429), Vector2(432, 433),
		Vector2(429, 415), Vector2(439, 401), Vector2(459, 407), Vector2(466, 418),
		Vector2(484, 410), Vector2(491, 396), Vector2(510, 397), Vector2(525, 411),
		Vector2(543, 407), Vector2(558, 399), Vector2(574, 408), Vector2(576, 428),
		Vector2(598, 425), Vector2(613, 441), Vector2(634, 450), Vector2(642, 470),
		Vector2(659, 465), Vector2(672, 485), Vector2(687, 492), Vector2(686, 511),
		Vector2(706, 513), Vector2(716, 529), Vector2(701, 542), Vector2(698, 557),
		Vector2(681, 565), Vector2(669, 580), Vector2(648, 575), Vector2(637, 597),
		Vector2(620, 595), Vector2(624, 630), Vector2(611, 644), Vector2(591, 646),
		Vector2(576, 655), Vector2(554, 645), Vector2(536, 645), Vector2(520, 632),
		Vector2(497, 640), Vector2(481, 627), Vector2(449, 625), Vector2(434, 607),
		Vector2(439, 589), Vector2(419, 581), Vector2(410, 560), Vector2(396, 554),
		Vector2(397, 536), Vector2(383, 527), Vector2(389, 511), Vector2(379, 496),
		Vector2(389, 480), Vector2(381, 467)
	]), 646.0, true))
	result.append(_cutout(texture, art_scale, art_offset, "LeftSupplyCrates", PackedVector2Array([
		Vector2(199, 479), Vector2(218, 471), Vector2(228, 457), Vector2(240, 451),
		Vector2(278, 453), Vector2(287, 449), Vector2(316, 457), Vector2(323, 447),
		Vector2(335, 447), Vector2(341, 456), Vector2(338, 469), Vector2(348, 475),
		Vector2(387, 486), Vector2(393, 542), Vector2(401, 550), Vector2(410, 567),
		Vector2(395, 615), Vector2(349, 621), Vector2(211, 615), Vector2(205, 557)
	]), 620.0))
	result.append(_cutout(texture, art_scale, art_offset, "RightSupplyCrates", PackedVector2Array([
		Vector2(1188, 376), Vector2(1206, 367), Vector2(1209, 350), Vector2(1226, 348),
		Vector2(1230, 337), Vector2(1245, 333), Vector2(1248, 321), Vector2(1260, 317),
		Vector2(1287, 321), Vector2(1298, 333), Vector2(1296, 353), Vector2(1306, 360),
		Vector2(1313, 350), Vector2(1337, 346), Vector2(1341, 403), Vector2(1334, 415),
		Vector2(1345, 434), Vector2(1344, 475), Vector2(1312, 484), Vector2(1267, 477),
		Vector2(1225, 463), Vector2(1186, 443)
	]), 481.0))
	# Follow the pot separately from the chest shoulder: no triangular dirt wedge.
	result.append(_cutout(texture, art_scale, art_offset, "ForegroundChest", PackedVector2Array([
		Vector2(1349, 554), Vector2(1391, 545), Vector2(1393, 537), Vector2(1389, 528),
		Vector2(1392, 520), Vector2(1403, 518), Vector2(1409, 524), Vector2(1418, 522),
		Vector2(1426, 518), Vector2(1433, 524), Vector2(1433, 535), Vector2(1423, 544),
		Vector2(1424, 550), Vector2(1463, 567), Vector2(1458, 626), Vector2(1428, 647),
		Vector2(1351, 631)
	]), 647.0))
	return result


static func _cutout(texture: Texture2D, art_scale: float, art_offset: Vector2,
		label: String, source: PackedVector2Array, baseline: float, foliage := false) -> Polygon2D:
	var mask := Polygon2D.new()
	mask.name = label
	mask.texture = texture
	mask.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	var points := PackedVector2Array()
	for point: Vector2 in source:
		points.append(point * art_scale + art_offset)
	mask.polygon = points
	mask.uv = source
	mask.z_index = int(baseline * art_scale + art_offset.y)
	if foliage:
		var material := ShaderMaterial.new()
		material.shader = FOLIAGE_SHADER
		mask.material = material
	return mask

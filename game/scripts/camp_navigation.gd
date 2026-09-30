extends RefCounted
## Ground navigation in the same authored 1600 x 900 space as the camp painting.
## Navigation is deliberately limited to the clearing, not the distant camp.

const CANVAS_SIZE := Vector2(1600, 900)
const CELL_SIZE := 12.0
const ACTOR_RADIUS := 12.0

var walk_polygon := PackedVector2Array()
var blocked_polygons: Array[PackedVector2Array] = []
var grid := AStarGrid2D.new()


func configure(ground: PackedVector2Array, obstacles: Array[PackedVector2Array]) -> void:
	walk_polygon = ground
	blocked_polygons = obstacles
	grid.region = Rect2i(0, 0, int(CANVAS_SIZE.x / CELL_SIZE) + 1, int(CANVAS_SIZE.y / CELL_SIZE) + 1)
	grid.cell_size = Vector2.ONE * CELL_SIZE
	grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
	grid.default_compute_heuristic = AStarGrid2D.HEURISTIC_OCTILE
	grid.default_estimate_heuristic = AStarGrid2D.HEURISTIC_OCTILE
	grid.update()
	for y: int in range(grid.region.size.y):
		for x: int in range(grid.region.size.x):
			var cell := Vector2i(x, y)
			grid.set_point_solid(cell, not is_walkable(Vector2(cell) * CELL_SIZE))


func is_walkable(point: Vector2, radius: float = ACTOR_RADIUS) -> bool:
	if walk_polygon.size() < 3 or not Geometry2D.is_point_in_polygon(point, walk_polygon):
		return false
	if _near_boundary(point, walk_polygon, radius):
		return false
	for obstacle: PackedVector2Array in blocked_polygons:
		if Geometry2D.is_point_in_polygon(point, obstacle) or _near_boundary(point, obstacle, radius):
			return false
	return true


func path_to(origin: Vector2, destination: Vector2) -> PackedVector2Array:
	if not is_walkable(destination):
		return PackedVector2Array()
	var start_cell := _nearest_open_cell(origin)
	var end_cell := _nearest_open_cell(destination)
	if start_cell.x < 0 or end_cell.x < 0:
		return PackedVector2Array()
	var raw := grid.get_point_path(start_cell, end_cell)
	if raw.is_empty():
		return PackedVector2Array()
	# Include the actual endpoints; grid coordinates never become a visible snap.
	raw.insert(0, origin)
	if not line_is_clear(raw[raw.size() - 1], destination):
		return PackedVector2Array()
	raw.append(destination)
	var result := PackedVector2Array([origin])
	var cursor := 0
	while cursor < raw.size() - 1:
		var farthest := cursor + 1
		if not line_is_clear(raw[cursor], raw[farthest]):
			return PackedVector2Array()
		for next: int in range(cursor + 2, raw.size()):
			if line_is_clear(raw[cursor], raw[next]):
				farthest = next
			else:
				break
		result.append(raw[farthest])
		cursor = farthest
	return result


func line_is_clear(from: Vector2, to: Vector2) -> bool:
	var steps := maxi(1, int(ceil(from.distance_to(to) / 3.0)))
	for step: int in range(steps + 1):
		if not is_walkable(from.lerp(to, float(step) / steps)):
			return false
	return true


func _nearest_open_cell(point: Vector2) -> Vector2i:
	var nearest := Vector2i((point / CELL_SIZE).round())
	var best := Vector2i(-1, -1)
	var best_distance := INF
	for y: int in range(nearest.y - 3, nearest.y + 4):
		for x: int in range(nearest.x - 3, nearest.x + 4):
			var cell := Vector2i(x, y)
			if not grid.is_in_boundsv(cell) or grid.is_point_solid(cell):
				continue
			var ground := Vector2(cell) * CELL_SIZE
			var distance := ground.distance_squared_to(point)
			if distance < best_distance and line_is_clear(point, ground):
				best = cell
				best_distance = distance
	return best


func _near_boundary(point: Vector2, polygon: PackedVector2Array, distance: float) -> bool:
	for index: int in range(polygon.size()):
		var nearest := Geometry2D.get_closest_point_to_segment(point, polygon[index], polygon[(index + 1) % polygon.size()])
		if point.distance_squared_to(nearest) < distance * distance:
			return true
	return false

extends Control
## Engraved timber desk under the readable document panels.
const T := preload("res://scripts/terminal_theme.gd")

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	resized.connect(queue_redraw)

func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), T.BG)
	for y: int in range(0, int(size.y), 5):
		var grain := 0.012 + 0.012 * sin(float(y) * 1.73)
		draw_line(Vector2(0, y), Vector2(size.x, y + 1), Color(T.GOLD, grain), 1)
	draw_rect(Rect2(Vector2(3,3), size - Vector2(6,6)), T.BORDER, false, 1)
	draw_rect(Rect2(Vector2(7,7), size - Vector2(14,14)), Color(T.GOLD, 0.17), false, 1)
	for corner: Vector2 in [Vector2(12,12), Vector2(size.x-12,12), Vector2(12,size.y-12), size-Vector2(12,12)]:
		var direction := Vector2(1 if corner.x < size.x/2 else -1, 1 if corner.y < size.y/2 else -1)
		draw_line(corner, corner + Vector2(direction.x*27,0), T.GOLD, 2)
		draw_line(corner, corner + Vector2(0,direction.y*27), T.GOLD, 2)
		draw_circle(corner + direction*5, 1.5, T.GOLD)

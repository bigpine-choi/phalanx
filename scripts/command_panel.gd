extends PanelContainer
## Brass inlay and corner pins remain quiet around text and numbers.
const T := preload("res://scripts/terminal_theme.gd")

func _ready() -> void:
	resized.connect(queue_redraw)

func _draw() -> void:
	for y: int in range(5, int(size.y)-4, 7):
		draw_line(Vector2(3, y), Vector2(size.x-3, y), Color(T.GOLD, 0.015), 1)
	draw_line(Vector2(12,1), Vector2(minf(80,size.x-12),1), Color(T.GOLD,0.7), 1)
	for x: float in [5.0, size.x-5.0]:
		for y: float in [5.0, size.y-5.0]:
			draw_circle(Vector2(x,y), 1.2, Color(T.GOLD,0.6))

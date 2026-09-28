extends Node2D
## Restrained motion in a fixed picture plane. Coordinates share the artwork transform.

var flames: Array[Vector2] = []
var dust_rect := Rect2(370, 190, 850, 480)
var _elapsed := 0.0
var enabled := true

func _process(delta: float) -> void:
	if enabled:
		_elapsed += delta
		queue_redraw()

func _draw() -> void:
	for index in 24:
		var t := float(index)
		var point := dust_rect.position + Vector2(fposmod(t * 127.1 + _elapsed * (2.0 + fmod(t, 3.0)), dust_rect.size.x), fposmod(t * 61.7 - _elapsed * 3.2, dust_rect.size.y))
		var fade := 0.045 + 0.035 * sin(_elapsed * 0.6 + t)
		draw_circle(point, 1.0 + fmod(t, 2.0) * 0.6, Color(1.0, 0.88, 0.60, fade))
	for index in flames.size():
		var at := flames[index]
		var flicker := 0.5 + 0.5 * sin(_elapsed * 4.1 + index * 2.7)
		for radius in range(4, 0, -1):
			draw_circle(at + Vector2(0, -7), radius * 9.0, Color(1.0, 0.54, 0.19, 0.012 + flicker * 0.005))
		for tongue in 3:
			var offset := Vector2(float(tongue - 1) * 6.0, 0)
			var height := 16.0 + sin(_elapsed * 5.4 + tongue * 2.8 + index) * 4.0
			var lean := sin(_elapsed * 3.8 + tongue) * 3.5
			var points := PackedVector2Array([at + offset + Vector2(-4, 0), at + offset + Vector2(-3, -height * 0.45), at + offset + Vector2(lean, -height), at + offset + Vector2(4, -height * 0.35), at + offset + Vector2(4, 0)])
			draw_colored_polygon(points, Color(1.0, 0.65 + tongue * 0.055, 0.24, 0.75))
			draw_circle(at + offset + Vector2(0, -3), 3.1, Color(1.0, 0.90, 0.61, 0.92))

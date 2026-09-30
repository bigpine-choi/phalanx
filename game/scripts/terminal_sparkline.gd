extends Control
## Small non-interactive trend chart. Values are explicitly demo fixtures.
var values: PackedFloat32Array = []
var line_color := Color("5ed6ba")

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	resized.connect(queue_redraw)

func _draw() -> void:
	if values.size() < 2:
		return
	var low := values[0]
	var high := values[0]
	for value: float in values:
		low = minf(low,value)
		high = maxf(high,value)
	var points := PackedVector2Array()
	for index: int in values.size():
		points.append(Vector2(float(index)/float(values.size()-1)*size.x, size.y-3.0-(values[index]-low)/maxf(high-low,0.001)*(size.y-6.0)))
	var fill := points.duplicate()
	fill.append(Vector2(size.x,size.y))
	fill.append(Vector2(0,size.y))
	draw_colored_polygon(fill,Color(line_color,0.07))
	draw_polyline(points,line_color,1.6,true)
	draw_circle(points[-1],2,line_color)

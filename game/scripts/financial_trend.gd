extends Control
const T = preload("res://scripts/terminal_theme.gd")
var rows: Array = []
var chart_font: Font = T.font(true)

func _ready() -> void:
	custom_minimum_size = Vector2(260,135)
	resized.connect(queue_redraw)
	mouse_filter = Control.MOUSE_FILTER_IGNORE

func set_rows(value: Array) -> void:
	rows = value
	queue_redraw()

func _draw() -> void:
	if rows.is_empty():
		draw_string(chart_font,Vector2(10,50),"자료 없음",HORIZONTAL_ALIGNMENT_LEFT,-1,14,T.MUTED)
		return
	var peak := 1.0
	var negative := false
	for row: Dictionary in rows:
		for key: String in ["revenue","operating_profit","operating_cash_flow"]:
			if row.get(key)!=null:
				peak = maxf(peak,absf(float(row[key])))
				negative = negative or float(row[key])<0
	var baseline := size.y-24 if not negative else (size.y-12)/2
	var height := baseline-12 if not negative else minf(baseline-12,size.y-24-baseline)
	draw_line(Vector2(0,baseline),Vector2(size.x,baseline),T.BORDER,1)
	var group_width := size.x/rows.size()
	for index: int in rows.size():
		var row: Dictionary = rows[index]
		var keys := ["revenue","operating_profit","operating_cash_flow"]
		var colors := [T.MUTED,T.ACCENT,T.GOLD]
		for series: int in 3:
			var value: Variant = row.get(keys[series])
			if value==null:
				continue
			var y_size := float(value)/peak*height
			var x := group_width*(index+0.5)+(series-1)*18-7
			draw_rect(Rect2(x,minf(baseline,baseline-y_size),14,maxf(1,absf(y_size))),colors[series])
		draw_string(chart_font,Vector2(group_width*(index+0.5)-15,size.y-4),str(row.year),HORIZONTAL_ALIGNMENT_LEFT,-1,11,T.MUTED)

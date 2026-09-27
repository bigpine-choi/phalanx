extends Control

const Data = preload("res://scripts/demo_data.gd")
const UP := Color("58d4b3")
const DOWN := Color("ee8592")
const MUTED := Color("8396ad")
var candles: Array = []
var days := 66
var show_average := true
var hover_index := -1
var full_history: Array = []

func _ready() -> void:
	custom_minimum_size = Vector2(380, 292)
	mouse_filter = Control.MOUSE_FILTER_STOP
	mouse_exited.connect(func(): hover_index = -1; queue_redraw())
	resized.connect(queue_redraw)

func set_stock(index: int) -> void:
	full_history = Data.history(index)
	set_period(days)

func set_period(value: int) -> void:
	days = value
	candles = full_history.slice(maxi(0, full_history.size() - days))
	hover_index = -1
	queue_redraw()

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and not candles.is_empty():
		var plot_width := size.x - 82.0
		hover_index = clampi(int((event.position.x - 8.0) / plot_width * candles.size()), 0, candles.size() - 1)
		queue_redraw()

func _draw() -> void:
	if candles.is_empty():
		return
	var font := get_theme_default_font()
	var plot := Rect2(8, 34, size.x - 82, size.y - 113)
	var low := INF
	var high := -INF
	var averages: Array[float] = []
	var offset := full_history.size() - candles.size()
	for i in range(candles.size()):
		var average := 0.0
		var count := 0
		for j in range(maxi(0, offset + i - 19), offset + i + 1):
			average += full_history[j].close
			count += 1
		averages.append(average / count)
		if show_average:
			low = minf(low, average / count)
			high = maxf(high, average / count)
	for candle in candles:
		low = minf(low, candle.low)
		high = maxf(high, candle.high)
	var padding := (high - low) * 0.10
	low -= padding
	high += padding
	var price_y := func(value: float) -> float: return plot.end.y - (value - low) / (high - low) * plot.size.y
	for i in range(5):
		var y := plot.position.y + plot.size.y * i / 4.0
		draw_line(Vector2(plot.position.x, y), Vector2(plot.end.x, y), Color("223045"), 1)
		draw_string(font, Vector2(plot.end.x + 10, y + 5), Data.money(high - (high - low) * i / 4.0), HORIZONTAL_ALIGNMENT_LEFT, -1, 11, MUTED)
	var step := plot.size.x / candles.size()
	var average_points := PackedVector2Array()
	for i in range(candles.size()):
		var candle: Dictionary = candles[i]
		var x := plot.position.x + (i + 0.5) * step
		var color := UP if candle.close >= candle.open else DOWN
		draw_line(Vector2(x, price_y.call(candle.high)), Vector2(x, price_y.call(candle.low)), color, 1)
		var top := minf(price_y.call(candle.open), price_y.call(candle.close))
		var height := maxf(1.5, absf(price_y.call(candle.close) - price_y.call(candle.open)))
		draw_rect(Rect2(x - maxf(1, step * 0.29), top, maxf(2, step * 0.58), height), color)
		draw_rect(Rect2(x - maxf(1, step * 0.29), size.y - 30 - candle.volume * 38, maxf(2, step * 0.58), candle.volume * 38), Color(color, 0.35))
		average_points.append(Vector2(x, price_y.call(averages[i])))
	if show_average and average_points.size() > 1:
		draw_polyline(average_points, Color("d4b678"), 1.6, true)
	draw_string(font, Vector2(8, size.y - 7), "%d거래일 전" % (candles.size() - 1), HORIZONTAL_ALIGNMENT_LEFT, -1, 11, MUTED)
	draw_string(font, Vector2(plot.end.x - 59, size.y - 7), "기준일", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, MUTED)
	var current: Dictionary = candles[hover_index if hover_index >= 0 else -1]
	var caption := "시가 %s   고가 %s   저가 %s   종가 %s" % [Data.money(current.open), Data.money(current.high), Data.money(current.low), Data.money(current.close)]
	draw_string(font, Vector2(8, 17), caption, HORIZONTAL_ALIGNMENT_LEFT, plot.size.x, 11, MUTED)
	if hover_index >= 0:
		var x := plot.position.x + (hover_index + 0.5) * step
		draw_dashed_line(Vector2(x, plot.position.y), Vector2(x, size.y - 27), Color("8aa2b8"), 1, 4)
		draw_circle(Vector2(x, price_y.call(current.close)), 3.5, Color("e3edf6"))

extends Control
const Data = preload("res://scripts/demo_data.gd")
const T = preload("res://scripts/terminal_theme.gd")
const UP := T.ACCENT
const DOWN := T.RED
var candles: Array = []
var days := 66
var show_average := true
var display_mode := "candles"
var hover_index := -1
var full_history: Array = []
var chart_font: Font = T.font(true)

func _ready() -> void:
	custom_minimum_size = Vector2(260,190)
	mouse_filter = Control.MOUSE_FILTER_STOP
	mouse_exited.connect(func() -> void: hover_index=-1; queue_redraw())
	resized.connect(queue_redraw)

func set_stock(index: int) -> void:
	full_history = Data.history(index)
	set_period(days)

func set_history(value: Array) -> void:
	full_history = value.duplicate(true)
	set_period(days)

func set_period(value: int) -> void:
	days = value
	candles = full_history.slice(maxi(0,full_history.size()-days))
	hover_index = -1
	queue_redraw()

func plot_rect() -> Rect2:
	return Rect2(4,29,maxf(1,size.x-78),maxf(1,size.y-101))

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and not candles.is_empty():
		var plot := plot_rect()
		hover_index = clampi(int((event.position.x-plot.position.x)/plot.size.x*candles.size()),0,candles.size()-1) if plot.has_point(event.position) else -1
		queue_redraw()

func _draw() -> void:
	if candles.is_empty():
		return
	var font := chart_font
	var plot := plot_rect()
	var low := INF
	var high := -INF
	var averages: Array[float] = []
	var offset := full_history.size()-candles.size()
	for index: int in candles.size():
		var average := 0.0
		var count := 0
		for j: int in range(maxi(0,offset+index-19),offset+index+1):
			average += full_history[j].close
			count += 1
		averages.append(average/count if count==20 else NAN)
		if show_average and count==20:
			low = minf(low,average/count)
			high = maxf(high,average/count)
	for candle: Dictionary in candles:
		low = minf(low,candle.low)
		high = maxf(high,candle.high)
	var padding := maxf((high-low)*0.12,1)
	low -= padding
	high += padding
	var price_y := func(value: float) -> float: return plot.end.y-(value-low)/(high-low)*plot.size.y
	for index: int in 5:
		var y := plot.position.y+plot.size.y*float(index)/4.0
		draw_line(Vector2(plot.position.x,y),Vector2(plot.end.x,y),Color("25323f"),1)
		draw_string(font,Vector2(plot.end.x+10,y+4),Data.money(high-(high-low)*float(index)/4),HORIZONTAL_ALIGNMENT_LEFT,-1,11,T.MUTED)
	var volume_max := 1.0
	for candle: Dictionary in candles:
		volume_max = maxf(volume_max,float(candle.volume))
	var step := plot.size.x/candles.size()
	var average_points := PackedVector2Array()
	var close_points := PackedVector2Array()
	for index: int in candles.size():
		var candle: Dictionary = candles[index]
		var x := plot.position.x+(index+0.5)*step
		var color := UP if candle.close>=candle.open else DOWN
		if display_mode == "candles":
			draw_line(Vector2(x,price_y.call(candle.high)),Vector2(x,price_y.call(candle.low)),color,1)
			var top := minf(price_y.call(candle.open),price_y.call(candle.close))
			var height := maxf(1.5,absf(price_y.call(candle.close)-price_y.call(candle.open)))
			draw_rect(Rect2(x-maxf(0.5,step*0.29),top,maxf(1,step*0.58),height),color)
		draw_rect(Rect2(x-maxf(0.5,step*0.29),size.y-20-candle.volume/volume_max*34,maxf(1,step*0.58),candle.volume/volume_max*34),Color(color,0.28))
		if is_finite(averages[index]):
			average_points.append(Vector2(x,price_y.call(averages[index])))
		close_points.append(Vector2(x,price_y.call(candle.close)))
	if display_mode == "line" and close_points.size()>1:
		var fill := close_points.duplicate()
		fill.append(Vector2(close_points[-1].x,plot.end.y))
		fill.append(Vector2(close_points[0].x,plot.end.y))
		draw_colored_polygon(fill,Color(UP,0.07))
		draw_polyline(close_points,UP,2,true)
	if show_average and average_points.size()>1:
		draw_polyline(average_points,T.GOLD,1.4,true)
	var last_y: float = price_y.call(candles[-1].close)
	draw_dashed_line(Vector2(plot.position.x,last_y),Vector2(plot.end.x,last_y),Color(UP,0.3),1,4)
	draw_rect(Rect2(plot.end.x+5,last_y-8,68,17),Color("1b4038"))
	draw_string(font,Vector2(plot.end.x+10,last_y+4),Data.money(candles[-1].close),HORIZONTAL_ALIGNMENT_LEFT,-1,11,UP)
	draw_string(font,Vector2(4,size.y-3),str(candles[0].get("date","-%dD" % (candles.size()-1))),HORIZONTAL_ALIGNMENT_LEFT,-1,10,T.MUTED)
	draw_string(font,Vector2(plot.end.x-65,size.y-3),str(candles[-1].get("date","T0")),HORIZONTAL_ALIGNMENT_LEFT,-1,10,T.MUTED)
	var current: Dictionary = candles[hover_index if hover_index>=0 else -1]
	var caption := "O %s   H %s   L %s   C %s" % [Data.money(current.open),Data.money(current.high),Data.money(current.low),Data.money(current.close)]
	draw_string(font,Vector2(4,14),caption,HORIZONTAL_ALIGNMENT_LEFT,plot.size.x,10,T.MUTED)
	if hover_index>=0:
		if current.has("date"):
			draw_string(font,Vector2(4,plot.end.y+15),current.date+"  V "+Data.money(current.volume),HORIZONTAL_ALIGNMENT_LEFT,plot.size.x,10,T.MUTED)
		var x := plot.position.x+(hover_index+0.5)*step
		var y: float = price_y.call(current.close)
		draw_dashed_line(Vector2(x,plot.position.y),Vector2(x,size.y-17),Color("94a8ba"),1,4)
		draw_dashed_line(Vector2(plot.position.x,y),Vector2(plot.end.x,y),Color("94a8ba"),1,4)
		draw_circle(Vector2(x,y),3,Color("e8edf3"))

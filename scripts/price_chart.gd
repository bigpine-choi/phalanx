extends Control
const Data = preload("res://scripts/market_data.gd")
const T = preload("res://scripts/terminal_theme.gd")
const UP := Color("365e46")
const DOWN := Color("9b4834")
const INK := Color("65533c")
const PAPER := Color("dac79f")
const AVERAGE := Color("8a6527")
const MIN_VISIBLE_BARS := 8
const ZOOM_FACTOR := 1.25
var candles: Array = []
var days := 66
var show_average := true
var display_mode := "candles"
var hover_index := -1
var full_history: Array = []
var view_start := 0
var visible_count := 0
var _dragging := false
var _drag_origin_x := 0.0
var _drag_origin_start := 0
var chart_font: Font = T.font(true)
var label_font: Font = T.font()

func _ready() -> void:
	custom_minimum_size = Vector2(260,190)
	mouse_filter = Control.MOUSE_FILTER_STOP
	mouse_force_pass_scroll_events = false
	mouse_exited.connect(func() -> void: hover_index=-1; queue_redraw())
	resized.connect(queue_redraw)

func set_history(value: Array) -> void:
	if full_history == value:
		return
	full_history = value.duplicate(true)
	reset_navigation()

func set_period(value: int) -> void:
	days = maxi(1,value)
	reset_navigation()

func reset_navigation() -> void:
	_dragging = false
	visible_count = mini(days,full_history.size())
	view_start = maxi(0,full_history.size()-visible_count)
	candles = full_history.slice(view_start,view_start+visible_count)
	hover_index = -1
	queue_redraw()

func _set_window(start: int, count: int) -> void:
	visible_count = clampi(count,1,full_history.size())
	view_start = clampi(start,0,full_history.size()-visible_count)
	candles = full_history.slice(view_start,view_start+visible_count)
	hover_index = -1
	queue_redraw()

func average_at(visible_index: int) -> float:
	var absolute_index := view_start+visible_index
	if visible_index < 0 or visible_index >= candles.size() or absolute_index < 19:
		return NAN
	var total := 0.0
	for index: int in range(absolute_index-19,absolute_index+1):
		total += float(full_history[index].close)
	return total/20.0

func plot_rect() -> Rect2:
	return Rect2(14,36,maxf(1,size.x-96),maxf(1,size.y-112))

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP or event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			accept_event()
			if event.pressed:
				_zoom_at(event.position,event.button_index == MOUSE_BUTTON_WHEEL_UP)
			return
		if event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed and event.double_click:
				reset_navigation()
				accept_event()
				return
			if event.pressed and plot_rect().has_point(event.position) and not candles.is_empty():
				_dragging = true
				_drag_origin_x = event.position.x
				_drag_origin_start = view_start
				accept_event()
			elif not event.pressed and _dragging:
				_pan_to(event.position.x)
				_dragging = false
				_update_hover(event.position)
				accept_event()
			return
	if event is InputEventMouseMotion:
		if _dragging and not candles.is_empty():
			_pan_to(event.position.x)
			accept_event()
		_update_hover(event.position)

func _pan_to(position_x: float) -> void:
	if not _dragging or visible_count <= 0:
		return
	var pixels_per_bar := plot_rect().size.x/float(visible_count)
	_set_window(_drag_origin_start-roundi((position_x-_drag_origin_x)/pixels_per_bar),visible_count)

func _zoom_at(position: Vector2, zoom_in: bool) -> void:
	if candles.is_empty():
		return
	var minimum := mini(MIN_VISIBLE_BARS,mini(days,full_history.size()))
	var next_count := visible_count
	if zoom_in:
		next_count = maxi(minimum,mini(visible_count-1,roundi(float(visible_count)/ZOOM_FACTOR)))
	else:
		next_count = mini(full_history.size(),maxi(visible_count+1,roundi(float(visible_count)*ZOOM_FACTOR)))
	if next_count == visible_count:
		return
	var plot := plot_rect()
	var fraction := clampf((position.x-plot.position.x)/plot.size.x,0.0,1.0)
	var anchor := float(view_start)+fraction*float(visible_count)
	_set_window(roundi(anchor-fraction*float(next_count)),next_count)
	_update_hover(position)

func _update_hover(position: Vector2) -> void:
	var index := -1
	if not candles.is_empty():
		var plot := plot_rect()
		if plot.has_point(position):
			index = clampi(int((position.x-plot.position.x)/plot.size.x*candles.size()),0,candles.size()-1)
	if hover_index != index:
		hover_index = index
		queue_redraw()

func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO,size), PAPER)
	draw_rect(Rect2(Vector2(4,4),size-Vector2(8,8)), Color("ac936b"), false, 1)
	for y: int in range(7,int(size.y)-6,4):
		draw_line(Vector2(6,y),Vector2(size.x-6,y+sin(y)*0.4),Color(0.30,0.20,0.10,0.025),1)
	for x: float in [8.0,size.x-8.0]:
		for y: float in [8.0,size.y-8.0]:
			draw_circle(Vector2(x,y),1.3,Color("967344"))
	if candles.is_empty():
		var center := size * 0.5
		draw_arc(center-Vector2(0,16),22,0,TAU,48,Color(INK,0.35),1,true)
		draw_line(center+Vector2(-29,-16),center+Vector2(29,-16),Color(INK,0.35),1)
		draw_line(center+Vector2(0,-45),center+Vector2(0,13),Color(INK,0.35),1)
		var message := "일봉 자료 대기 중"
		var width := label_font.get_string_size(message,HORIZONTAL_ALIGNMENT_LEFT,-1,13).x
		draw_string(label_font,center+Vector2(-width*0.5,44),message,HORIZONTAL_ALIGNMENT_LEFT,-1,13,INK)
		return
	var font := chart_font
	var plot := plot_rect()
	var low := INF
	var high := -INF
	var averages: Array[float] = []
	for index: int in candles.size():
		var average := average_at(index)
		averages.append(average)
		if show_average and is_finite(average):
			low = minf(low,average)
			high = maxf(high,average)
	for candle: Dictionary in candles:
		low = minf(low,candle.low)
		high = maxf(high,candle.high)
	var padding := maxf((high-low)*0.12,1)
	low -= padding
	high += padding
	var price_y := func(value: float) -> float: return plot.end.y-(value-low)/(high-low)*plot.size.y
	for index: int in 5:
		var y := plot.position.y+plot.size.y*float(index)/4.0
		draw_line(Vector2(plot.position.x,y),Vector2(plot.end.x,y),Color("bba77f"),1)
		draw_string(font,Vector2(plot.end.x+10,y+4),Data.money(high-(high-low)*float(index)/4),HORIZONTAL_ALIGNMENT_LEFT,-1,11,INK)
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
		draw_polyline(average_points,AVERAGE,1.7,true)
	var last_y: float = price_y.call(candles[-1].close)
	draw_dashed_line(Vector2(plot.position.x,last_y),Vector2(plot.end.x,last_y),Color(UP,0.3),1,4)
	draw_rect(Rect2(plot.end.x+5,last_y-8,68,17),UP)
	draw_string(font,Vector2(plot.end.x+10,last_y+4),Data.money(candles[-1].close),HORIZONTAL_ALIGNMENT_LEFT,-1,11,PAPER)
	draw_string(font,Vector2(14,size.y-9),str(candles[0].get("date","-%dD" % (candles.size()-1))),HORIZONTAL_ALIGNMENT_LEFT,-1,10,INK)
	draw_string(font,Vector2(plot.end.x-65,size.y-9),str(candles[-1].get("date","T0")),HORIZONTAL_ALIGNMENT_LEFT,-1,10,INK)
	var current: Dictionary = candles[hover_index if hover_index>=0 else -1]
	var caption := "O %s   H %s   L %s   C %s" % [Data.money(current.open),Data.money(current.high),Data.money(current.low),Data.money(current.close)]
	draw_string(font,Vector2(14,22),caption,HORIZONTAL_ALIGNMENT_LEFT,plot.size.x,10,INK)
	if hover_index>=0:
		if current.has("date"):
			draw_string(font,Vector2(14,plot.end.y+15),current.date+"  V "+Data.money(current.volume),HORIZONTAL_ALIGNMENT_LEFT,plot.size.x,10,INK)
		var x := plot.position.x+(hover_index+0.5)*step
		var y: float = price_y.call(current.close)
		draw_dashed_line(Vector2(x,plot.position.y),Vector2(x,size.y-17),INK,1,4)
		draw_dashed_line(Vector2(plot.position.x,y),Vector2(plot.end.x,y),INK,1,4)
		draw_circle(Vector2(x,y),3,UP)

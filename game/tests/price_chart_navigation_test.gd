extends SceneTree
const Chart = preload("res://scripts/price_chart.gd")

var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func history(count: int) -> Array:
	var result: Array = []
	for index: int in count:
		var close := float(index+1)
		result.append({"date":"D%03d" % index,"open":close-0.5,"high":close+1.0,"low":close-1.0,"close":close,"volume":1000+index})
	return result

func wheel(chart: Control, position: Vector2, direction: MouseButton) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = direction
	event.pressed = true
	event.position = position
	chart._gui_input(event)

func mouse_button(chart: Control, position: Vector2, pressed: bool, double_click := false) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_LEFT
	event.position = position
	event.pressed = pressed
	event.double_click = double_click
	chart._gui_input(event)

func motion(chart: Control, position: Vector2, mask: int = MOUSE_BUTTON_MASK_LEFT) -> void:
	var event := InputEventMouseMotion.new()
	event.position = position
	event.button_mask = mask
	chart._gui_input(event)

func global_wheel(position: Vector2) -> void:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_WHEEL_DOWN
	event.pressed = true
	event.position = position
	event.global_position = position
	Input.parse_input_event(event)

func run() -> void:
	var chart := Chart.new()
	root.add_child(chart)
	chart.size = Vector2(500,300)
	var bars := history(120)
	chart.set_history(bars)
	check(chart.mouse_filter == Control.MOUSE_FILTER_STOP and not chart.mouse_force_pass_scroll_events,"Chart owns wheel events over its area without passing scroll to parent")
	check(chart.view_start == 54 and chart.visible_count == 66 and chart.candles[0].date == "D054","Default period shows the latest 66 bars")

	var plot: Rect2 = chart.plot_rect()
	var quarter := Vector2(plot.position.x+plot.size.x*0.25,plot.position.y+plot.size.y*0.5)
	var before_anchor := float(chart.view_start)+float(chart.visible_count)*0.25
	wheel(chart,quarter,MOUSE_BUTTON_WHEEL_UP)
	var after_anchor := float(chart.view_start)+float(chart.visible_count)*0.25
	check(chart.visible_count < 66 and absf(after_anchor-before_anchor) <= 1.0,"Wheel zooms around pointer position")
	check(chart.candles[0].date == "D%03d" % chart.view_start,"Visible candle slice follows zoom window")
	for index: int in 40:
		wheel(chart,quarter,MOUSE_BUTTON_WHEEL_UP)
	check(chart.visible_count == Chart.MIN_VISIBLE_BARS,"Zoom in stops at minimum candle count")
	for index: int in 40:
		wheel(chart,quarter,MOUSE_BUTTON_WHEEL_DOWN)
	check(chart.visible_count == 120 and chart.view_start == 0,"Zoom out stops at available history")

	chart._set_window(40,30)
	var center := plot.get_center()
	mouse_button(chart,center,true)
	motion(chart,center+Vector2(80,0))
	mouse_button(chart,center+Vector2(80,0),false)
	check(chart.view_start == 34 and chart.visible_count == 30,"Right drag pans toward older candles")
	mouse_button(chart,center,true)
	motion(chart,center-Vector2(80,0))
	mouse_button(chart,center-Vector2(80,0),false)
	check(chart.view_start == 40,"Left drag pans toward newer candles")
	chart._set_window(40,30)
	mouse_button(chart,center,true)
	mouse_button(chart,center+Vector2(80,0),false)
	check(chart.view_start == 34,"Fast press and release pans using release position")
	chart._set_window(40,30)
	mouse_button(chart,center,true)
	motion(chart,center+Vector2(80,0),0)
	mouse_button(chart,center+Vector2(80,0),false)
	check(chart.view_start == 34,"Drag motion without a button mask remains effective")
	motion(chart,Vector2(plot.position.x+plot.size.x*0.75,plot.get_center().y))
	check(chart.hover_index == 22 and chart.candles[chart.hover_index].date == "D056","Hover maps to visible candle after pan")
	motion(chart,Vector2.ZERO)
	check(chart.hover_index == -1,"Hover clears outside plot")
	chart._set_window(20,30)
	check(is_equal_approx(chart.average_at(0),11.5) and is_equal_approx(chart.average_at(10),21.5),"Moving average uses absolute source indices after pan")
	chart._set_window(0,30)
	check(is_nan(chart.average_at(0)) and is_equal_approx(chart.average_at(19),10.5),"Moving average starts after 20 actual candles")

	chart._set_window(20,30)
	chart.set_history(bars.duplicate(true))
	chart.display_mode = "line"
	chart.show_average = false
	chart.queue_redraw()
	check(chart.view_start == 20 and chart.visible_count == 30,"Identical history and style changes retain navigation")
	mouse_button(chart,center,true,true)
	check(chart.view_start == 54 and chart.visible_count == 66,"Double click restores selected period")
	chart._set_window(20,30)
	chart.set_period(22)
	check(chart.view_start == 98 and chart.visible_count == 22,"Changing period restores latest period window")
	chart.set_history(history(130))
	check(chart.view_start == 108 and chart.visible_count == 22,"Different history resets navigation")
	chart.set_period(3)
	wheel(chart,center,MOUSE_BUTTON_WHEEL_UP)
	check(chart.visible_count == 3,"Zoom in does not enlarge a period shorter than the normal minimum")
	wheel(chart,center,MOUSE_BUTTON_WHEEL_DOWN)
	wheel(chart,center,MOUSE_BUTTON_WHEEL_UP)
	check(chart.visible_count == 3,"Short period can zoom back to its own minimum")
	chart._set_window(0,30)
	mouse_button(chart,center,true)
	motion(chart,center+Vector2(2000,0))
	mouse_button(chart,center+Vector2(2000,0),false)
	check(chart.view_start == 0,"Drag clamps at the first source candle")
	chart._set_window(100,30)
	mouse_button(chart,center,true)
	motion(chart,center-Vector2(2000,0))
	mouse_button(chart,center-Vector2(2000,0),false)
	check(chart.view_start == 100,"Drag clamps at the latest source candle")
	chart.set_history([])
	check(chart.candles.is_empty() and chart.view_start == 0 and chart.visible_count == 0,"Clearing for stock switch resets old candles")
	wheel(chart,center,MOUSE_BUTTON_WHEEL_UP)
	check(chart.visible_count == 0,"Empty chart ignores wheel navigation")
	chart.queue_free()
	await process_frame

	var scroll := ScrollContainer.new()
	scroll.size = Vector2(300,250)
	root.add_child(scroll)
	var column := VBoxContainer.new()
	scroll.add_child(column)
	var embedded := Chart.new()
	column.add_child(embedded)
	embedded.set_history(bars)
	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(260,800)
	column.add_child(spacer)
	await process_frame
	check(scroll.get_v_scroll_bar().max_value > 250,"Parent scroll area has scrollable content")
	global_wheel(Vector2(100,80))
	await process_frame
	check(embedded.visible_count > 66 and scroll.scroll_vertical == 0,"Wheel over chart zooms without scrolling parent")
	global_wheel(Vector2(100,220))
	await process_frame
	check(scroll.scroll_vertical > 0,"Wheel outside chart still scrolls parent")

	print("PHALANX_PRICE_CHART_NAVIGATION_TEST: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

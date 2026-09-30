extends "res://tests/watchlist_groups_review.gd"
## Native chart/table review. Every price and daily bar here is synthetic.
const Quotes = preload("res://scripts/watchlist_quote_gateway.gd")
const ResearchModel = preload("res://scripts/research_model.gd")
var review_view: Control
var last_navigation := ""

func _process(_delta: float) -> bool:
	if not is_instance_valid(review_view):
		return false
	var market: Control = review_view.chart
	var research: Control = review_view.research_view.chart
	var navigation := "workspace=%s code=%s market=%d/%d research=%d/%d scroll=%d" % [review_view.workspace,review_view.securities[review_view.selected].code,market.view_start,market.visible_count,research.view_start,research.visible_count,review_view.research_page.scroll_vertical]
	if navigation != last_navigation:
		last_navigation = navigation
		print("NATIVE_NAVIGATION: ",navigation)
	return false

class SeedProcess extends Node:
	signal completed(code: String, token: int, envelope: Dictionary)
	func request(code: String, token: int) -> void:
		var payload := {"provider":"NHPLUG","code":code,"market":"KRX","currency":"KRW","price":10000+int(code)%90000,"fetched_at":int(Time.get_unix_time_from_system())}
		completed.emit.call_deferred(code,token,{"ok":true,"payload":payload})

func history(code: String) -> Dictionary:
	var now := int(Time.get_unix_time_from_system())
	var candles: Array = []
	for index: int in 241:
		var date := Time.get_datetime_string_from_unix_time(now+9*3600-(242-index)*86400).left(10)
		var base := 80000.0+index*80.0+sin(index*0.12)*4000.0
		candles.append({"date":date,"open":base,"high":base+1000.0,"low":base-800.0,"close":base+sin(index)*650.0,"volume":100000+index*370})
	return ResearchModel.parse_kis({"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":now,"requested_start":candles[0].date,"requested_end":candles[-1].date,"candles":candles},code,now)

func run(directory: String, width: String) -> void:
	# Only the injected seeder runs with the queue enabled; it cannot call WSL.
	OS.set_environment("PHALANX_NH_OFFLINE","0")
	OS.set_environment("PHALANX_NH_QUOTE_CACHE",directory.path_join("nh"))
	var seed := Quotes.new()
	seed.process = SeedProcess.new()
	root.add_child(seed)
	var marker := directory.path_join("synthetic-quotes-seeded.flag")
	if not FileAccess.file_exists(marker):
		var codes: Array = []
		for stock: Dictionary in Data.STOCKS:
			codes.append(stock.code)
		for index: int in 15:
			codes.append("%06d" % (300000+index))
		seed.refresh(codes)
		var deadline := Time.get_ticks_msec()+20000
		while seed.busy and Time.get_ticks_msec()<deadline:
			await create_timer(0.1).timeout
		if seed.busy or seed.quote_for("005930").is_empty():
			push_error("Synthetic NH cache preparation failed")
			quit(1)
			return
		var flag := FileAccess.open(marker,FileAccess.WRITE)
		flag.store_string("Synthetic public-price fixture only")
		flag.close()
	print("QUOTE_RESTART_RESTORE: ",JSON.stringify(seed.quote_for("005930")))
	seed.queue_free()
	await process_frame
	OS.set_environment("PHALANX_NH_OFFLINE","1")
	await super.run(directory,width)
	var view: Control = root.get_children()[-1]
	review_view = view
	view.chart.gui_input.connect(_chart_event.bind(view.chart,"market"))
	view.research_view.chart.gui_input.connect(_chart_event.bind(view.research_view.chart,"research"))
	for security: Dictionary in view.securities:
		view.research_view.gateway.memory_quotes[security.code] = history(security.code)
	var selected_code: String = view.securities[view.selected].code
	view.research_view.gateway.quote = view.research_view.gateway.memory_quotes[selected_code]
	view.research_view.gateway.quote_state = "cached"
	view.research_view.gateway.quote_message = "격리 검수용 합성 일봉 · 실제 시장 자료 아님"
	view.research_view.gateway.changed.emit()
	view._refresh_watch_table(true)
	root.title = "Phalanx 시세표·차트 검수 " + width + " — 합성 자료"
	print("QUOTES_CHART_REVIEW_READY: ",width,"; synthetic rows=60; candles=241; NH offline")

func _chart_event(event: InputEvent, chart: Control, label: String) -> void:
	if event is InputEventMouseButton:
		print("NATIVE_CHART_INPUT: ",label," button=",event.button_index," down=",event.pressed," point=",event.position," plot=",chart.plot_rect().has_point(event.position))

extends "res://tests/watchlist_groups_ui_test.gd"
## Targeted integration cases added for current-price and chart navigation changes.
const ResearchModel = preload("res://scripts/research_model.gd")

func daily(code: String) -> Dictionary:
	var now := int(Time.get_unix_time_from_system())
	var bars: Array = []
	for index: int in 90:
		bars.append({"date":Time.get_datetime_string_from_unix_time(now+9*3600-(91-index)*86400).left(10),"open":100.0+index,"high":110.0+index,"low":90.0+index,"close":105.0+index,"volume":1000})
	return ResearchModel.parse_kis({"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":now,"requested_start":bars[0].date,"requested_end":bars[-1].date,"candles":bars},code,now)

func run() -> void:
	OS.set_environment("PHALANX_NH_OFFLINE","1")
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(view)
	await frames()
	view.catalog.accept_snapshot(catalog_fixture())
	for code: String in ["005930","123456","123457"]:
		view.research_view.gateway.memory_quotes[code] = daily(code)
	view._catalog_security_chosen(item("123456","검증전자","KOSDAQ","보통주"),false)
	view.chart._zoom_at(view.chart.plot_rect().get_center(),true)
	var zoomed: int = view.chart.visible_count
	check(zoomed<66,"Preview chart zooms")
	view._catalog_security_chosen(item("123456","검증전자","KOSDAQ","보통주"),false)
	check(view.chart.visible_count==zoomed,"Re-selecting same preview preserves navigation")
	view._catalog_security_chosen(item("005930","삼성전자"),false)
	check(view.securities[view.selected].code=="005930" and view._security_index("123456")<0,"Preview removal before existing target never indexes a removed row")
	check(view.chart.visible_count==66 and view.research_view.chart.visible_count==66,"Different security resets both charts even with identical daily bars")
	view._catalog_security_chosen(item("123456","검증전자","KOSDAQ","보통주"),false)
	view.chart._zoom_at(view.chart.plot_rect().get_center(),true)
	view._catalog_security_chosen(item("123457","검증화학","KOSDAQ","우선주"),false)
	check(view.securities[view.selected].code=="123457" and view.chart.visible_count==66,"New preview replacing same array slot still resets navigation")
	var snapshot: Dictionary = catalog_fixture()
	snapshot.items.append(item("123457","다른 식별자","KOSDAQ","보통주"))
	snapshot.collisions = [{"code":"123457","reason":"동일 코드 식별자 충돌"}]
	check(view.catalog.accept_snapshot(snapshot),"Catalogue collision fixture is accepted as blocked metadata")
	await frames(2)
	check(view.research_view.gateway.quote_state=="unsupported" and view.chart.candles.is_empty() and view.research_view.chart.candles.is_empty(),"New catalogue conflict removes both displayed KIS charts")
	check(view.research_view.nh_button.disabled and find_row(view._table_rows(),"123457").price==null,"Same conflict also blocks NH action and table price")
	view.watch_table.show()
	view.catalog.accept_snapshot(catalog_fixture())
	await frames(2)
	check(view.research_view.gateway.unsupported_reason.is_empty() and not view.chart.candles.is_empty(),"Resolved identity reconnects the cached daily chart")
	check(find_row(view.watch_table.source_rows,"123457").status != "일봉 미지원","Resolved identity refreshes the visible table after gateway state changes")
	check(view.research_view.nh_quotes.process.pid<0,"Selection and table integration never request NH automatically")
	view.queue_free()
	await process_frame
	print("WATCHLIST_QUOTES_INTEGRATION: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

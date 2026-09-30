extends SceneTree
## Isolated catalogue-to-market UI regression; never uses the live discovery store.
const Store = preload("res://scripts/workspace_store.gd")

var checks := 0
var failures := 0
var directory := ""

func _initialize() -> void:
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	directory = OS.get_environment("TEMP").path_join("phalanx-catalog-ui-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("workspace.json"))
	OS.set_environment("PHALANX_CATALOG_CACHE",directory.path_join("catalog.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func frames(count := 6) -> void:
	for index: int in count:
		await process_frame

func row(code: String, name: String, kind: String = "보통주", market: String = "KOSPI") -> Dictionary:
	return {"code":code,"name":name,"market":market,"kind":kind,"source":"격리 검증 목록","collected_at":"2026-09-30T00:00:00+00:00",
		"collision":false,"registration_supported":true,"reason":""}

func snapshot() -> Dictionary:
	var rows: Array = [row("123456","검증전자"),row("069501","KODEX 검증 ETF","ETF"),row("005935","삼성전자 검증 우선주","우선주"),
		row("555555","충돌 A"),row("555555","충돌 B"),row("KRX:123456","확장 코드","기타")]
	for index: int in 2500:
		rows.append(row("%06d" % (300000+index),"확장종목 %04d" % index))
	return {"state":"ready","collected_at":"2026-09-30T00:00:00+00:00","source":"격리 검증 목록","items":rows,
		"collisions":[{"code":"555555","reason":"동일 코드 식별자 충돌"}]}

func observation(code: String) -> Dictionary:
	var now := int(Time.get_unix_time_from_system())
	var start := Time.get_datetime_string_from_unix_time(now+9*3600-5*86400).left(10)
	var next := Time.get_datetime_string_from_unix_time(now+9*3600-4*86400).left(10)
	var finish := Time.get_datetime_string_from_unix_time(now+9*3600-86400).left(10)
	return {"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":now,
		"requested_start":start,"requested_end":finish,"candles":[
			{"date":start,"open":100.0,"high":110.0,"low":90.0,"close":100.0,"volume":100},
			{"date":next,"open":100.0,"high":115.0,"low":95.0,"close":110.0,"volume":200}]}

func account_snapshot(security_name: String, marker: String) -> Dictionary:
	var holding := {"code":"123456","name":security_name,"quantity":"10","sellable":"10","price":"100","value":"1000","broker_value":"1000",
		"profit_loss":"0","stock_weight":"100","price_observed_at":"2026-09-29T12:00:00+00:00"}
	return {"version":1,"source":"kis_account","currency":"KRW","snapshot_id":marker.repeat(64),"account_masked":"0000****-**",
		"observed_at":"2026-09-29T12:00:00+00:00","positions_value":"1000",
		"summary":{"net_assets":"1000","deposit_total":"0","securities_evaluation_amount":"1000","profit_loss_total":"0"},
		"warnings":[],"rows":[holding]}

func run() -> void:
	root.size = Vector2i(1280,720)
	var dashboard: Control = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	await frames()
	dashboard._open_catalog()
	var panel: Control = dashboard.catalog_panel
	check(panel.visible and panel.status_label.text.contains("최초"),"Fresh catalogue distinguishes no initial data")
	check(panel.results.get_child_count()==1 and panel.add_button.disabled,"No-data catalogue offers no security to register")
	check(dashboard.catalog.accept_snapshot(snapshot()),"Isolated discovery snapshot is accepted")
	for resolution: Vector2i in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = resolution
		await frames(8)
		var card: Rect2 = panel.card.get_global_rect()
		check(card.position.x>=0 and card.position.y>=0 and card.end.x<=resolution.x and card.end.y<=resolution.y,"Catalogue card fits "+str(resolution))
		check(panel.query_edit.is_visible_in_tree() and panel.add_button.is_visible_in_tree() and panel.view_button.is_visible_in_tree(),"Search and actions remain visible at "+str(resolution))
	panel.set_query("검증전자")
	check(panel.selected_item.get("code")=="123456" and panel.count_label.text.contains("1건"),"Korean name search finds an unheld security")
	panel.set_query("123456")
	check(panel.selected_item.get("name")=="검증전자","Code search selects the exact security ahead of a longer code")
	panel.set_query("069501")
	check(panel.selected_item.get("kind")=="ETF" and panel.detail_meta.text.contains("ETF"),"ETF appears with its kind and market")
	panel.set_query("우선주")
	check(panel.selected_item.get("code")=="005935" and panel.detail_source.text.contains("수집"),"Preferred stock appears with source and collection time")
	panel.set_query("확장종목")
	check(panel.count_label.text.contains("2500건") and panel.results.get_child_count()<=30,"Thousands-scale result sets create only bounded visible rows")
	panel.set_query("존재하지않는이름")
	check(panel.count_label.text.contains("0건") and panel.results.get_child_count()==1 and panel.results.get_child(0).text.contains("0건"),"No matches are distinct from no initial data")
	panel.set_query("KRX:123456")
	check(panel.selected_item.get("code")=="KRX:123456" and panel.add_button.disabled and panel.view_button.disabled and panel.detail_support.text.contains("6자리"),"Non-history code is searchable with its support reason")
	panel.set_query("555555")
	check(panel.count_label.text.contains("2건") and panel.selected_item.get("collision")==true and panel.add_button.disabled,"Duplicate identifiers are marked and cannot be registered")
	var old_count: int = dashboard.watchlist_codes.size()
	dashboard._catalog_security_chosen(panel.selected_item,true)
	check(dashboard.watchlist_codes.size()==old_count and dashboard._security_index("555555")<0,"Direct collision action cannot bypass registration guard")
	dashboard._catalog_security_chosen(row("005930","다른 삼성전자"),true)
	check(dashboard.watchlist_codes.size()==old_count and dashboard.securities[0].name=="삼성전자" and panel.feedback.text.contains("식별자 충돌"),"Existing code and different name cannot be merged")
	panel.set_query("123456")
	check(panel.feedback.text.is_empty(),"New search clears stale identity error feedback")
	check(not panel.add_button.disabled,"Valid unheld security can be added")
	panel.add_button.pressed.emit()
	check(not panel.visible and dashboard.securities[dashboard.selected].code=="123456","Catalogue add selects the same market security")
	check(dashboard.watchlist_codes.count("123456")==1 and dashboard.position_button.disabled,"New favorite is unique and remains unheld")
	dashboard._catalog_security_chosen(row("123456","검증전자","ETF"),true)
	check(dashboard.watchlist_codes.count("123456")==1 and dashboard.securities[dashboard.selected].kind=="보통주","Existing code with different kind cannot be merged")
	check(dashboard.research_view.current_code=="123456" and dashboard.research_view.advisor.context.code=="123456" and not dashboard.research_view.advisor.busy,"Research and advisor follow the selection without starting AI")
	dashboard._select_workspace("research")
	dashboard.research_page.scroll_vertical = 10000
	await frames()
	dashboard._select_workspace("market")
	dashboard._open_selected_advisor()
	await frames()
	var research_bounds: Rect2 = dashboard.research_page.get_global_rect()
	var title_bounds: Rect2 = dashboard.research_title.get_global_rect()
	var advisor_bounds: Rect2 = dashboard.research_view.advisor.heading.get_global_rect()
	check(dashboard.research_page.scroll_vertical==0 and title_bounds.position.y>=research_bounds.position.y and title_bounds.position.y<research_bounds.end.y,"Research navigation reveals the selected security heading")
	check(advisor_bounds.position.y>=research_bounds.position.y and advisor_bounds.position.y<research_bounds.end.y and not dashboard.research_view.advisor.busy,"Research navigation shows advisor heading without starting AI")
	dashboard._select_workspace("market")
	var gateway: Node = dashboard.research_view.gateway
	gateway._kis_completed("123456",gateway.generation,observation("123456"))
	check(dashboard.chart.candles.size()==2 and dashboard.research_view.chart.candles==dashboard.chart.candles,"Market and research use the same existing single-stock daily history")
	check(dashboard.research_view.advisor.context.quote.get("code")=="123456","Advisor receives the selected stock's quote")
	dashboard.note_editor.text = "검증 가설 · ETF와 우선주도 살펴본다"
	dashboard._note_changed()
	dashboard.flush_profile()
	dashboard._open_catalog("123456")
	check(panel.add_button.disabled and panel.add_button.text.contains("등록됨"),"Already watched security cannot be added twice")
	dashboard._catalog_security_chosen(panel.selected_item,true)
	check(dashboard.watchlist_codes.count("123456")==1,"Repeated add call still keeps one favorite")
	dashboard._toggle_favorite()
	var stored: Dictionary = Store.new(directory.path_join("workspace.json")).load_profile()
	check(not "123456" in stored.watchlist and stored.notes.get("123456")=="검증 가설 · ETF와 우선주도 살펴본다","Removing a favorite leaves its note on disk")
	var collected: String = dashboard.catalog.collected_at
	var count: int = dashboard.catalog.items.size()
	dashboard.catalog._failed("refresh")
	check(dashboard.catalog.state=="stale" and dashboard.catalog.collected_at==collected and dashboard.catalog.items.size()==count and panel.status_label.text.contains("갱신 실패"),"Failed refresh keeps the previous list and collection time")
	var prior_watchlist: Array = dashboard.watchlist_codes.duplicate()
	dashboard.watchlist_codes.clear()
	for index: int in 1000:
		dashboard.watchlist_codes.append("%06d" % (700000+index))
	dashboard._refresh_favorite()
	check(dashboard.favorite_button.disabled,"Favorite action respects the existing 1,000-entry storage limit")
	dashboard._catalog_security_chosen(row("123456","검증전자"),true)
	check(dashboard.watchlist_codes.size()==1000 and panel.feedback.text.contains("1,000"),"Catalogue add reports the storage limit before changing the profile")
	dashboard.watchlist_codes = prior_watchlist
	dashboard._toggle_favorite()
	dashboard.simulator.set_account(account_snapshot("다른 검증 종목","a"))
	await frames()
	var selected_security: Dictionary = dashboard.securities[dashboard._security_index("123456")]
	check(selected_security.name=="검증전자" and selected_security.get("account_identity_conflict")=="다른 검증 종목","Late account identity conflict preserves the catalogue name")
	check(dashboard.position_button.disabled and dashboard.position_heading.text.contains("식별자") and dashboard.research_view.gateway.quote_state=="unsupported" and dashboard.chart.candles.is_empty(),"Conflicting account row is not attached to market position or history")
	check(dashboard.research_view.advisor.context.quote.is_empty() and dashboard.research_view.advisor.context.plan.is_empty() and dashboard.research_view.advisor.buttons[0].disabled,"Advisor cannot analyze a mismatched account identity")
	dashboard.flush_profile()
	check(Store.new(directory.path_join("workspace.json")).load_profile().security_names.get("123456")=="검증전자","Account conflict cannot overwrite the watched name on disk")
	dashboard.simulator.set_account(account_snapshot("검증전자","b"))
	await frames()
	check(not dashboard.securities[dashboard._security_index("123456")].has("account_identity_conflict") and not dashboard.position_button.disabled and dashboard.research_view.gateway.quote_state!="unsupported","Matching next account snapshot restores verified links")
	panel.close()
	dashboard.queue_free()
	await frames()
	var restored: Control = load("res://scenes/headquarters.tscn").instantiate()
	restored.embedded_in_camp = true
	root.add_child(restored)
	await frames()
	restored._select_stock(restored._security_index("123456"))
	restored.simulator.set_account(account_snapshot("다른 검증 종목","c"))
	await frames()
	check(restored.securities[restored.selected].name=="검증전자" and restored.position_button.disabled and restored.research_view.gateway.quote_state=="unsupported","Restored saved identity also rejects a later conflicting account row")
	restored.queue_free()
	await frames()
	print("MARKET_CATALOG_UI_TEST: %s (%d checks; isolated profile and catalogue)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

extends SceneTree
const Model = preload("res://scripts/research_model.gd")
const Store = preload("res://scripts/workspace_store.gd")
var checks := 0
var failures := 0
var directory: String

func _initialize() -> void:
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE"]: OS.set_environment(key,"1")
	directory = OS.get_environment("TEMP").path_join("phalanx-market-test-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("workspace.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("quotes"))
	call_deferred("run")

func check(value: bool, label: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(label)

func frames() -> void:
	for i: int in 8: await process_frame

static func observation(code: String) -> Dictionary:
	return {"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":1790640000,"requested_start":"2026-09-01","requested_end":"2026-09-28","candles":[{"date":"2026-09-24","open":100,"high":110,"low":90,"close":100,"volume":123},{"date":"2026-09-25","open":100,"high":112,"low":99,"close":110,"volume":456}]}

static func account() -> Dictionary:
	var rows: Array = []
	for i: int in 11:
		rows.append({"code":"%06d" % (123450+i),"name":"검증 종목 %d" % i,"quantity":"10","sellable":"10","price":"100","value":"1000","broker_value":"1000","profit_loss":"-50","stock_weight":str(100.0/11),"price_observed_at":"2026-09-29T12:00:00+00:00"})
	return {"version":1,"source":"kis_account","currency":"KRW","snapshot_id":"b".repeat(64),"account_masked":"0000****-**","observed_at":"2026-09-29T12:00:00+00:00","positions_value":"11000","summary":{"net_assets":"13000","deposit_total":"2000","securities_evaluation_amount":"11000","profit_loss_total":"-550"},"warnings":[],"rows":rows}

func run() -> void:
	root.size = Vector2i(1440,960)
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(view)
	await frames()
	check(view.chart.candles.is_empty() and view.price_label.text=="—","Unobserved market has no synthetic quote")
	check(view.account_labels[0].text=="—" and view.simulator.account.is_empty(),"Unobserved account is not shown as zero")
	view.simulator.set_account(account())
	await frames()
	check(view.securities.size()==16 and view.stock_buttons.size()==16,"All 11 holdings merge with five watched securities")
	check(view.stock_buttons.filter(func(b: Button) -> bool: return b.visible).size()==16,"Holdings show even when not in watchlist")
	view._select_stock(view._security_index("123459"))
	check(view.title_label.text=="검증 종목 9" and view.research_view.current_code=="123459","Dynamic selection follows into research")
	check(view.research_view.advisor.context.code=="123459" and view.research_view.advisor.context.name=="검증 종목 9","Advisor follows dynamic security identity")
	check(not view.research_view.advisor.context.has("account") and not view.research_view.advisor.context.has("quantity"),"Market does not add private balances to AI context")
	check(view.position_detail.text.contains("10주") and view.position_detail.text.contains("-50원"),"Position uses actual observed quantity and P&L")
	check(not view.position_button.disabled,"Held stock links to allocation")
	var gateway: Node = view.research_view.gateway
	gateway._kis_completed("123459",gateway.generation,observation("123459"))
	check(view.chart.candles.size()==2 and view.price_label.text=="110 원","Same public history feeds market")
	check(view.change_label.text.contains("+10.00%") and view.quote_status.text.contains("456주"),"Change and volume come from same daily observation")
	check(view.research_view.chart.candles==view.chart.candles,"Market and research share exactly the same daily bars")
	view._set_period(22)
	view._set_chart_mode("line")
	view._open_selected_position()
	await frames()
	check(view.workspace=="portfolio" and view.simulator.rows[9].input.get_line_edit().has_focus(),"Allocation action focuses selected holding")
	check(view.simulator.targets["123459"]==9.09,"Navigation does not change target weights")
	view._select_workspace("market")
	view._open_selected_advisor()
	await frames()
	check(view.workspace=="research" and not view.research_view.advisor.busy,"Advisor navigation does not auto-spend API credit")
	view.note_editor.text = "동적 종목의 검토 메모"
	view._note_changed()
	view._toggle_favorite()
	var old_generation: int = gateway.generation
	view._select_stock(0)
	gateway._kis_completed("123459",old_generation,observation("123459"))
	check(view.chart.candles.is_empty() and view.price_label.text=="—","Late reply cannot display previous stock's price")
	check(view.position_button.disabled and view.position_heading.text.contains("미보유"),"Unheld stock cannot pretend to own shares")
	view._select_stock(view._security_index("123459"))
	check(view.chart.candles.size()==2 and view.chart.days==22 and view.chart.display_mode=="line","Cached observed chart and view preferences survive switching")
	check(view.note_editor.text=="동적 종목의 검토 메모","Notes remain isolated by dynamic code")
	gateway._quote_failed("검증 실패")
	check(view.quote_status.text.contains("실패") and view.chart.candles.size()==2,"Stale chart retained with failure label")
	view.simulator.refresh_account()
	check(view.account_status.text.contains("이전 잔고") and view.position_button.disabled,"Account refresh failure marks old balances and blocks allocation")
	var updated := account()
	updated.snapshot_id = "c".repeat(64)
	updated.rows = []
	updated.positions_value = "0"
	view.simulator.set_account(updated)
	check(view.position_button.disabled and view.position_heading.text.contains("미보유"),"Removed holding no longer shows obsolete position")
	view._filter_stocks("123459")
	check(view.stock_buttons[view.selected].visible,"Saved watched code remains searchable after position closes")
	view.flush_profile()
	var saved: Dictionary = Store.new(directory.path_join("workspace.json")).load_profile()
	check(saved.security_names.get("123459")=="검증 종목 9" and saved.notes.has("123459"),"Watched name and note persist together")
	check(not saved.has("account") and not saved.has("positions_value"),"Raw account snapshot is not written to preferences")
	for resolution: Vector2i in [Vector2i(900,680),Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = resolution
		view._select_workspace("market")
		await frames()
		check(view.body.get_global_rect().end.x<=resolution.x+1,"Dynamic list fits width "+str(resolution))
		check(view.brief_panel.get_global_rect().end.y<=resolution.y-18,"Position actions remain reachable "+str(resolution))
	view.queue_free()
	await frames()
	var restored: Control = load("res://scenes/headquarters.tscn").instantiate()
	root.add_child(restored)
	await frames()
	check(restored._security_index("123459")>=0 and restored.securities[restored._security_index("123459")].name=="검증 종목 9","Watched security restored before account connection")
	check(restored.simulator.account.is_empty(),"Restart cannot mistake persisted preferences for live balances")
	restored.queue_free()
	await frames()
	print("MARKET_LIVE_TEST: %d checks, %d failures" % [checks,failures])
	quit(1 if failures else 0)

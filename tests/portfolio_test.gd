extends SceneTree
const Record = preload("res://scripts/operation_record.gd")
const Store = preload("res://scripts/workspace_store.gd")
var checks := 0
var failures := 0
var directory: String

func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_ADVISOR_OFFLINE","1")
	directory = OS.get_environment("TEMP").path_join("phalanx-portfolio-test-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("workspace.json"))
	OS.set_environment("PHALANX_ADVISOR_REQUESTS",directory.path_join("requests"))
	OS.set_environment("PHALANX_ADVISOR_CONFIG",directory.path_join("missing.json"))
	OS.set_environment("OPENAI_API_KEY","")
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func frames() -> void:
	for i: int in 8: await process_frame

func settle(worker: Node) -> void:
	var end := Time.get_ticks_msec()+15000
	while worker.pid>0 and Time.get_ticks_msec()<end: await create_timer(0.05).timeout
	await frames()
	check(worker.pid<0,"Python worker completes")

func fixture() -> Dictionary:
	return {"version":1,"source":"kis_account","currency":"KRW","snapshot_id":"a".repeat(64),"account_masked":"0000****-**","observed_at":"2026-09-29T12:00:00+00:00","positions_value":"2000","summary":{"net_assets":"9000","deposit_total":"7000","securities_evaluation_amount":"2000","profit_loss_total":"100"},"warnings":[],"rows":[
		{"code":"005930","name":"삼성전자","quantity":"10","sellable":"10","price":"100","value":"1000","profit_loss":"50","stock_weight":"50","price_observed_at":"2026-09-29T12:00:00+00:00"},
		{"code":"000660","name":"SK하이닉스","quantity":"5","sellable":"5","price":"200","value":"1000","profit_loss":"50","stock_weight":"50","price_observed_at":"2026-09-29T12:00:00+00:00"}]}

func run() -> void:
	root.gui_embed_subwindows = true
	root.size = Vector2i(1440,960)
	var dashboard: Control = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	await frames()
	dashboard._select_workspace("portfolio")
	var panel: Control = dashboard.simulator
	check(dashboard.live_portfolio_page.visible and not dashboard.market_actions.visible,"Live portfolio has no demo account totals")
	check(not panel.busy and panel.account.is_empty(),"Offline tests cannot auto-query the real account")
	panel.set_account(fixture())
	check(panel.rows.size()==2 and panel.budget_input.value==0,"All holdings shown; deposit is never copied to budget")
	panel.calculate()
	await settle(panel.worker)
	check(not panel.result.is_empty() and panel.result.buy_total==0 and panel.result.sell_total==0,"Current weights preserve holdings without rounding trades")
	panel.budget_input.value = 1000
	panel.rows[0].input.value = 50
	panel.rows[1].input.value = 25
	check(panel.result.is_empty() and panel.order_button.disabled,"Changing targets invalidates previous result")
	panel.calculate()
	await settle(panel.worker)
	check(panel.result.plan.planned_cash==900 and panel.result.buy_total==500 and panel.result.sell_total==400,"Python trade quantities and cash reconcile")
	check(panel.result.plan.base_assets==3000,"Simulation denominator is holdings plus assumed cash, not broker NAV")
	check(not panel.order_button.disabled and panel.rows[0].detail.text.contains("5주"),"Rows and apply action updated")
	panel.review()
	await settle(panel.worker)
	check(panel.result.ai_state=="KEY_MISSING" and not panel.result.plan.is_empty(),"Missing AI key retains simulation")
	panel.apply_order()
	await frames()
	check(dashboard.dialog.visible and dashboard.simulation_plan.source==Record.LIVE_SOURCE,"Apply opens the live plan document")
	check(not dashboard.simulator.has_signal("sample_requested"),"Sample account entry is removed")
	check(dashboard.dialog.document.source_label.text.contains("실계좌") and dashboard.dialog.document.source_label.text.contains("가정"),"Document labels real-snapshot simulation and assumed cash")
	check(not dashboard.save_failed and not dashboard.profile_dirty,"Applied draft persists")
	var stored := Store.new(directory.path_join("workspace.json"))
	var saved: Dictionary = stored.load_profile()
	check(saved.simulation_plan.snapshot_id=="a".repeat(64) and saved.live_operation_draft.rationale.contains("시뮬레이터"),"Plan and evidence reload together")
	dashboard.dialog.document.risk_input.text = "수수료와 결제 가능액 확인"
	dashboard.dialog.document._changed()
	dashboard._record_operation()
	check(dashboard.operations.size()==1 and Record.validate(dashboard.operations[0]),"Live plan can be sealed into validated history")
	check(dashboard.operations[0].source==Record.LIVE_SOURCE and dashboard.operations[0].rows[0].result_quantity==15,"Sealed snapshot keeps calculated quantities and source")
	check(dashboard.simulation_plan.is_empty() and dashboard.live_operation_draft.rationale.is_empty(),"Sealing clears only the live draft")
	dashboard.dialog.hide()
	panel.rows[0].input.value = 90
	panel.calculate()
	await settle(panel.worker)
	check(panel.result.is_empty() and panel.status_label.text.contains("100%"),"Over-allocation is shown and cannot be applied")
	panel._current_weights()
	panel.calculate()
	panel.rows[0].input.value = 40
	await frames()
	check(panel.worker.pid<0 and panel.result.is_empty(),"Editing during calculation cancels stale results")
	panel.refresh_account()
	check(panel.stale and panel.account.rows.size()==2 and panel.calculate_button.disabled,"Failed refresh retains marked old balances and blocks simulation")
	panel.set_account(fixture())
	for dimensions: Vector2i in [Vector2i(900,680),Vector2i(1280,720),Vector2i(1440,960),Vector2i(2160,1440)]:
		root.size = dimensions
		await frames()
		check(dashboard.live_portfolio_page.get_h_scroll_bar().max_value<=dashboard.live_portfolio_page.size.x+2,"No horizontal overflow %s" % dimensions)
		check(panel.refresh_button.get_global_rect().end.x<=dashboard.get_global_rect().end.x,"Refresh reachable %s" % dimensions)
		panel.calculate()
		await settle(panel.worker)
		panel.apply_order()
		await frames()
		var dialog: AcceptDialog = dashboard.dialog
		var rendered: Rect2 = dialog.get_stretch_transform()*dialog.get_ok_button().get_global_rect()
		check(Rect2(Vector2.ZERO,Vector2(dialog.size)).encloses(rendered),"Seal button inside actual mouse bounds %s" % dimensions)
		dialog.hide()
	dashboard._select_workspace("sample")
	check(dashboard.workspace=="portfolio" and dashboard.live_portfolio_page.visible,"Removed sample route cannot open a hidden account")
	dashboard.queue_free()
	await frames()
	for child: String in ["requests"]:
		var path := directory.path_join(child)
		if DirAccess.dir_exists_absolute(path):
			for name: String in DirAccess.get_files_at(path): DirAccess.remove_absolute(path.path_join(name))
			DirAccess.remove_absolute(path)
	for name: String in DirAccess.get_files_at(directory): DirAccess.remove_absolute(directory.path_join(name))
	DirAccess.remove_absolute(directory)
	print("Portfolio integration: %d checks, %d failures" % [checks,failures])
	quit(1 if failures else 0)

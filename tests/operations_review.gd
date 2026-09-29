extends SceneTree
const Fixture = preload("res://tests/operation_fixture.gd")
var app: Control
var output: String
var native := false
func _initialize() -> void:
	OS.set_environment("PHALANX_ACCOUNT_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-operations-review-%d.json" % OS.get_process_id()))
	call_deferred("run")
func hold(seconds := 0.4) -> void:
	await create_timer(seconds).timeout
func capture(label: String) -> void:
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output.path_join(label+".png"))
func run() -> void:
	output = OS.get_cmdline_user_args()[0]
	native = OS.get_cmdline_user_args().has("native")
	root.size = Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await hold()
	app.camp.restore_position(app.camp.entrance_position)
	app.enter_headquarters()
	await hold(1.6)
	await capture("01-headquarters-journal")
	app._open_journal()
	await hold(1.0)
	await capture("02-empty-journal")
	app.dashboard_overlay.close_dashboard()
	await hold(0.6)
	app._open_dashboard()
	await hold(1.0)
	var view: Control = app.dashboard_overlay.dashboard
	view._select_workspace("portfolio")
	Fixture.install(view)
	view._show_plan()
	await hold()
	await capture("03-order-draft")
	if native:
		print("PHALANX_OPERATIONS_REVIEW: native input ready; isolated profile")
		return
	var draft := {"title":"예시 작전 · 현금 여력을 남기는 재배치","rationale":"샘플 포트폴리오를 기준으로 종목별 비중을 점검한다.\n현금 여력을 남겨 다음 판단에 대비한다.","risk":"실제 시세와 연결되지 않은 연습용 계획이다.\n가격 변동과 거래 비용에 따라 결과가 달라질 수 있다."}
	view.dialog.document.display(view.simulation_plan,draft)
	view._operation_draft_changed(draft)
	await hold()
	await capture("04-order-filled")
	view._record_operation()
	await hold(0.5)
	await capture("05-order-sealed")
	view.dialog.hide()
	app.dashboard_overlay.close_dashboard()
	await hold(0.6)
	app._open_journal()
	await hold(1.0)
	await capture("06-journal-record")
	root.size = Vector2i(1280,720)
	await hold()
	await capture("07-journal-1280")
	root.size = Vector2i(960,680)
	await hold()
	await capture("08-journal-960")
	app.dashboard_overlay.close_dashboard()
	await hold(0.6)
	app._open_dashboard()
	await hold(0.8)
	Fixture.install(view)
	view._show_plan()
	await hold()
	await capture("09-order-960")
	view.dialog.hide()
	print("PHALANX_OPERATIONS_REVIEW: PASS (scripted GPU captures)")
	quit()

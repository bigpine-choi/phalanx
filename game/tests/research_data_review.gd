extends SceneTree
## Real provider query through the integrated dashboard; no live account reads.
var app: Control
var dashboard: Control
var output := ""
var summary: Array = []

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	output = args[0]
	OS.set_environment("PHALANX_RESEARCH_CACHE",args[1])
	OS.set_environment("PHALANX_WORKSPACE_PATH",args[1].path_join("review-profile.json"))
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1" if args.has("offline") else "0")
	call_deferred("run")

func frames(count := 8) -> void:
	for index: int in count:
		await process_frame

func capture(name: String) -> void:
	await frames()
	await RenderingServer.frame_post_draw
	if root.get_texture().get_image().save_png(output.path_join(name+".png"))!=OK:
		push_error("Capture failed")
		quit(1)

func wait_quote() -> bool:
	var gateway: Node = dashboard.research_view.gateway
	var deadline := Time.get_ticks_msec()+60000
	while gateway.quote_state=="loading" and Time.get_ticks_msec()<deadline:
		await create_timer(0.1).timeout
	return not gateway.quote.is_empty() and gateway.quote_state in ["ready","cached"]

func run() -> void:
	DirAccess.make_dir_recursive_absolute(output)
	root.content_scale_factor = 1.0
	root.size = Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await frames()
	app.camp.restore_position(app.camp.entrance_position)
	app.camp.try_enter()
	app.dashboard_overlay.open_dashboard()
	await frames()
	dashboard = app.dashboard_overlay.dashboard
	dashboard._select_workspace("research")
	if OS.get_cmdline_user_args().has("native"):
		root.size = Vector2i(1280,720)
		root.title = "Phalanx - KIS research review"
		print("PHALANX_KIS_NATIVE_READY")
		return
	for index: int in 5:
		dashboard._select_stock(index)
		if not await wait_quote():
			push_error("KIS query/cache failed for index "+str(index))
			quit(1)
			return
		var quote: Dictionary = dashboard.research_view.gateway.quote
		summary.append({"code":quote.code,"source":quote.source,"as_of":quote.as_of,"fetched_at":quote.fetched_at,"rows":quote.candles.size(),"state":dashboard.research_view.gateway.quote_state})
		print("KIS_VERIFIED ",JSON.stringify(summary[-1]))
		if index==1:
			await capture("missing-financials-1440x960")
		if index==4:
			await capture("etf-1440x960")
	dashboard._select_stock(0)
	await frames()
	for resolution: Vector2i in [Vector2i(1440,960),Vector2i(1280,720),Vector2i(900,680)]:
		root.min_size = Vector2i(900,680)
		root.size = resolution
		dashboard.research_page.scroll_vertical = 0
		await capture("research-%dx%d" % [resolution.x,resolution.y])
		dashboard.research_page.scroll_vertical = 460
		await capture("financials-%dx%d" % [resolution.x,resolution.y])
	var file := FileAccess.open(output.path_join("provider-verification.json"),FileAccess.WRITE)
	file.store_string(JSON.stringify(summary,"\t"))
	file.close()
	print("PHALANX_RESEARCH_DATA_REVIEW: PASS (GPU, real KIS/public IR)")
	quit()

extends SceneTree
## GPU layout evidence; native mode only sets up the screen, never injects input.
## -- OUTPUT_DIRECTORY [native] [1280]
var app: Control

func _initialize() -> void:
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	if OS.get_environment("PHALANX_WORKSPACE_PATH").is_empty():
		OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-terminal_review-%s-%s.json" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("run")

func frames(count := 8) -> void:
	for index: int in count:
		await process_frame

func run() -> void:
	var args := OS.get_cmdline_user_args()
	var output := args[0]
	DirAccess.make_dir_recursive_absolute(output)
	root.content_scale_factor = 1.0
	root.size = Vector2i(1280,720) if args.has("1280") else Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await frames()
	app.camp.restore_position(app.camp.entrance_position)
	app.camp.try_enter()
	app.dashboard_overlay.open_dashboard()
	await frames(12)
	if args.has("native"):
		root.title = "Phalanx - Investment workspace review %dx%d" % [root.size.x,root.size.y]
		if args.has("saved"):
			root.title = "Phalanx - Saved workspace review"
		if args.has("research"):
			root.title = "Phalanx - Public research review"
			app.dashboard_overlay.dashboard._select_workspace("research")
		print("PHALANX_TERMINAL_NATIVE_READY ",root.size)
		return
	var dashboard: Control = app.dashboard_overlay.dashboard
	for resolution: Vector2i in [Vector2i(1440,960),Vector2i(1280,720),Vector2i(900,680)]:
		root.min_size = Vector2i(900,680)
		root.size = resolution
		await frames()
		for workspace: String in ["market","portfolio","research"]:
			dashboard._select_workspace(workspace)
			await frames()
			await RenderingServer.frame_post_draw
			var path := output.path_join("%s-%dx%d.png" % [workspace,resolution.x,resolution.y])
			var result := root.get_texture().get_image().save_png(path)
			if result!=OK:
				push_error("Screenshot save failed")
				quit(1)
				return
			print("TERMINAL_CAPTURE ",path," chart=",dashboard.chart.get_global_rect()," viewport=",root.size)
	print("PHALANX_TERMINAL_REVIEW: PASS (GPU; synthetic layout setup)")
	quit()

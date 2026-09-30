extends SceneTree
## Actual GPU footage with a scripted tour; not a native-input play recording.
var app: Control
var output := ""

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE", "1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-transition-review-%d.json" % OS.get_process_id()))
	call_deferred("run")

func hold(seconds: float) -> void:
	await create_timer(seconds).timeout

func capture(label: String) -> void:
	if output.is_empty():
		return
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(output.path_join(label+".png"))

func run() -> void:
	var args := OS.get_cmdline_user_args()
	if not args.is_empty():
		output = args[0]
	root.content_scale_factor = 1.0
	root.size = Vector2i(1440,960)
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	current_scene = app
	await hold(0.3)
	app.camp.restore_position(app.camp.entrance_position)
	await hold(0.7)
	await capture("01-camp")
	app.enter_headquarters()
	await hold(0.43)
	await capture("02-enter-transition")
	await hold(1.25)
	await capture("03-headquarters")
	app._open_dashboard()
	await hold(0.33)
	await capture("04-map-unfold")
	await hold(2.0)
	await capture("05-analysis")
	app.dashboard_overlay.close_dashboard()
	await hold(0.8)
	app.return_to_camp()
	await hold(0.46)
	await capture("06-exit-transition")
	await hold(1.8)
	await capture("07-camp-return")
	print("PHALANX_TRANSITION_REVIEW: PASS (actual GPU render; scripted tour)")
	quit()

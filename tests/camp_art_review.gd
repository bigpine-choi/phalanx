extends SceneTree
## HISTORICAL: preserved first-person art review; do not use for current-design acceptance.
## Current scene-flow review/captures: res://tests/quarter_flow_test.gd.
## Optional windowed GPU review. Fixed poses at both sizes; no production input hooks.
## Frame intervals are main-loop wall times, not isolated GPU timings or hardware input latency.
## Outputs belong outside the repository (for example a directory under Windows TEMP).
var camp
var output: String
var phase: String
var failures := 0
func _initialize():
	call_deferred("_run")
func frames(count: int):
	for i in count:
		await process_frame
func capture(label: String):
	await frames(18)
	await RenderingServer.frame_post_draw
	var shot = root.get_texture().get_image()
	var result = shot.save_png(output.path_join("%s-%s-%dx%d.png" % [phase,label,root.size.x,root.size.y]))
	if result != OK or shot.get_size() != root.size:
		failures += 1
		push_error("Capture failed or had an unexpected resolution: " + label)
	print("SHOT ",phase," ",label," ",shot.get_size())
func pose(at: Vector3, target: Vector3):
	camp.player.pause_exploration()
	camp.player.position = at
	camp.player.rotation = Vector3.ZERO
	camp.player.head.rotation = Vector3.ZERO
	camp.player.camera.look_at(target)
	camp.environment.set_table_highlight(false)
	camp.capture_prompt.hide()
	await frames(4)
func stats(values: Array):
	values.sort()
	return {"median_ms": values[values.size()/2], "p95_ms":values[int(values.size()*0.95)]}
func _run():
	var args = OS.get_cmdline_user_args()
	if args.size() != 2:
		push_error("Usage: --script res://tests/camp_art_review.gd -- ABSOLUTE_OUTPUT_DIR LABEL")
		quit(1)
		return
	if not args[0].is_absolute_path():
		push_error("Capture output must be an absolute directory outside the source tree")
		quit(1)
		return
	var project_path = ProjectSettings.globalize_path("res://").replace("\\", "/").to_lower().trim_suffix("/")
	var target_path = args[0].replace("\\", "/").simplify_path().to_lower().trim_suffix("/")
	if target_path == project_path or target_path.begins_with(project_path + "/"):
		push_error("Keep generated images outside the project")
		quit(1)
		return
	if not args[1].is_valid_filename() or DisplayServer.get_name() == "headless":
		push_error("Use a filename-safe label and a windowed rendering driver")
		quit(1)
		return
	if DirAccess.make_dir_recursive_absolute(args[0]) != OK:
		push_error("Cannot create capture directory")
		quit(1)
		return
	output = args[0]
	phase = args[1]
	root.content_scale_factor = 1.0
	root.position = Vector2i(35,35)
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	camp = load("res://scenes/command_camp.tscn").instantiate()
	root.add_child(camp)
	current_scene = camp
	camp.environment.set_process(false)
	if camp.environment.has_node("CampLighting"): camp.environment.get_node("CampLighting").set_process(false)
	await frames(120)
	for size in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = size
		await frames(60)
		await pose(Vector3(0,0.04,-3.1),Vector3(0,1.25,0))
		await capture("01-start")
		var intervals: Array = []
		var last: int = Time.get_ticks_usec()
		for i in 600:
			await process_frame
			var now = Time.get_ticks_usec()
			intervals.append(float(now-last)/1000.0)
			last = now
		print("FRAME_INTERVAL ",phase," ",size," ",JSON.stringify(stats(intervals))," renderer=",RenderingServer.get_current_rendering_method()," adapter=",RenderingServer.get_video_adapter_name())
		await pose(Vector3(0,0.04,-1.56),Vector3(0,1.06,0))
		await capture("02-front")
		await pose(Vector3(-2.56,0.04,-0.10),Vector3(0,1.06,0))
		await capture("03-left")
		await pose(Vector3(2.56,0.04,-0.10),Vector3(0,1.06,0))
		await capture("04-right")
		await pose(Vector3(0,0.04,1.90),Vector3(0,1.06,0))
		await capture("05-behind")
		await pose(Vector3(0,0.04,4.4),Vector3(0,1.30,-1.0))
		await capture("06-entrance")
		await pose(Vector3(0,0.04,-1.56),Vector3(0,1.06,0))
		camp.player.notification(Node.NOTIFICATION_WM_WINDOW_FOCUS_IN)
		camp.player.begin_exploration()
		await frames(5)
		var response_times: Array = []
		for trial in 8:
			var event = InputEventKey.new()
			event.keycode = KEY_E
			event.pressed = true
			var begin = Time.get_ticks_usec()
			Input.parse_input_event(event)
			event = InputEventKey.new()
			event.keycode = KEY_E
			event.pressed = false
			Input.parse_input_event(event)
			for i in 30:
				if camp.dashboard_overlay.is_open(): break
				await process_frame
			await RenderingServer.frame_post_draw
			if camp.dashboard_overlay.is_open():
				response_times.append(float(Time.get_ticks_usec()-begin)/1000.0)
			else:
				failures += 1
				print("INPUT_RESPONSE_FAILED ",phase," size=",size)
			if trial == 7: await capture("07-dashboard")
			camp.dashboard_overlay.close_dashboard()
			await frames(8)
		if not response_times.is_empty(): print("SYNTHETIC_E_TO_DRAW ",phase," ",size," ",JSON.stringify(stats(response_times))," samples=",response_times.size())
		camp.player.pause_exploration()
	print("PASS_A_CAPTURE_DONE ",phase," failures=",failures)
	quit(0 if failures == 0 else 1)

extends SceneTree
## The source JSON is synthetic. Its risk/ERC scenarios were produced by the
## Python research engine, with no real account or credential data.
## Optional GPU capture: --script res://tests/research_allocation_test.gd -- ABSOLUTE_PNG_PATH

const FIXTURE := "res://tests/fixtures/synthetic_research_allocation_targets.json"

var checks := 0
var failures := 0
var directory := ""
var screenshot_path := ""

func _initialize() -> void:
	for key: String in ["PHALANX_ACCOUNT_OFFLINE", "PHALANX_RESEARCH_OFFLINE", "PHALANX_ADVISOR_OFFLINE", "PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key, "1")
	var python := OS.get_environment("PHALANX_RESEARCH_PYTHON")
	if python.is_empty():
		python = OS.get_environment("PHALANX_ADVISOR_PYTHON")
	if python.is_empty() or not FileAccess.file_exists(python):
		print("PHALANX_RESEARCH_ALLOCATION_TEST: SKIP (set PHALANX_RESEARCH_PYTHON to an installed project Python)")
		quit(0)
		return
	directory = OS.get_environment("TEMP").path_join("phalanx-research-allocation-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_WORKSPACE_PATH", directory.path_join("workspace.json"))
	OS.set_environment("PHALANX_ALLOCATION_REQUESTS", directory.path_join("allocation"))
	OS.set_environment("PHALANX_ADVISOR_REQUESTS", directory.path_join("advisor"))
	OS.set_environment("PHALANX_RESEARCH_CACHE", directory.path_join("research"))
	var args := OS.get_cmdline_user_args()
	if not args.is_empty():
		if args.size() != 1 or not args[0].is_absolute_path() or DisplayServer.get_name() == "headless":
			push_error("GPU review requires one absolute PNG path")
			quit(1)
			return
		screenshot_path = args[0]
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func frames(count := 6) -> void:
	for i: int in count:
		await process_frame

func wait_for_load(panel: Control) -> void:
	var deadline := Time.get_ticks_msec() + 20000
	while panel.busy and Time.get_ticks_msec() < deadline:
		await create_timer(0.03).timeout
	await frames()
	check(not panel.busy, "Local projection worker completes within the test deadline")

func capture() -> void:
	if screenshot_path.is_empty():
		return
	await frames(12)
	await RenderingServer.frame_post_draw
	var shot := root.get_texture().get_image()
	check(shot != null and shot.get_size() == root.size, "GPU screenshot has the viewport dimensions")
	if shot != null:
		check(shot.save_png(screenshot_path) == OK, "Save allocation workspace screenshot")
		print("ALLOCATION_CAPTURE ", screenshot_path)

func run() -> void:
	root.gui_embed_subwindows = true
	root.content_scale_factor = 1.0
	root.size = Vector2i(1440, 960)
	root.position = Vector2i(30, 30)
	var dashboard: Control = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	await frames()
	check(dashboard.workspace_buttons.size() == 4, "Headquarters exposes four workspaces")
	var allocation_button: Button = dashboard.workspace_buttons[3]
	check(allocation_button.name == "Workspace_allocation" and allocation_button.visible, "Research allocation is reachable from the actual headquarters header")
	allocation_button.pressed.emit()
	await frames()
	check(dashboard.workspace == "allocation" and dashboard.allocation_page.visible and dashboard.allocation_view.visible, "Header action opens the game research allocation page")
	check(not dashboard.live_portfolio_page.visible and not dashboard.research_page.visible, "Research allocation is separate from account and single-stock research")
	check(dashboard.simulator.account.is_empty() and dashboard.simulation_plan.is_empty(), "Opening research allocation does not inspect or modify the account plan")
	var panel: Control = dashboard.allocation_view
	check(panel.get_node_or_null("TargetsFileDialog") is FileDialog and panel.open_button is Button and panel.open_button.name == "OpenAllocationFile", "The game provides a saved JSON file picker")
	check(panel.scenario_buttons.size() == 4 and panel.scenario_buttons[0].disabled, "Scenario actions wait for a saved file")
	check(FileAccess.file_exists(ProjectSettings.globalize_path(FIXTURE)), "Synthetic backend fixture is packaged with the game test")
	check(panel.load(ProjectSettings.globalize_path(FIXTURE)), "Saved PR32-style target file starts the local projection bridge")
	await wait_for_load(panel)
	if panel.payload.is_empty():
		push_error("First saved result load failed: " + panel.status_label.text)
		dashboard.queue_free()
		await frames()
		print("PHALANX_RESEARCH_ALLOCATION_TEST: FAIL (first file load)")
		quit(1)
		return
	check(panel.payload.get("source_semantics") == "saved_file_unverified" and panel.payload.get("status") == "succeeded", "Actual file-to-Python-to-Godot path yields a saved research result")
	check(panel.payload.get("succeeded_count") == 4 and panel.payload.get("selected_codes", []).size() == 6, "All four calculated scenarios and six selected codes reach the game")
	check(panel.payload.get("replay_provenance") is Dictionary and panel.provenance_label.text.contains("영수증 SHA-256"), "Replay receipt provenance reaches the research page as file-reported evidence")
	check(panel.metadata_label.text.contains("2026-08-20") and panel.metadata_label.text.contains("504건"), "Calculation date and observation count are visible")
	check(panel.status_label.text.contains("재검증하지 않았습니다") and not panel.status_label.text.contains("인증 완료"), "The game does not claim fresh receipt or database verification")
	check(panel.scenario_buttons.all(func(button: Button) -> bool: return not button.disabled), "Four independent scenarios can be inspected")
	check(panel.selected_scenario == 0 and panel.holdings.get_child_count() == 6, "First scenario shows six code/weight rows")
	var first_weight := ""
	if panel.holdings.get_child_count() > 0:
		first_weight = panel.holdings.get_child(0).get_child(1).text
	panel.scenario_buttons[1].pressed.emit()
	await frames()
	check(panel.selected_scenario == 1 and panel.scenario_heading.text.contains("빠른 적응"), "Second scenario button changes the selected result")
	check(panel.holdings.get_child_count() == 6 and panel.holdings.get_child(0).get_child(1).text != first_weight, "Scenario switch updates the actual displayed weights")
	check(dashboard.simulator.account.is_empty() and dashboard.simulation_plan.is_empty(), "Scenario switching does not create an account simulation or order")
	await capture()
	for dimensions: Vector2i in [Vector2i(900, 680), Vector2i(1280, 720), Vector2i(1440, 960)]:
		root.size = dimensions
		await frames(8)
		check(allocation_button.get_global_rect().end.x <= dashboard.get_global_rect().end.x + 1, "Allocation header tab remains reachable at %s" % dimensions)
		check(dashboard.allocation_page.get_h_scroll_bar().max_value <= dashboard.allocation_page.size.x + 2, "Allocation page has no horizontal overflow at %s" % dimensions)
	var invalid_path := directory.path_join("invalid-targets.json")
	var invalid := FileAccess.open(invalid_path, FileAccess.WRITE)
	invalid.store_string('{"schema":"unknown"}')
	invalid.close()
	check(panel.load(invalid_path), "An invalid JSON artifact is handed to the same bridge")
	await wait_for_load(panel)
	check(panel.payload.is_empty() and panel.scenario_buttons[0].disabled and panel.status_label.text.contains("올바르지"), "Invalid artifact clears old weights and explains rejection")
	check(not panel.load(directory.path_join("missing.json")) and panel.payload.is_empty(), "Missing file is rejected without restoring stale data")
	panel.file_dialog.file_selected.emit(ProjectSettings.globalize_path(FIXTURE))
	await wait_for_load(panel)
	check(panel.payload.get("status") == "succeeded" and panel.holdings.get_child_count() == 6, "File picker signal reloads the valid four-scenario result after rejection")
	dashboard.queue_free()
	await frames()
	var request_directory := directory.path_join("allocation")
	if DirAccess.dir_exists_absolute(request_directory):
		for name: String in DirAccess.get_files_at(request_directory):
			DirAccess.remove_absolute(request_directory.path_join(name))
		DirAccess.remove_absolute(request_directory)
	for name: String in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(name))
	DirAccess.remove_absolute(directory)
	print("PHALANX_RESEARCH_ALLOCATION_TEST: %s (%d checks, renderer=%s)" % ["PASS" if failures == 0 else "FAIL (%d)" % failures, checks, DisplayServer.get_name()])
	quit(0 if failures == 0 else 1)

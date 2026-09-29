extends SceneTree
const Worker = preload("res://scripts/advisor_process.gd")
const Model = preload("res://scripts/research_model.gd")
const Record = preload("res://scripts/operation_record.gd")
var checks := 0
var failures := 0
var directory: String
var done := false
var result: Dictionary = {}
var error := ""

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_ADVISOR_OFFLINE","1")
	OS.set_environment("OPENAI_API_KEY","")
	directory = OS.get_environment("TEMP").path_join("phalanx-advisor-%s-%s" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	OS.set_environment("PHALANX_ADVISOR_CONFIG",directory.path_join("config.json"))
	OS.set_environment("PHALANX_ADVISOR_REQUESTS",directory.path_join("requests"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("cache"))
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("workspace.json"))
	call_deferred("run")

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(message)

func frames() -> void:
	for i: int in 8:
		await process_frame

func wait_worker(worker: Node) -> void:
	var end := Time.get_ticks_msec()+15000
	while worker.pid>0 and Time.get_ticks_msec()<end:
		await create_timer(0.05).timeout
	await frames()
	check(worker.pid<0,"Worker completes without timeout")

func click_save(settings: AcceptDialog) -> void:
	var button := settings.get_ok_button()
	var rendered: Rect2 = settings.get_stretch_transform() * button.get_global_rect()
	check(Rect2(Vector2.ZERO,Vector2(settings.size)).encloses(rendered),"Rendered save button stays inside embedded mouse bounds")
	var location := Vector2(settings.position) + rendered.get_center()
	var motion := InputEventMouseMotion.new()
	motion.position = location
	root.push_input(motion,true)
	check(settings.gui_get_hovered_control()==button,"Mouse hits the drawn save button")
	var press := InputEventMouseButton.new()
	press.position = location
	press.button_index = MOUSE_BUTTON_LEFT
	press.pressed = true
	root.push_input(press,true)
	var release := press.duplicate()
	release.pressed = false
	root.push_input(release,true)

func run() -> void:
	root.gui_embed_subwindows = true
	root.size = Vector2i(1440,960)
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	view.storage_path = directory.path_join("workspace.json")
	root.add_child(view)
	view._select_workspace("research")
	await frames()
	var advisor: PanelContainer = view.research_view.advisor
	check(advisor.context.code=="005930","Selected Samsung context connected")
	check(advisor.context.financials.rows.size()==3,"Official IR snapshot connected")
	advisor.request_report("brief",false)
	await wait_worker(advisor.worker)
	check(advisor.report.get("ai_state")=="not_requested" and advisor.report.get("facts",[]).size()==3,"Native Python facts round trip")
	check(not advisor.busy and not advisor.buttons[0].disabled,"Controls restored after result")
	check(DirAccess.get_files_at(advisor.worker.directory).is_empty(),"Request files cleaned after success")
	advisor.request_report("brief",true)
	await wait_worker(advisor.worker)
	check(advisor.report.get("ai_state")=="KEY_MISSING" and advisor.report.get("analysis",[1]).is_empty(),"No key retains facts and never invents AI output")
	advisor.request_report("counter")
	check(not advisor.busy and advisor.status_label.text.contains("먼저"),"Counter requires a thesis")
	view.note_editor.text = "반박할 테스트 가설"
	view._note_changed()
	advisor.request_report("brief",false)
	view._select_stock(1)
	await frames()
	check(not advisor.busy and advisor.report.is_empty() and advisor.context.code=="000660","Selection cancels and invalidates old result")
	check(DirAccess.get_files_at(advisor.worker.directory).is_empty(),"Cancelled request cleaned")
	view._select_stock(0)
	advisor.request_report("brief",false)
	await wait_worker(advisor.worker)
	var fact: Dictionary = advisor.report.facts[0].duplicate(true)
	view.operation_draft.rationale = "기존 사용자 근거"
	view._sync_advisor()
	advisor.request_report("brief",false)
	await wait_worker(advisor.worker)
	advisor._append(fact,false)
	check(view.operation_draft.rationale.begins_with("기존 사용자 근거\n\n") and view.operation_draft.rationale.contains("출처:"),"Appending preserves user rationale with provenance")
	check(not view.profile_dirty and not view.save_failed and view.dialog.visible,"Append saved and opens reviewable draft")
	var saved: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(view.storage_path))
	check(saved.operation_draft.rationale==view.operation_draft.rationale,"Appended evidence persists")
	view.dialog.hide()
	view.operation_draft.risk = "a".repeat(1999)
	view._append_advisor("risk","long")
	check(view.operation_draft.risk.length()==1999,"Draft limit prevents overwrite/truncation")
	view.operation_draft.risk = ""
	view._sync_advisor()
	for dimensions: Vector2i in [Vector2i(960,680),Vector2i(1280,720),Vector2i(1440,960),Vector2i(2160,1440)]:
		root.size = dimensions
		await frames()
		check(advisor.size.x>250 and advisor.size.x<=view.research_page.size.x,"Advisor fits research width %s" % dimensions)
		check(advisor.buttons[2].get_global_rect().end.x<=advisor.get_global_rect().end.x+1,"Buttons fit panel %s" % dimensions)
		check(view.research_page.get_h_scroll_bar().max_value<=view.research_page.size.x+2,"No outer horizontal overflow %s" % dimensions)
		advisor.settings.open_settings()
		await wait_worker(advisor.settings.worker)
		# Headless windows may shrink to their minimum; exercise the actual
		# large-window dimensions that exposed the visible/mouse bounds mismatch.
		var factor := maxf(1.0,minf(dimensions.x/1440.0,dimensions.y/960.0))
		advisor.settings.size = Vector2i(Vector2(660,540)*factor)
		await frames()
		check(advisor.settings.size.x<=root.size.x and advisor.settings.size.y<=root.size.y,"Settings fit viewport %s" % dimensions)
		check(advisor.settings.get_ok_button().get_global_rect().end.y<=advisor.settings.get_visible_rect().size.y,"Save button remains visible %s" % dimensions)
		click_save(advisor.settings)
		await wait_worker(advisor.settings.worker)
		check(advisor.settings.status_label.text=="API 키를 입력해주세요.","Mouse click submits settings %s" % dimensions)
		advisor.settings.hide()
	var settings: AcceptDialog = advisor.settings
	settings.open_settings()
	await wait_worker(settings.worker)
	check(settings.visible and settings.key_input.secret and settings.status_label.text.contains("아직"),"Settings empty and masked")
	settings.key_input.text = "sk-test-never-a-real-key-1234567890"
	settings.key_input.grab_focus()
	var enter := InputEventKey.new()
	enter.keycode = KEY_ENTER
	enter.pressed = true
	root.push_input(enter,true)
	await wait_worker(settings.worker)
	check(settings.key_input.text.is_empty() and settings.status_label.text.contains("키 저장됨"),"Anonymous pipe config round trip")
	check(FileAccess.file_exists(directory.path_join("config.json")),"Encrypted config created")
	check(not FileAccess.get_file_as_string(directory.path_join("config.json")).contains("sk-test"),"Config contains no plaintext key")
	settings.hide()
	settings.open_settings()
	await wait_worker(settings.worker)
	check(settings.key_input.text.is_empty() and settings.status_label.text.contains("키 저장됨"),"Reopen does not reveal key")
	settings.key_input.text = "unsaved-resize-test"
	root.size = Vector2i(960,680)
	await frames()
	check(settings.key_input.text=="unsaved-resize-test","Resize keeps the unsaved key")
	check(settings.position.x>=0 and settings.position.y>=0 and (settings.position+settings.size).x<=root.size.x and (settings.position+settings.size).y<=root.size.y,"Open settings recenters inside resized game")
	settings.hide()
	advisor.request_report("review",true)
	await wait_worker(advisor.worker)
	check(advisor.report.get("ai_state")=="OFFLINE","Offline guard prevents test API requests with dummy key")
	check(advisor.report.get("sources",[]).any(func(s: Dictionary) -> bool: return s.id=="P"),"Review includes plan provenance")
	view.queue_free()
	await frames()
	# Exercise popup Escape in the same overlay routing used by the game.
	var overlay: CanvasLayer = load("res://scripts/dashboard_overlay.gd").new()
	root.add_child(overlay)
	overlay.open_dashboard()
	await create_timer(0.9).timeout
	overlay.dashboard.research_view.advisor.settings.open_settings()
	await wait_worker(overlay.dashboard.research_view.advisor.settings.worker)
	var event := InputEventKey.new()
	event.keycode = KEY_ESCAPE
	event.pressed = true
	overlay._on_plan_window_input(event)
	check(not overlay.dashboard.research_view.advisor.settings.visible and overlay.is_open(),"Escape dismisses settings only")
	overlay._input(event)
	check(overlay.is_open(),"Same Escape cannot also dismiss map")
	overlay.queue_free()
	await frames()
	# All paths below are generated test paths in this test's own directory.
	for child: String in ["requests","cache"]:
		var path := directory.path_join(child)
		if not DirAccess.dir_exists_absolute(path):
			continue
		for file: String in DirAccess.get_files_at(path):
			DirAccess.remove_absolute(path.path_join(file))
		DirAccess.remove_absolute(path)
	for file: String in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
	print("Advisor integration: %d checks, %d failures" % [checks,failures])
	quit(1 if failures else 0)

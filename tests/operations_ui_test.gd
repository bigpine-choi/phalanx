extends SceneTree
const Record = preload("res://scripts/operation_record.gd")
var app: Control
var checks := 0
var failures := 0
func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",OS.get_environment("TEMP").path_join("phalanx-operation-ui-%d.json" % OS.get_process_id()))
	call_deferred("run")
func check(value: bool, description: String) -> void:
	checks += 1
	if not value:
		failures += 1
		push_error(description)
func settle() -> void:
	await create_timer(0.85).timeout
func click(at: Vector2) -> void:
	for pressed: bool in [true,false]:
		var event := InputEventMouseButton.new()
		event.position = at
		event.global_position = at
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame
	await settle()
func escape() -> void:
	for pressed: bool in [true,false]:
		var event := InputEventKey.new()
		event.keycode = KEY_ESCAPE
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame
	await settle()
func run() -> void:
	app = load("res://scenes/phalanx.tscn").instantiate()
	root.add_child(app)
	app.camp.restore_position(app.camp.entrance_position)
	app.enter_headquarters()
	await create_timer(1.5).timeout
	var overlay: CanvasLayer = app.dashboard_overlay
	for window_size: Vector2i in [Vector2i(1440,960),Vector2i(1280,720),Vector2i(960,680),Vector2i(2160,1440)]:
		root.size = window_size
		await settle()
		await click(app.world_to_view(app.headquarters.journal_center))
		check(overlay.is_open() and overlay.journal.visible and not overlay.dashboard_host.visible,"Scroll hotspot opens journal at "+str(window_size))
		check(not app.headquarters.active,"Journal blocks background interactions")
		var journal: Control = overlay.journal
		var record := Record.create([18,16,22,8,14],{"title":"긴 작전 이름의 표시 검증 ".repeat(4),"rationale":"읽기 전용 근거","risk":"읽기 전용 위험"})
		var older := record.duplicate(true)
		older.title = "이전 작전"
		journal.set_records([older,record])
		await settle()
		check(journal.entry_buttons.size()==2 and journal.records[0].title==record.title,"History is newest first")
		check(not journal.document.rationale_input.editable and not journal.document.risk_input.editable,"Historical fields cannot be edited")
		check(journal.document.size.x>400 and journal.document.size.y>250,"Paper has usable area at "+str(window_size))
		check(journal.entry_buttons[0].size.x<=journal.list.size.x,"Long title does not expand history list")
		journal._select(1)
		check(journal.document.title_input.text=="이전 작전","Selecting older record shows its own snapshot")
		await escape()
		check(not overlay.is_open() and app.mode=="headquarters","Esc closes journal without leaving HQ")
		await click(app.world_to_view(app.headquarters.table_center))
		check(overlay.dashboard_host.visible and not journal.visible,"Map still opens analysis after journal")
		overlay.dashboard._show_plan()
		await settle()
		var dialog: AcceptDialog = overlay.dashboard.dialog
		check(dialog.visible and dialog.size.x<=root.size.x and dialog.size.y<=root.size.y,"Order popup fits viewport")
		await escape()
		check(not dialog.visible and overlay.is_open(),"Esc closes only document first")
		await escape()
		check(not overlay.is_open() and app.mode=="headquarters","Second Esc returns to HQ")
	print("PHALANX_OPERATIONS_UI_TEST: %s (%d checks; synthetic viewport input)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

extends CanvasLayer
## Owns one lazy dashboard instance and all modal UI/input behavior.

signal opened
signal closed

const DashboardScene := preload("res://scenes/headquarters.tscn")
const TerminalTheme := preload("res://scripts/terminal_theme.gd")
const Journal := preload("res://scripts/operation_journal.gd")

var dashboard: Control
var blocker: Control
var close_button: Button
var dashboard_host: Control
var presentation: Control
var background: ColorRect
var journal: Control
var header_title: Label
var _content: Control
var phase := "closed"
var _tween: Tween
var _origin_ratio := Vector2(0.5, 0.65)
var _last_escape_event: InputEventKey
@export var framed_interior := false

func _ready() -> void:
	layer = 10
	blocker = Control.new()
	blocker.name = "DashboardModal"
	blocker.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	blocker.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(blocker)
	background = ColorRect.new()
	background.color = Color(0.035, 0.027, 0.018, 0.86) if framed_interior else TerminalTheme.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	blocker.add_child(background)
	presentation = Control.new()
	presentation.name = "UnfoldingWarTable"
	presentation.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	blocker.add_child(presentation)
	var layout := VBoxContainer.new()
	layout.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	if framed_interior:
		layout.offset_left = 18
		layout.offset_top = 16
		layout.offset_right = -18
		layout.offset_bottom = -16
	layout.add_theme_constant_override("separation", 0)
	presentation.add_child(layout)
	var header := PanelContainer.new()
	var header_style := StyleBoxFlat.new()
	header_style.bg_color = Color("211a13")
	header_style.border_color = TerminalTheme.BORDER
	header_style.set_border_width_all(1)
	header_style.content_margin_left = 28
	header_style.content_margin_right = 28
	header_style.content_margin_top = 7
	header_style.content_margin_bottom = 7
	header.add_theme_stylebox_override("panel", header_style)
	layout.add_child(header)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 20)
	header.add_child(row)
	blocker.theme = TerminalTheme.create()
	header_title = Label.new()
	header_title.text = "◆  원정군 사령부    /    작전 지도"
	header_title.add_theme_color_override("font_color", TerminalTheme.GOLD)
	header_title.add_theme_font_size_override("font_size", 12)
	header_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(header_title)
	close_button = Button.new()
	close_button.name = "ReturnToCamp"
	close_button.text = "지도 접기  ·  Esc"
	close_button.custom_minimum_size = Vector2(160, 30)
	close_button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	close_button.pressed.connect(close_dashboard)
	row.add_child(close_button)
	dashboard_host = Control.new()
	dashboard_host.name = "DashboardHost"
	dashboard_host.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_child(dashboard_host)
	journal = Journal.new()
	journal.name = "OperationJournal"
	journal.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_child(journal)
	journal.hide()
	blocker.resized.connect(_resize_presentation)
	get_viewport().size_changed.connect(_fit_ui)
	_fit_ui()
	blocker.hide()

func _fit_ui() -> void:
	var viewport_size := get_viewport().get_visible_rect().size
	var factor := maxf(1.0, minf(viewport_size.x / 1440.0, viewport_size.y / 960.0))
	scale = Vector2.ONE * factor
	blocker.size = viewport_size / factor

func open_dashboard(origin := Vector2.INF, journal_only := false) -> void:
	if is_open():
		return
	if not is_instance_valid(dashboard):
		dashboard = DashboardScene.instantiate()
		dashboard.name = "DashboardInstance"
		dashboard.set("embedded_in_camp", true)
		dashboard_host.add_child(dashboard)
		dashboard.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		# Handle Esc here before hiding either UI layer. AcceptDialog's built-in
		# handler would otherwise hide the popup before window_input reaches us.
		dashboard.dialog.dialog_close_on_escape = false
		dashboard.dialog.window_input.connect(_on_plan_window_input)
		dashboard.research_view.advisor.settings.dialog_close_on_escape = false
		dashboard.research_view.advisor.settings.window_input.connect(_on_plan_window_input)
	dashboard_host.visible = not journal_only
	journal.visible = journal_only
	_content = journal if journal_only else dashboard
	header_title.text = "◆  원정군 사령부    /    작전 일지" if journal_only else "◆  원정군 사령부    /    작전 지도"
	close_button.text = "두루마리 접기  ·  Esc" if journal_only else "지도 접기  ·  Esc"
	if journal_only:
		journal.set_records(dashboard.operations)
	if origin.is_finite():
		_origin_ratio = origin / (blocker.size * scale)
	phase = "opening"
	blocker.show()
	close_button.disabled = true
	presentation.pivot_offset = blocker.size * 0.5
	presentation.position = blocker.size * (_origin_ratio - Vector2(0.5,0.5))
	presentation.scale = Vector2(0.46,0.025)
	presentation.modulate.a = 0.2
	background.modulate.a = 0.0
	_content.modulate.a = 0.0
	opened.emit()
	_tween = create_tween().set_parallel(true)
	_tween.tween_property(background,"modulate:a",1.0,0.42).set_trans(Tween.TRANS_SINE)
	_tween.tween_property(presentation,"position",Vector2.ZERO,0.62).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_tween.tween_property(presentation,"scale:x",1.0,0.35).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_tween.tween_property(presentation,"scale:y",1.0,0.60).set_delay(0.10).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN_OUT)
	_tween.tween_property(presentation,"modulate:a",1.0,0.18)
	_tween.tween_property(_content,"modulate:a",1.0,0.30).set_delay(0.23)
	_tween.chain().tween_callback(_finish_open)

func _finish_open() -> void:
	phase = "open"
	presentation.position = Vector2.ZERO
	presentation.scale = Vector2.ONE
	presentation.modulate.a = 1.0
	_content.modulate.a = 1.0
	background.modulate.a = 1.0
	close_button.disabled = false
	close_button.grab_focus()

func close_dashboard() -> void:
	if not is_open() or phase == "closing":
		return
	if is_instance_valid(dashboard):
		dashboard.flush_profile()
		dashboard.catalog_panel.close()
		dashboard.dialog.hide()
		dashboard.research_view.advisor.settings.hide()
	if is_instance_valid(_tween):
		_tween.kill()
	phase = "closing"
	close_button.disabled = true
	_tween = create_tween().set_parallel(true)
	_tween.tween_property(_content,"modulate:a",0.0,0.18)
	_tween.tween_property(presentation,"scale",Vector2(0.46,0.025),0.36).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN)
	_tween.tween_property(presentation,"position",blocker.size*(_origin_ratio-Vector2(0.5,0.5)),0.36).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN)
	_tween.tween_property(presentation,"modulate:a",0.0,0.15).set_delay(0.22)
	_tween.tween_property(background,"modulate:a",0.0,0.35).set_trans(Tween.TRANS_SINE)
	_tween.chain().tween_callback(_finish_close)

func _finish_close() -> void:
	phase = "closed"
	blocker.hide()
	closed.emit()

func _resize_presentation() -> void:
	presentation.pivot_offset = blocker.size * 0.5
	# A resize finishes the current motion instead of leaving stale pixel targets.
	if is_transitioning():
		if is_instance_valid(_tween):
			_tween.kill()
		if phase == "opening":
			_finish_open()
		else:
			_finish_close()

func is_transitioning() -> bool:
	return phase == "opening" or phase == "closing"

func is_open() -> bool:
	return is_instance_valid(blocker) and blocker.visible

func _input(event: InputEvent) -> void:
	if is_transitioning():
		get_viewport().set_input_as_handled()
		return
	if not is_open() or not _consume_escape(event):
		return
	if dashboard.catalog_panel.visible:
		dashboard.catalog_panel.close()
		return
	var popup: Window = dashboard.active_popup()
	if popup != null:
		popup.hide()
	else:
		close_dashboard()

func _on_plan_window_input(event: InputEvent) -> void:
	# Native popup input does not go through the root viewport. This route may
	# dismiss only the popup, never the dashboard underneath it.
	if is_open() and _consume_escape(event):
		var popup: Window = dashboard.active_popup()
		if popup != null:
			popup.hide()

func _consume_escape(event: InputEvent) -> bool:
	if not event is InputEventKey or event.keycode != KEY_ESCAPE:
		return false
	get_viewport().set_input_as_handled()
	dashboard.dialog.set_input_as_handled()
	dashboard.research_view.advisor.settings.set_input_as_handled()
	if not event.pressed or event.echo or event == _last_escape_event:
		return false
	# Keep the event itself alive so its instance ID cannot be reused. If the
	# same dispatch reaches both windows, it still dismisses only one layer.
	_last_escape_event = event
	return true

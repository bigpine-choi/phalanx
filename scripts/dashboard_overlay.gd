extends CanvasLayer
## Owns one lazy dashboard instance and all modal UI/input behavior.

signal opened
signal closed

const DashboardScene := preload("res://scenes/headquarters.tscn")

var dashboard: Control
var blocker: Control
var close_button: Button
var dashboard_host: Control

func _ready() -> void:
	layer = 10
	blocker = Control.new()
	blocker.name = "DashboardModal"
	blocker.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	blocker.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(blocker)
	var background := ColorRect.new()
	background.color = Color("0c131e")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	blocker.add_child(background)
	var layout := VBoxContainer.new()
	layout.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	layout.add_theme_constant_override("separation", 0)
	blocker.add_child(layout)
	var header := PanelContainer.new()
	var header_style := StyleBoxFlat.new()
	header_style.bg_color = Color("251b1c")
	header_style.border_color = Color("a4824c")
	header_style.border_width_bottom = 1
	header_style.content_margin_left = 28
	header_style.content_margin_right = 28
	header_style.content_margin_top = 10
	header_style.content_margin_bottom = 10
	header.add_theme_stylebox_override("panel", header_style)
	layout.add_child(header)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 20)
	header.add_child(row)
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"])
	var ui_theme := Theme.new()
	ui_theme.default_font = font
	ui_theme.default_font_size = 14
	blocker.theme = ui_theme
	var title := Label.new()
	title.text = "작전 테이블  /  투자 대시보드  ·  가상 데이터"
	title.add_theme_color_override("font_color", Color("e9d4ab"))
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(title)
	close_button = Button.new()
	close_button.name = "ReturnToCamp"
	close_button.text = "사령부로 돌아가기  ·  Esc"
	close_button.custom_minimum_size = Vector2(220, 40)
	close_button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	close_button.pressed.connect(close_dashboard)
	row.add_child(close_button)
	dashboard_host = Control.new()
	dashboard_host.name = "DashboardHost"
	dashboard_host.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_child(dashboard_host)
	blocker.hide()

func open_dashboard() -> void:
	if is_open():
		return
	if not is_instance_valid(dashboard):
		dashboard = DashboardScene.instantiate()
		dashboard.name = "DashboardInstance"
		dashboard.set("embedded_in_camp", true)
		dashboard_host.add_child(dashboard)
		dashboard.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		# Native popup keys bypass the parent viewport. Its X/OK keep their usual behavior.
		dashboard.dialog.window_input.connect(_input)
	blocker.show()
	close_button.grab_focus()
	opened.emit()

func close_dashboard() -> void:
	if not is_open():
		return
	if is_instance_valid(dashboard):
		dashboard.dialog.hide()
	blocker.hide()
	closed.emit()

func is_open() -> bool:
	return is_instance_valid(blocker) and blocker.visible

func _input(event: InputEvent) -> void:
	if is_open() and event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE:
		get_viewport().set_input_as_handled()
		close_dashboard()

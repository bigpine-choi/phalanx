extends Control
## Shared chrome for the two fixed views; no movement or transition logic.

signal return_requested
signal enter_requested

var return_button: Button
var enter_button: Button
var location_label: Label
var instruction_label: Label
var status_label: Label
var _header: PanelContainer
var _footer: PanelContainer

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	# World sprites sort by their ground Y; interface always stays above them.
	z_index = 2000
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"])
	var skin := Theme.new()
	skin.default_font = font
	skin.default_font_size = 14
	theme = skin
	_header = PanelContainer.new()
	_header.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	_header.offset_bottom = 64
	_header.mouse_filter = Control.MOUSE_FILTER_STOP
	_header.add_theme_stylebox_override("panel", _panel_style())
	add_child(_header)
	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 24)
	_header.add_child(row)
	row.add_child(_label("☼  P H A L A N X", 22, Color("e8cd90")))
	row.add_child(_label("/", 19, Color("7d7664")))
	location_label = _label("원정 야영지", 18, Color("f0e5d0"))
	location_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(location_label)
	return_button = _button("←  야영지로  ·  Esc")
	return_button.pressed.connect(func() -> void: return_requested.emit())
	row.add_child(return_button)
	_footer = PanelContainer.new()
	_footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	_footer.offset_top = -71
	_footer.mouse_filter = Control.MOUSE_FILTER_STOP
	_footer.add_theme_stylebox_override("panel", _panel_style())
	add_child(_footer)
	var lower := HBoxContainer.new()
	lower.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lower.add_theme_constant_override("separation", 20)
	_footer.add_child(lower)
	var text_column := VBoxContainer.new()
	text_column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	text_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	lower.add_child(text_column)
	instruction_label = _label("목적지를 클릭해 이동", 16, Color("ede0c5"))
	text_column.add_child(instruction_label)
	status_label = _label("사령부 입구로 이동한 뒤 입장하세요.", 12, Color("b8b39f"))
	text_column.add_child(status_label)
	enter_button = _button("사령부 입장  →")
	enter_button.pressed.connect(func() -> void: enter_requested.emit())
	lower.add_child(enter_button)
	lower.add_child(_label("가상 데이터  ·  실제 계좌 미연결", 12, Color("bca780")))
	set_location("camp")

func set_location(mode: String) -> void:
	return_button.visible = mode == "headquarters"
	enter_button.visible = false
	location_label.text = "원정 야영지" if mode == "camp" else "마케도니아 원정군 사령부"
	instruction_label.text = "목적지를 클릭해 이동" if mode == "camp" else "작전 지도를 클릭해 포트폴리오 검토"
	status_label.text = "사령부 입구로 이동한 뒤 입장하세요." if mode == "camp" else "고정 시점  ·  마우스로 지도 선택  ·  Esc 야영지로"

func set_near_entrance(value: bool) -> void:
	enter_button.visible = value
	status_label.text = "입구를 다시 클릭하거나 ‘사령부 입장’을 선택하세요." if value else "사령부 입구로 이동한 뒤 입장하세요."

func set_table_hover(value: bool) -> void:
	instruction_label.text = "클릭  ·  포트폴리오 검토 열기" if value else "작전 지도를 클릭해 포트폴리오 검토"

func _label(text: String, font_size: int, tint: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", tint)
	return label

func _button(text: String) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(200, 39)
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_color_override("font_color", Color("f1dfb3"))
	for state in ["normal", "hover", "pressed", "focus"]:
		var style := _panel_style()
		style.bg_color = Color("403324") if state in ["hover", "pressed"] else Color("221e18")
		style.border_color = Color("c4a05e")
		style.set_border_width_all(1)
		style.set_corner_radius_all(3)
		button.add_theme_stylebox_override(state, style)
	return button

func _panel_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.035, 0.042, 0.037, 0.90)
	style.border_color = Color(0.65, 0.51, 0.28, 0.58)
	style.border_width_bottom = 1
	style.content_margin_left = 26
	style.content_margin_right = 26
	style.content_margin_top = 12
	style.content_margin_bottom = 12
	return style

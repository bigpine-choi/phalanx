extends Node3D
## Scene wiring and the camp HUD; geometry, picking, and modal UI live separately.

@onready var environment = $Environment
@onready var table_interaction = $TableInteraction
@onready var dashboard_overlay = $DashboardOverlay

var camp_hud: CanvasLayer
var hover_hint: Label

func _ready() -> void:
	get_window().min_size = Vector2i(960, 680)
	table_interaction.camera = environment.get_node("CampCamera")
	table_interaction.hover_changed.connect(_table_hover_changed)
	table_interaction.activated.connect(dashboard_overlay.open_dashboard)
	dashboard_overlay.opened.connect(_dashboard_opened)
	dashboard_overlay.closed.connect(_dashboard_closed)
	_build_hud()

func _build_hud() -> void:
	camp_hud = CanvasLayer.new()
	camp_hud.name = "CampHUD"
	camp_hud.layer = 1
	add_child(camp_hud)
	var hud := Control.new()
	hud.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	camp_hud.add_child(hud)
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"])
	var hud_theme := Theme.new()
	hud_theme.default_font = font
	hud_theme.default_font_size = 14
	hud.theme = hud_theme
	var title_panel := PanelContainer.new()
	title_panel.position = Vector2(32, 30)
	title_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	title_panel.add_theme_stylebox_override("panel", _hud_style())
	hud.add_child(title_panel)
	var titles := VBoxContainer.new()
	titles.mouse_filter = Control.MOUSE_FILTER_IGNORE
	titles.add_theme_constant_override("separation", 7)
	title_panel.add_child(titles)
	titles.add_child(_label("P H A L A N X   /   H E A D Q U A R T E R S", 12, Color("cdb181")))
	titles.add_child(_label("마케도니아 원정군 사령부", 25, Color("f4e4c5")))
	titles.add_child(_label("원정의 다음 수를 준비하는 곳", 13, Color("c4b7a0")))
	var bottom := PanelContainer.new()
	bottom.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	bottom.offset_left = 32
	bottom.offset_right = -32
	bottom.offset_top = -86
	bottom.offset_bottom = -26
	bottom.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bottom.add_theme_stylebox_override("panel", _hud_style())
	hud.add_child(bottom)
	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 24)
	bottom.add_child(row)
	hover_hint = _label("중앙 테이블 위에 마우스를 올려보세요", 17, Color("e5d3ae"))
	hover_hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(hover_hint)
	row.add_child(_label("가상 데이터 사용  ·  실제 계좌 미연결", 12, Color("c8b389")))

func _label(text: String, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_color_override("font_color", color)
	label.add_theme_font_size_override("font_size", font_size)
	return label

func _hud_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.10, 0.075, 0.065, 0.90)
	style.border_color = Color("77603b")
	style.border_width_left = 3
	style.content_margin_left = 20
	style.content_margin_right = 20
	style.content_margin_top = 14
	style.content_margin_bottom = 14
	return style

func _table_hover_changed(value: bool) -> void:
	environment.set_table_highlight(value)
	if is_instance_valid(hover_hint):
		hover_hint.text = "작전 테이블 열기  ·  마우스 왼쪽 클릭" if value else "중앙 테이블 위에 마우스를 올려보세요"
		hover_hint.modulate = Color("ffd895") if value else Color.WHITE

func _dashboard_opened() -> void:
	table_interaction.set_interaction_enabled(false)
	camp_hud.hide()

func _dashboard_closed() -> void:
	table_interaction.set_interaction_enabled(true)
	camp_hud.show()

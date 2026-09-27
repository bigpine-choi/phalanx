extends Node3D
## Scene wiring and HUD. Movement, collision, selection and modal UI stay separate.

@onready var environment = $Environment
@onready var table_interaction = $TableInteraction
@onready var dashboard_overlay = $DashboardOverlay
@onready var player = $Player

var camp_hud: CanvasLayer
var hover_hint: Label
var crosshair: Panel
var capture_prompt: PanelContainer

func _ready() -> void:
	get_window().min_size = Vector2i(960, 680)
	$CampCollision.build(environment)
	table_interaction.camera = player.camera
	table_interaction.hover_changed.connect(_table_hover_changed)
	table_interaction.activated.connect(dashboard_overlay.open_dashboard)
	dashboard_overlay.opened.connect(_dashboard_opened)
	dashboard_overlay.closed.connect(_dashboard_closed)
	player.exploration_changed.connect(_exploration_changed)
	_build_hud()
	_exploration_changed(player.exploring)

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
	hover_hint = _label("클릭하여 탐색 시작", 17, Color("e5d3ae"))
	hover_hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(hover_hint)
	row.add_child(_label("가상 데이터 사용  ·  실제 계좌 미연결", 12, Color("c8b389")))
	crosshair = Panel.new()
	crosshair.name = "AimReticle"
	crosshair.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(crosshair)
	crosshair.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	crosshair.offset_left = -3
	crosshair.offset_top = -3
	crosshair.offset_right = 3
	crosshair.offset_bottom = 3
	var reticle_style := StyleBoxFlat.new()
	reticle_style.bg_color = Color("f4e4c5")
	reticle_style.border_color = Color("342b23")
	reticle_style.set_border_width_all(1)
	reticle_style.set_corner_radius_all(3)
	crosshair.add_theme_stylebox_override("panel", reticle_style)
	capture_prompt = PanelContainer.new()
	capture_prompt.name = "CapturePrompt"
	capture_prompt.mouse_filter = Control.MOUSE_FILTER_IGNORE
	capture_prompt.add_theme_stylebox_override("panel", _hud_style())
	hud.add_child(capture_prompt)
	capture_prompt.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	capture_prompt.offset_left = -240
	capture_prompt.offset_right = 240
	capture_prompt.offset_top = -44
	capture_prompt.offset_bottom = 44
	var prompt := _label("클릭하여 탐색 시작\nWASD 이동 · 마우스 시선 · Esc 마우스 해제", 17, Color("f4e4c5"))
	prompt.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	capture_prompt.add_child(prompt)

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
		hover_hint.text = "E — 작전 테이블 열기" if value else ("WASD 이동 · 마우스 시선 · Esc 마우스 해제" if player.exploring else "클릭하여 탐색 시작")
		hover_hint.modulate = Color("ffd895") if value else Color.WHITE
		crosshair.modulate = Color("ffd895") if value else Color.WHITE

func _exploration_changed(value: bool) -> void:
	var active: bool = value and not dashboard_overlay.is_open()
	table_interaction.set_interaction_enabled(active)
	if is_instance_valid(crosshair):
		crosshair.visible = active
		capture_prompt.visible = not active and not dashboard_overlay.is_open()
		_table_hover_changed(false)

func _dashboard_opened() -> void:
	table_interaction.set_interaction_enabled(false)
	player.set_modal_blocked(true)
	camp_hud.hide()

func _dashboard_closed() -> void:
	camp_hud.show()
	player.set_modal_blocked(false)
	_exploration_changed(player.exploring)

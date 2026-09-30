extends AcceptDialog
signal draft_changed(value: Dictionary)
signal record_requested
const Document := preload("res://scripts/operation_document.gd")
const T := preload("res://scripts/terminal_theme.gd")
var document: PanelContainer
var feedback: Label
var recorded := false

func _ready() -> void:
	title = "Phalanx · 작전 명령서"
	theme = T.create()
	theme.set_constant("buttons_min_height","AcceptDialog",44)
	min_size = Vector2i(620,460)
	dialog_hide_on_ok = false
	ok_button_text = "명령서 봉인 · 기록"
	add_cancel_button("닫기")
	var column := VBoxContainer.new()
	column.custom_minimum_size = Vector2(590,360)
	add_child(column)
	document = Document.new()
	document.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(document)
	document.draft_changed.connect(func(value: Dictionary) -> void: draft_changed.emit(value))
	feedback = Label.new()
	feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	feedback.custom_minimum_size.y = 32
	feedback.add_theme_font_size_override("font_size",12)
	column.add_child(feedback)
	confirmed.connect(func() -> void:
		if not recorded:
			record_requested.emit())
	get_parent().get_viewport().size_changed.connect(_fit_window)

func open_plan(plan: Dictionary, draft: Dictionary) -> void:
	recorded = false
	get_ok_button().disabled = false
	ok_button_text = "명령서 봉인 · 기록"
	document.display(plan,draft)
	show_feedback("작전 이름·판단 근거·주요 위험을 작성한 뒤 기록하세요. 초안도 자동 저장됩니다.",false)
	_fit_window(true)

func _fit_window(opening := false) -> void:
	if not opening and not visible: return
	var viewport_size: Vector2 = get_parent().get_viewport_rect().size
	var factor := maxf(1.0,minf(viewport_size.x/1440.0,viewport_size.y/960.0))
	var logical_size := viewport_size/factor
	var desired := Vector2(mini(850,int(logical_size.x)-60),mini(800,int(logical_size.y)-80))
	content_scale_size = Vector2i.ZERO
	content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	content_scale_factor = factor
	popup_centered(Vector2i(desired*factor))

func show_feedback(message: String, error := true) -> void:
	feedback.text = message
	feedback.add_theme_color_override("font_color",T.RED if error else T.GOLD)

func saved(record: Dictionary) -> void:
	recorded = true
	get_ok_button().disabled = true
	ok_button_text = "기록 완료"
	document.display(record,record,true)
	document.stamp()
	show_feedback("봉인 완료 · 사령부의 ‘작전 일지’ 두루마리에서 다시 읽을 수 있습니다.",false)

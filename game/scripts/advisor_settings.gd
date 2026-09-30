extends AcceptDialog
signal configuration_changed
const T = preload("res://scripts/terminal_theme.gd")
const Worker = preload("res://scripts/advisor_process.gd")
var key_input: LineEdit
var model_input: LineEdit
var status_label: Label
var worker: Node

func _ready() -> void:
	title = "참모 · OpenAI 연결 설정"
	theme = T.create()
	theme.default_font_size = 16
	theme.set_constant("buttons_min_height","AcceptDialog",44)
	theme.set_constant("buttons_min_width","AcceptDialog",150)
	min_size = Vector2i(540,380)
	dialog_hide_on_ok = false
	ok_button_text = "암호화하여 저장"
	add_cancel_button("닫기")
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(500,360)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation",12)
	scroll.add_child(column)
	for text: String in ["OpenAI API 연결", "API 키는 이 Windows 사용자 계정으로 암호화해 보관합니다.\n저장만으로는 API를 호출하지 않습니다."]:
		var label := _label(text)
		if text=="OpenAI API 연결":
			label.add_theme_font_size_override("font_size",20)
			label.add_theme_color_override("font_color",T.GOLD)
		column.add_child(label)
	key_input = LineEdit.new()
	key_input.secret = true
	key_input.max_length = 1024
	key_input.placeholder_text = "API 키 붙여넣기 · 기존 키 유지 시 비워 두세요"
	column.add_child(key_input)
	register_text_enter(key_input)
	column.add_child(_label("사용할 모델"))
	model_input = LineEdit.new()
	model_input.text = "gpt-5.4-mini"
	model_input.max_length = 100
	column.add_child(model_input)
	register_text_enter(model_input)
	column.add_child(_label("브리핑 요청 시 선택 종목 자료와 노트를 OpenAI에 전송합니다.\n작전 검토에는 모의 목표 비중·명령서 초안도 포함합니다.\nAPI 사용료는 OpenAI API 계정에 별도로 발생합니다."))
	var link := LinkButton.new()
	link.text = "OpenAI API 키 관리 열기 ↗"
	link.pressed.connect(func() -> void: OS.shell_open("https://platform.openai.com/api-keys"))
	column.add_child(link)
	status_label = _label("")
	column.add_child(status_label)
	worker = Worker.new()
	add_child(worker)
	worker.completed.connect(_completed)
	confirmed.connect(_save)
	get_parent().get_viewport().size_changed.connect(_fit_window)
	visibility_changed.connect(func() -> void:
		if not visible:
			key_input.clear())

func _label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size",14)
	return label

func open_settings() -> void:
	key_input.clear()
	get_ok_button().disabled = true
	status_label.text = "연결 설정 확인 중…"
	_fit_window(true)
	key_input.grab_focus()
	worker.request("status")

func _fit_window(opening := false) -> void:
	if not opening and not visible:
		return
	var viewport_size: Vector2 = get_parent().get_viewport_rect().size
	var factor := maxf(1.0,minf(viewport_size.x/1440.0,viewport_size.y/960.0))
	# AcceptDialog lays out its children using size / content_scale_factor.
	# A fixed content_scale_size stretches those children a second time, placing
	# the drawn button outside the embedded window's mouse input bounds.
	content_scale_size = Vector2i.ZERO
	content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	content_scale_factor = factor
	popup_centered(Vector2i(Vector2(660,540)*factor))

func _save() -> void:
	if get_ok_button().disabled:
		return
	get_ok_button().disabled = true
	status_label.text = "암호화하여 저장 중…"
	var value := {"key":key_input.text,"model":model_input.text}
	worker.request("configure",value)
	key_input.clear()

func _completed(action: String, payload: Dictionary, error: String) -> void:
	get_ok_button().disabled = false
	if not error.is_empty():
		var messages := {"KEY_MISSING":"API 키를 입력해주세요.","KEY_INVALID":"API 키 형식을 확인해주세요.","KEY_UNREADABLE":"저장된 키를 읽지 못했습니다. 현재 Windows 계정에서 키를 다시 저장해주세요.","KEY_STORAGE_FAILED":"Windows 암호화 저장에 실패했습니다. 현재 사용자 계정과 실행 환경을 확인해주세요.","MODEL_INVALID":"모델 이름을 확인해주세요.","PYTHON_UNAVAILABLE":"Python 실행 환경을 찾지 못했습니다. Phalanx 연결 경로를 확인해주세요."}
		status_label.text = messages.get(error,"설정 확인 실패 · "+error+"\n키와 모델 이름, Python 실행 경로를 확인하세요.")
		return
	model_input.text = payload.get("model","gpt-5.4-mini")
	status_label.text = "키 저장됨 · 브리핑을 요청하면 연결을 확인합니다." if payload.get("configured",false) else "아직 API 키가 없습니다. 키를 입력하고 저장하세요."
	if action == "configure":
		configuration_changed.emit()

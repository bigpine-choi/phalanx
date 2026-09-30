extends PanelContainer
signal append_to_order(field: String, text: String)
signal evidence_requested(kind: String)
const T = preload("res://scripts/terminal_theme.gd")
const Worker = preload("res://scripts/advisor_process.gd")
const Settings = preload("res://scripts/advisor_settings.gd")
const ERRORS := {"KEY_MISSING":"OpenAI 키를 설정하면 참모 해석을 받을 수 있습니다. 아래는 Python 계산 결과입니다.","OFFLINE":"오프라인 검수 중 · AI 호출 없이 계산 결과만 표시합니다.","AUTH_FAILED":"OpenAI 인증 실패 · 키 또는 모델 권한을 확인하세요.","LIMIT_REACHED":"API 한도 또는 결제 상태를 확인하고 다시 요청하세요.","TIMEOUT":"응답 시간이 초과됐습니다. 계산 결과는 유지됩니다.","NETWORK_FAILED":"OpenAI 연결 실패 · 네트워크를 확인하세요.","CITATION_INVALID":"근거를 확인할 수 없는 AI 응답을 제외했습니다. 다시 요청하세요.","RESPONSE_INVALID":"AI 응답 형식을 확인하지 못했습니다. 다시 요청하세요.","PYTHON_UNAVAILABLE":"Python 연결 경로를 확인해주세요. 기존 Phalanx 실행 환경이 필요합니다.","REQUEST_FAILED":"입력 자료를 확인하지 못했습니다. 종목 자료를 갱신하고 다시 요청하세요."}
var worker: Node
var settings: AcceptDialog
var context: Dictionary = {}
var report: Dictionary = {}
var status_label: Label
var report_box: VBoxContainer
var scroll: ScrollContainer
var buttons: Array[Button] = []
var cancel_button: Button
var heading: Label
var mode := "brief"
var _signature := ""
var _request_signature := ""
var busy := false
var _appear: Tween

func _ready() -> void:
	add_theme_stylebox_override("panel",T.panel_style(14))
	custom_minimum_size.y = 620
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation",10)
	add_child(column)
	var row := HBoxContainer.new()
	column.add_child(row)
	heading = _label("Φ  전략 참모",20,T.GOLD)
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(heading)
	var setup := _button("연결 설정",func() -> void: settings.open_settings())
	row.add_child(setup)
	column.add_child(_label("ADVISOR  /  근거를 읽고, 판단을 검토하다",10,T.MUTED))
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation",4)
	column.add_child(actions)
	for entry: Array in [["핵심 브리핑","brief"],["가설 반박","counter"],["작전 검토","review"]]:
		var button := _button(entry[0],request_report.bind(entry[1],true))
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		actions.add_child(button)
		buttons.append(button)
	var tools_row := HBoxContainer.new()
	column.add_child(tools_row)
	var facts_button := _button("지표만 계산",request_report.bind("brief",false))
	tools_row.add_child(facts_button)
	buttons.append(facts_button)
	cancel_button = _button("요청 취소",_cancel)
	tools_row.add_child(cancel_button)
	cancel_button.hide()
	status_label = _label("종목을 고르고 브리핑을 요청하세요.\n수치 계산은 기존 Phalanx Python 엔진을 사용합니다.",12,T.MUTED)
	column.add_child(status_label)
	scroll = ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.follow_focus = true
	column.add_child(scroll)
	report_box = VBoxContainer.new()
	report_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	report_box.add_theme_constant_override("separation",10)
	scroll.add_child(report_box)
	column.add_child(_label("요청 시 선택 자료·노트와 검토 대상 모의 계획을 OpenAI에 전송합니다. API 사용료가 발생할 수 있습니다.",10,T.MUTED))
	worker = Worker.new()
	add_child(worker)
	worker.completed.connect(_completed)
	settings = Settings.new()
	add_child(settings)
	settings.configuration_changed.connect(func() -> void: status_label.text = "연결 설정 저장됨 · 브리핑을 요청하세요.")

func _label(text: String, font_size := 12, color := T.TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	return label

func _button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.add_theme_font_size_override("font_size",11)
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.pressed.connect(action)
	return button

func set_context(value: Dictionary) -> void:
	var signature := JSON.stringify(value).sha256_text()
	if signature == _signature:
		return
	_signature = signature
	context = value.duplicate(true)
	worker.cancel()
	_set_busy(false)
	report = {}
	_clear()
	heading.text = "Φ  "+str(value.get("name","전략"))+" 참모"
	var conflict: String = str(value.get("identity_conflict",""))
	status_label.text = "같은 코드의 계좌 종목명("+conflict+")과 카탈로그 종목명이 다릅니다. 종목 식별자를 확인한 뒤 참모를 요청하세요." if not conflict.is_empty() else "현재 자료로 브리핑을 요청하세요.\n자료·노트·계획을 바꾸면 이전 답변은 초기화됩니다."
	if not conflict.is_empty():
		for button: Button in buttons:
			button.disabled = true

func request_report(value: String, use_ai := true) -> void:
	if context.is_empty() or busy:
		return
	if not str(context.get("identity_conflict","")).is_empty():
		status_label.text = "종목 식별자가 충돌해 참모 요청을 시작하지 않았습니다. 계좌와 카탈로그의 종목명을 확인해주세요."
		return
	if context.get("note","").length()>8000:
		status_label.text = "노트가 8,000자를 넘습니다. 분석할 가설을 줄여주세요. 원본 노트는 유지됩니다."
		return
	if value == "counter" and context.get("note","").strip_edges().is_empty():
		status_label.text = "아래 리서치 노트에 투자 가설을 먼저 적어주세요."
		return
	mode = value
	_request_signature = _signature
	report = {}
	_clear()
	_set_busy(true)
	status_label.text = "근거를 정리하고 참모 의견을 작성 중…" if use_ai else "Python에서 지표를 계산 중…"
	var request := context.duplicate(true)
	request.mode = mode
	worker.request("analyze" if use_ai else "facts",request)

func _set_busy(value: bool) -> void:
	busy = value
	for button: Button in buttons:
		button.disabled = value
	cancel_button.visible = value

func _cancel() -> void:
	worker.cancel()
	_set_busy(false)
	status_label.text = "요청을 취소했습니다. 이미 전송된 요청의 비용은 발생할 수 있습니다."

func _clear() -> void:
	if is_instance_valid(_appear):
		_appear.kill()
	for child: Node in report_box.get_children():
		report_box.remove_child(child)
		child.queue_free()
	scroll.scroll_vertical = 0

func _completed(_action: String, payload: Dictionary, error: String) -> void:
	if _request_signature != _signature:
		return
	_set_busy(false)
	if not error.is_empty():
		status_label.text = ERRORS.get(error,"참모 연결을 완료하지 못했습니다. 다시 요청하세요. ("+error+")")
		return
	if payload.get("code") != context.get("code") or payload.get("mode") != mode or not payload.get("facts") is Array or not payload.get("sources") is Array or not payload.get("analysis") is Array:
		status_label.text = "다른 종목 또는 형식이 잘못된 답변은 표시하지 않습니다."
		return
	report = payload.duplicate(true)
	_render()

func _render() -> void:
	_clear()
	var ai_state: String = report.get("ai_state","")
	status_label.text = "OpenAI · "+str(report.get("model",""))+" · 요청 시점의 근거" if ai_state=="ready" else ("Python 계산 완료 · AI 해석을 요청하지 않았습니다." if ai_state=="not_requested" else ERRORS.get(ai_state,"AI 해석을 받지 못했습니다. 계산 결과만 표시합니다. ("+ai_state+")"))
	if not report.analysis.is_empty():
		report_box.add_child(_label("참모의 해석  /  검토할 의견",14,T.GOLD))
		for item: Dictionary in report.analysis:
			_card(item,true)
	report_box.add_child(_label("확인된 수치  /  Python 계산",14,T.ACCENT))
	for item: Dictionary in report.facts:
		_card(item,false)
	report_box.add_child(_label("자료 부족 · 해석의 범위",14,T.GOLD))
	for text: String in report.missing:
		report_box.add_child(_label("• "+text,11,T.MUTED))
	report_box.modulate.a = 0.0
	_appear = create_tween()
	_appear.tween_property(report_box,"modulate:a",1.0,0.28)

func _card(item: Dictionary, ai: bool) -> void:
	var card := PanelContainer.new()
	card.add_theme_stylebox_override("panel",T.style(T.INSET,T.BORDER,2,10))
	report_box.add_child(card)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation",7)
	card.add_child(box)
	box.add_child(_label(str(item.title),13,T.GOLD if ai else T.TEXT))
	box.add_child(_label(str(item.text),12))
	var refs := HFlowContainer.new()
	box.add_child(refs)
	for identifier: String in item.source_ids:
		var source := _source(identifier)
		if source.is_empty():
			continue
		refs.add_child(_button("근거 · "+source.label,func() -> void: _show_source(source,box)))
	var add := _button("명령서 위험에 추가" if mode=="counter" else "명령서 근거에 추가",func() -> void: _append(item,ai))
	box.add_child(add)

func _source(identifier: String) -> Dictionary:
	for source: Dictionary in report.get("sources",[]):
		if source.id == identifier:
			return source
	return {}

func _show_source(source: Dictionary, parent: VBoxContainer) -> void:
	var existing := parent.get_node_or_null("Evidence")
	if existing != null:
		parent.remove_child(existing)
		existing.queue_free()
	var detail := VBoxContainer.new()
	detail.name = "Evidence"
	parent.add_child(detail)
	detail.add_child(_label(source.label+" · "+source.as_of+"\n"+source.detail,11,T.MUTED))
	if source.kind in ["quote","financial","note"]:
		detail.add_child(_button("해당 자료로 이동",func() -> void: evidence_requested.emit(source.kind)))
	var url: String = source.get("url","")
	if url.begins_with("https://images.samsung.com/") or url.begins_with("https://dart.fss.or.kr/") or url.begins_with("https://github.com/koreainvestment/"):
		detail.add_child(_button("원문 / 출처 열기 ↗",func() -> void: OS.shell_open(url)))

func _append(item: Dictionary, ai: bool) -> void:
	if _request_signature != _signature or report.is_empty():
		return
	var text := "["+str(report.name)+" · "+("AI 해석" if ai else "계산 근거")+"] "+str(item.title)+"\n"+str(item.text)
	for identifier: String in item.source_ids:
		var source := _source(identifier)
		if not source.is_empty():
			text += "\n출처: "+source.label+" ("+source.as_of+")"
	append_to_order.emit("risk" if mode=="counter" else "rationale",text)

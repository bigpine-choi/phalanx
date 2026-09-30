extends VBoxContainer
signal account_state_changed
signal resume_requested
signal order_requested(plan: Dictionary, evidence: String)
const T = preload("res://scripts/terminal_theme.gd")
const Data = preload("res://scripts/market_data.gd")
const Worker = preload("res://scripts/portfolio_process.gd")
const ERRORS := {"OFFLINE":"오프라인 · 계좌 조회를 실행하지 않았습니다.","ACCOUNT_CONFIG":"기존 KIS 계좌 연결 설정을 확인해주세요.","ACCOUNT_AUTH":"KIS 인증에 실패했습니다. 기존 계좌 설정을 확인해주세요.","ACCOUNT_QUERY_FAILED":"계좌 또는 보유종목 시세 조회를 완료하지 못했습니다. 다시 조회해주세요.","OVER_ALLOCATED":"목표 비중 합계가 100%를 넘습니다.","SELLABLE_EXCEEDED":"매도가능수량을 초과하는 계획입니다. 목표 비중을 높여주세요.","QUANTITY_INVALID":"정수주로 계획할 수 없는 잔고입니다.","NO_HOLDINGS":"계획할 보유종목이 없습니다.","KEY_MISSING":"리서치의 연결 설정에서 OpenAI 키를 저장해주세요.","LIMIT_REACHED":"OpenAI 사용 한도 또는 결제 상태를 확인해주세요.","AUTH_FAILED":"OpenAI 인증을 확인해주세요.","TIMEOUT":"조회 시간이 초과됐습니다. 다시 시도해주세요."}
var account: Dictionary = {}
var result: Dictionary = {}
var targets: Dictionary = {}
var worker: Node
var busy := false
var stale := false
var keep_holdings := false
var _request_signature := ""
var _updating := false
var _appeared: Tween
var rows: Array[Dictionary] = []
var refresh_button: Button
var calculate_button: Button
var review_button: Button
var order_button: Button
var current_button: Button
var equal_button: Button
var cancel_button: Button
var budget_input: SpinBox
var metadata: Label
var status_label: Label
var summary_grid: GridContainer
var summary_labels: Array[Label] = []
var holdings: VBoxContainer
var holdings_scroll: ScrollContainer
var split: BoxContainer
var report_box: VBoxContainer
var allocation_label: Label
var before_bar: AllocationBar
var after_bar: AllocationBar

class AllocationBar extends Control:
	var weights: Array = []
	var palette := [Color("afc19a"),Color("d4ad65"),Color("ab8260"),Color("aab9c6"),Color("d9b7a2"),Color("767e61")]
	func _ready() -> void:
		custom_minimum_size.y = 12
		mouse_filter = Control.MOUSE_FILTER_IGNORE
	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO,size),Color("3a3329"))
		var x := 0.0
		for i: int in weights.size():
			var width := size.x*clampf(float(weights[i])/100.0,0,1)
			draw_rect(Rect2(x,0,maxf(0,width-1),size.y),palette[i%palette.size()])
			x += width

func _label(text: String, font_size := 14, color := T.TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label

func _button(text: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size.y = 38
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.pressed.connect(callback)
	return button

func _panel(parent: Node) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel",T.panel_style(16))
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation",10)
	panel.add_child(box)
	return box

func _ready() -> void:
	add_theme_constant_override("separation",12)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var header := HBoxContainer.new()
	add_child(header)
	var heading := VBoxContainer.new()
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(heading)
	heading.add_child(_label("PORTFOLIO  /  DEPLOYMENT",10,T.GOLD))
	heading.add_child(_label("계좌 현황 · 작전 시뮬레이터",26,T.TEXT))
	refresh_button = _button("계좌 새로고침",refresh_account)
	header.add_child(refresh_button)
	header.add_child(_button("작성 중 명령서",func() -> void: resume_requested.emit()))
	metadata = _label("한국투자증권 · 조회 전용 · 계좌를 조회하면 보유종목 전체를 표시합니다.",12,T.MUTED)
	add_child(metadata)
	summary_grid = GridContainer.new()
	summary_grid.columns = 4
	summary_grid.add_theme_constant_override("h_separation",12)
	add_child(summary_grid)
	for caption: String in ["증권사 순자산","예수금 · 주문가능금액 아님","증권사 주식평가액","증권사 평가손익"]:
		var card := _panel(summary_grid)
		card.add_child(_label(caption,12,T.MUTED))
		var value := _label("—",22,T.GOLD)
		card.add_child(value)
		summary_labels.append(value)
	var controls := _panel(self)
	var budget_row := HBoxContainer.new()
	controls.add_child(budget_row)
	budget_row.add_child(_label("시뮬레이션 투입 현금 (가정)",14,T.GOLD))
	budget_input = SpinBox.new()
	budget_input.min_value = 0
	budget_input.max_value = 100000000000
	budget_input.step = 1
	budget_input.suffix = "원"
	budget_input.custom_minimum_size.x = 190
	budget_input.value_changed.connect(func(_value: float) -> void: _invalidate())
	budget_row.add_child(budget_input)
	controls.add_child(_label("조회 주식 평가액 + 위 가정 현금으로 계산합니다. 예수금을 자동으로 매수가능금액으로 사용하지 않습니다.",12,T.MUTED))
	var actions := HFlowContainer.new()
	actions.add_theme_constant_override("h_separation",8)
	controls.add_child(actions)
	current_button = _button("현재 비중",_current_weights)
	equal_button = _button("동일 비중",_equal_weights)
	calculate_button = _button("변경안 계산",calculate)
	review_button = _button("참모 검토 · 종목/비중 전송",review)
	order_button = _button("명령서에 적용 →",apply_order)
	order_button.add_theme_stylebox_override("normal",T.style(T.SELECTED,T.GOLD,2,10))
	cancel_button = _button("요청 취소",_cancel)
	for button: Button in [current_button,equal_button,calculate_button,review_button,order_button,cancel_button]: actions.add_child(button)
	allocation_label = _label("목표 비중을 설정하세요. 남는 비중은 계획 현금입니다.",13,T.GOLD)
	controls.add_child(allocation_label)
	status_label = _label("계좌 새로고침으로 시작하세요.",13,T.MUTED)
	controls.add_child(status_label)
	split = BoxContainer.new()
	split.add_theme_constant_override("separation",12)
	add_child(split)
	var table := _panel(split)
	table.add_child(_label("Ⅰ  보유 종목 · 배치 변경",18,T.GOLD))
	table.add_child(_label("현재·계획 비중의 분모: 조회 주식 평가액 + 가정 현금. 조회 시각의 가격으로 고정합니다.",11,T.MUTED))
	holdings_scroll = ScrollContainer.new()
	holdings_scroll.custom_minimum_size.y = 380
	holdings_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	table.add_child(holdings_scroll)
	holdings = VBoxContainer.new()
	holdings.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	holdings.add_theme_constant_override("separation",8)
	holdings_scroll.add_child(holdings)
	report_box = _panel(split)
	report_box.get_parent().custom_minimum_size.x = 290
	report_box.get_parent().size_flags_horizontal = Control.SIZE_FILL
	report_box.add_child(_label("Ⅱ  변경 전후 · 참모 검토",18,T.GOLD))
	report_box.add_child(_label("계산 후 매수·매도 금액과 남는 현금을 비교합니다.",13,T.MUTED))
	worker = Worker.new()
	add_child(worker)
	worker.completed.connect(_completed)
	resized.connect(_fit)
	_fit()
	_buttons()

func activate() -> void:
	if account.is_empty() and not busy and OS.get_environment("PHALANX_ACCOUNT_OFFLINE")!="1": refresh_account()

func _fit() -> void:
	summary_grid.columns = 2 if size.x<1000 else 4
	split.vertical = size.x<1200
	report_box.get_parent().size_flags_horizontal = Control.SIZE_EXPAND_FILL if split.vertical else Control.SIZE_FILL
	report_box.get_parent().custom_minimum_size.x = 0 if split.vertical else 290

func _context() -> Dictionary:
	return {"account":account,"targets":targets,"cash_assumption":str(budget_input.value),"keep_holdings":keep_holdings}

func _signature() -> String:
	return JSON.stringify(_context()).sha256_text()

func refresh_account() -> void:
	if busy: return
	stale = not account.is_empty()
	_invalidate()
	busy = true
	status_label.text = "계좌 잔고와 보유종목 가격을 조회 중…"
	_buttons()
	worker.request("account")

func set_account(value: Dictionary) -> void:
	account = value.duplicate(true)
	stale = false
	targets.clear()
	_build_rows()
	_current_weights()
	var summary: Dictionary = account.summary
	for i: int in 4:
		summary_labels[i].text = Data.money(float(summary[["net_assets","deposit_total","securities_evaluation_amount","profit_loss_total"][i]]))+" 원"
	metadata.text = "한국투자증권  %s  ·  %d종목  ·  조회 %s  ·  주문가능현금 미제공" % [account.account_masked,account.rows.size(),_time(account.observed_at)]
	status_label.text = "잔고 조회 완료 · 목표 비중을 바꾸고 변경안을 계산하세요." if not account.rows.is_empty() else "조회 완료 · 보유종목이 없습니다."
	if not account.get("warnings",[]).is_empty(): status_label.text += " · 조회 중 계좌 요약 변동 확인 필요"
	_buttons()

func _time(value: String) -> String:
	var unix := Time.get_unix_time_from_datetime_string(value.left(19))
	return Time.get_datetime_string_from_unix_time(unix+9*3600).replace("T"," ")+" KST"

func _build_rows() -> void:
	for child: Node in holdings.get_children():
		holdings.remove_child(child)
		child.queue_free()
	rows.clear()
	for item: Dictionary in account.rows:
		var panel := PanelContainer.new()
		panel.add_theme_stylebox_override("panel",T.style(T.INSET,T.BORDER,2,10))
		holdings.add_child(panel)
		var box := VBoxContainer.new()
		panel.add_child(box)
		var heading := HBoxContainer.new()
		box.add_child(heading)
		heading.add_child(_label(item.name+"  ·  "+item.code,14,T.TEXT))
		var input := SpinBox.new()
		input.min_value = 0
		input.max_value = 100
		input.step = 0.01
		input.suffix = "%"
		input.custom_minimum_size.x = 100
		input.value_changed.connect(func(value: float) -> void:
			if not _updating:
				targets[item.code] = snappedf(value,0.01)
				_invalidate())
		heading.add_child(input)
		box.add_child(_label("%s주  ·  조회가 %s원  ·  평가액 %s원" % [item.quantity,Data.money(float(item.price)),Data.money(float(item.value))],12,T.MUTED))
		var detail := _label("",12,T.ACCENT)
		box.add_child(detail)
		rows.append({"input":input,"detail":detail,"code":item.code})

func _current_weights() -> void:
	if account.is_empty(): return
	var base := float(account.positions_value)+budget_input.value
	_updating = true
	for i: int in rows.size():
		# Floor to 0.01% so display rounding cannot create a total over 100%.
		var value := floorf(float(account.rows[i].value)/base*10000.0)/100.0 if base>0 else 0.0
		targets[rows[i].code] = value
		rows[i].input.value = value
	_updating = false
	_invalidate()
	keep_holdings = true
	allocation_label.text = "현재 보유량 유지 · 비중은 0.01%% 단위 표시 · 현금 가정 %s원" % Data.money(budget_input.value)

func _equal_weights() -> void:
	if rows.is_empty(): return
	_updating = true
	var each := floorf(10000.0/rows.size())/100.0
	for row: Dictionary in rows:
		targets[row.code] = each
		row.input.value = each
	_updating = false
	_invalidate()

func _invalidate() -> void:
	if _updating: return
	keep_holdings = false
	if is_instance_valid(worker): worker.cancel()
	busy = false
	result = {}
	_clear_report()
	var total := 0.0
	for value: Variant in targets.values(): total += float(value)
	allocation_label.text = "목표 주식 %.2f%%  ·  목표 현금 %.2f%%" % [total,maxf(0,100-total)]
	allocation_label.add_theme_color_override("font_color",T.RED if total>100.00001 else T.GOLD)
	for i: int in rows.size():
		var base := float(account.positions_value)+budget_input.value
		var current := float(account.rows[i].value)/base*100 if base>0 else 0.0
		rows[i].detail.text = "현재 %.2f%%  ·  목표 %.2f%%  ·  증권사 손익 %s원" % [current,float(targets.get(rows[i].code,0)),Data.money(float(account.rows[i].profit_loss))]
	if is_instance_valid(status_label): status_label.text = "변경안을 계산하면 거래 수량과 계획 비중을 확인할 수 있습니다."
	_buttons()

func _buttons() -> void:
	account_state_changed.emit()
	if not is_instance_valid(refresh_button): return
	var usable := not account.is_empty() and not rows.is_empty() and not stale
	refresh_button.disabled = busy
	calculate_button.disabled = busy or not usable
	review_button.disabled = busy or result.is_empty() or not usable
	order_button.disabled = busy or result.is_empty() or not usable
	current_button.disabled = busy or not usable
	equal_button.disabled = busy or not usable
	cancel_button.visible = busy

func calculate() -> void:
	_request("simulate")

func review() -> void:
	_request("portfolio_review")

func _request(action: String) -> void:
	if busy or account.is_empty() or stale: return
	busy = true
	_request_signature = _signature()
	status_label.text = "Python에서 정수주 변경안을 계산 중…" if action=="simulate" else "종목명·코드·비중 변화로 참모 검토 중… (금액·수량·계좌번호 제외)"
	_buttons()
	worker.request(action,_context())

func _completed(action: String, payload: Dictionary, error: String) -> void:
	busy = false
	if action!="account" and _request_signature!=_signature():
		_buttons()
		return
	if not error.is_empty():
		status_label.text = ERRORS.get(error,"계산을 완료하지 못했습니다. 입력과 연결 상태를 확인해주세요. ("+error+")")
		if action=="account" and not account.is_empty(): status_label.text += " 이전 잔고를 표시합니다. 재조회 전까지 새 계획은 막습니다."
		_buttons()
		return
	if action=="account":
		if payload.get("source")!="kis_account" or not payload.get("rows") is Array or not payload.get("summary") is Dictionary:
			status_label.text = "계좌 응답 형식을 확인하지 못했습니다."
			_buttons()
			return
		set_account(payload)
	else:
		if not payload.get("plan") is Dictionary or payload.plan.get("snapshot_id")!=account.get("snapshot_id"):
			status_label.text = "다른 조회 시점의 계산 결과를 제외했습니다."
			_buttons()
			return
		result = payload
		_render_result()
		status_label.text = "Python 계산 완료 · 명령서에 적용할 수 있습니다."
		if action=="portfolio_review":
			status_label.text = "OpenAI · "+str(result.get("model",""))+" · 배분 검토 완료" if result.ai_state=="ready" else ERRORS.get(result.ai_state,"참모 답변을 받지 못했습니다. 계산 결과는 유지됩니다. ("+str(result.ai_state)+")")
	_buttons()

func _clear_report() -> void:
	if not is_instance_valid(report_box): return
	if is_instance_valid(_appeared): _appeared.kill()
	for child: Node in report_box.get_children():
		report_box.remove_child(child)
		child.queue_free()
	report_box.add_child(_label("Ⅱ  변경 전후 · 참모 검토",18,T.GOLD))
	if result.is_empty(): report_box.add_child(_label("변경안 계산 후 비교 결과를 표시합니다.",13,T.MUTED))

func _render_result() -> void:
	_clear_report()
	var plan: Dictionary = result.plan
	for i: int in rows.size():
		var item: Dictionary = plan.rows[i]
		var action := "유지" if item.delta==0 else ("매수" if item.delta>0 else "매도")
		rows[i].detail.text = "%.2f%% → %.2f%%  ·  %s %d주  ·  %s원" % [item.before_weight,item.after_weight,action,absi(item.delta),Data.money(item.amount)]
	report_box.add_child(_label("현재 배분",12,T.MUTED))
	before_bar = AllocationBar.new()
	before_bar.weights = plan.rows.map(func(row: Dictionary) -> float: return row.before_weight)
	report_box.add_child(before_bar)
	report_box.add_child(_label("변경 후 배분  ·  회색은 현금",12,T.MUTED))
	after_bar = AllocationBar.new()
	after_bar.weights = plan.rows.map(func(row: Dictionary) -> float: return row.after_weight)
	report_box.add_child(after_bar)
	for text: String in ["계획 후 현금  %s원" % Data.money(plan.planned_cash),"매수 %s원 / 매도 %s원" % [Data.money(result.buy_total),Data.money(result.sell_total)],"최대 종목 %.2f%% → %.2f%%" % [result.largest_before,result.largest_after]]:
		report_box.add_child(_label(text,14,T.GOLD))
	for warning: String in result.warnings: report_box.add_child(_label("· "+warning,12,T.MUTED))
	for item: Dictionary in result.get("analysis",[]):
		var card := _panel(report_box)
		card.add_child(_label(item.title,14,T.GOLD))
		card.add_child(_label(item.text,13))
		card.add_child(_label("근거 · 이번 변경안의 종목별 비중과 현금 가정",11,T.MUTED))
	report_box.modulate.a = 0
	_appeared = create_tween()
	_appeared.tween_property(report_box,"modulate:a",1.0,0.3)

func apply_order() -> void:
	if busy or stale or result.is_empty() or _request_signature!=_signature(): return
	var evidence := "[작전 시뮬레이터] 조회 %s\n투입 현금 가정 %s원 · 계획 후 현금 %s원\n매수 %s원 · 매도 %s원\n조회 가격 고정 · 수수료·세금 제외 · 실제 주문 미연결" % [_time(account.observed_at),Data.money(result.plan.base_cash),Data.money(result.plan.planned_cash),Data.money(result.buy_total),Data.money(result.sell_total)]
	for item: Dictionary in result.get("analysis",[]): evidence += "\n[참모] "+item.title+" · "+item.text
	order_requested.emit(result.plan.duplicate(true),evidence)

func _cancel() -> void:
	worker.cancel()
	busy = false
	status_label.text = "요청을 취소했습니다. 전송된 AI 요청에는 비용이 발생할 수 있습니다."
	_buttons()

func focus_position(code: String) -> bool:
	for row: Dictionary in rows:
		if row.code==code:
			var outer := get_parent()
			if outer is ScrollContainer: outer.ensure_control_visible(holdings_scroll)
			holdings_scroll.ensure_control_visible(row.input)
			row.input.get_line_edit().grab_focus()
			row.input.get_line_edit().select_all()
			return true
	return false

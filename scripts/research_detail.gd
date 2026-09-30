extends VBoxContainer
signal context_changed
## Research and advisor content shares public observations with the market workspace.
const T = preload("res://scripts/terminal_theme.gd")
const CommandPanel = preload("res://scripts/command_panel.gd")
const Data = preload("res://scripts/market_data.gd")
const Model = preload("res://scripts/research_model.gd")
const Gateway = preload("res://scripts/research_gateway.gd")
const NhProcess = preload("res://scripts/nhplug_quote_process.gd")
const NhModel = preload("res://scripts/nhplug_quote_model.gd")
const Chart = preload("res://scripts/price_chart.gd")
const Trend = preload("res://scripts/financial_trend.gd")
const Advisor = preload("res://scripts/advisor_panel.gd")
var advisor: PanelContainer
var right_column: VBoxContainer
var finance_panel: PanelContainer
var gateway: Node
var nh_process: Node
var title_label: Label
var price_label: Label
var change_label: Label
var status_label: Label
var source_label: Label
var nh_status: Label
var nh_button: Button
var finance_status: Label
var finance_heading: Label
var metrics: Array[Label] = []
var values_table: GridContainer
var source_links: VBoxContainer
var chart: Control
var trend: Control
var note_editor: TextEdit
var note_status: Label
var refresh_button: Button
var main_columns: BoxContainer
var notes_panel: PanelContainer
var period_buttons: Array[Button] = []
var mode_buttons: Array[Button] = []
var current_code := ""
var current_quote: Dictionary = {}
var current_financials: Dictionary = {}
var nh_generation := 0

func _ready() -> void:
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation",12)
	gateway = Gateway.new()
	add_child(gateway)
	gateway.changed.connect(_render)
	gateway.changed.connect(func() -> void: context_changed.emit())
	nh_process = NhProcess.new()
	nh_process.directory = ProjectSettings.globalize_path("user://research_cache")
	add_child(nh_process)
	nh_process.completed.connect(_nh_completed)
	_build()
	resized.connect(_responsive)
	_responsive.call_deferred()

func _label(text: String, font_size := 13, color := T.TEXT, wrap := false) -> Label:
	var result := Label.new()
	result.text = text
	result.add_theme_font_size_override("font_size",font_size)
	result.add_theme_color_override("font_color",color)
	result.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if wrap:
		result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return result

func _box(gap := 8) -> VBoxContainer:
	var result := VBoxContainer.new()
	result.add_theme_constant_override("separation",gap)
	result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return result

func _panel() -> PanelContainer:
	var result := CommandPanel.new()
	result.add_theme_stylebox_override("panel",T.panel_style(14))
	result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return result

func _button(text: String, action: Callable) -> Button:
	var result := Button.new()
	result.text = text
	result.pressed.connect(action)
	result.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	result.add_theme_font_size_override("font_size",11)
	return result

func _build() -> void:
	var heading := HBoxContainer.new()
	add_child(heading)
	title_label = _label("종목 분석",24)
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title_label)
	heading.add_child(_label("KIS RESEARCH  /  KRW",11,T.GOLD))
	nh_button = _button("NH 현재가",_fetch_nh)
	heading.add_child(nh_button)
	refresh_button = _button("새로고침",gateway.refresh)
	heading.add_child(refresh_button)
	var quote_row := HBoxContainer.new()
	quote_row.add_theme_constant_override("separation",14)
	add_child(quote_row)
	price_label = _label("—",30)
	quote_row.add_child(price_label)
	change_label = _label("일봉 자료 없음",13,T.MUTED)
	quote_row.add_child(change_label)
	status_label = _label("",11,T.MUTED,true)
	add_child(status_label)
	source_label = _label("",11,T.MUTED,true)
	add_child(source_label)
	nh_status = _label("NH투자증권 현재가는 버튼으로 별도 조회 · 키는 WSL 설정 파일에서 읽습니다.",11,T.MUTED,true)
	add_child(nh_status)
	main_columns = BoxContainer.new()
	main_columns.add_theme_constant_override("separation",12)
	add_child(main_columns)
	var left := _box(12)
	left.size_flags_stretch_ratio = 1.7
	main_columns.add_child(left)
	var price_panel := _panel()
	left.add_child(price_panel)
	var price_box := _box()
	price_panel.add_child(price_box)
	var controls := HBoxContainer.new()
	price_box.add_child(controls)
	for period: Array in [["1개월",22],["3개월",66],["1년",252]]:
		var button := _button(period[0],_set_period.bind(period[1]))
		button.tooltip_text = "최근 %d거래일 · 월/연 기간은 거래일 수로 근사" % period[1]
		button.toggle_mode = true
		button.button_pressed = period[1]==66
		controls.add_child(button)
		period_buttons.append(button)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	controls.add_child(spacer)
	for mode: Array in [["캔들","candles"],["라인","line"]]:
		var button := _button(mode[0],_set_mode.bind(mode[1]))
		button.toggle_mode = true
		button.button_pressed = mode[1]=="candles"
		controls.add_child(button)
		mode_buttons.append(button)
	chart = Chart.new()
	chart.custom_minimum_size.y = 230
	price_box.add_child(chart)
	# PriceChart sets a general minimum in _ready; research uses a taller plot.
	chart.custom_minimum_size.y = 230
	price_box.add_child(_label("황토색 20거래일 평균  ·  하단 거래량  ·  전일까지의 일봉 · 배당 포함 수익률 아님",10,T.MUTED,true))
	finance_panel = _panel()
	left.add_child(finance_panel)
	var finance := _box(9)
	finance_panel.add_child(finance)
	finance_heading = _label("연간 실적 · 연결 기준",15)
	finance.add_child(finance_heading)
	finance_status = _label("",11,T.MUTED,true)
	finance.add_child(finance_status)
	var metric_row := HBoxContainer.new()
	finance.add_child(metric_row)
	for caption: String in ["매출액","영업이익","영업현금흐름","영업이익률"]:
		var item := _box(2)
		metric_row.add_child(item)
		item.add_child(_label(caption,10,T.MUTED))
		var value := _label("자료 없음",16)
		item.add_child(value)
		metrics.append(value)
	trend = Trend.new()
	finance.add_child(trend)
	finance.add_child(_label("회색 매출액  ·  연녹색 영업이익  ·  금색 영업현금흐름  /  같은 금액 척도",10,T.MUTED,true))
	values_table = GridContainer.new()
	values_table.columns = 4
	values_table.add_theme_constant_override("h_separation",12)
	values_table.add_theme_constant_override("v_separation",7)
	finance.add_child(values_table)
	source_links = _box(3)
	finance.add_child(source_links)
	right_column = _box(12)
	right_column.size_flags_stretch_ratio = 1.0
	main_columns.add_child(right_column)
	advisor = Advisor.new()
	right_column.add_child(advisor)
	advisor.evidence_requested.connect(_show_evidence)
	notes_panel = _panel()
	right_column.add_child(notes_panel)
	var notes := _box(10)
	notes_panel.add_child(notes)
	notes.add_child(_label("나의 리서치 노트",15))
	notes.add_child(_label("투자 가설 · 반대 근거 · 다음 확인",11,T.MUTED,true))
	note_editor = TextEdit.new()
	note_editor.name = "ResearchNote"
	note_editor.placeholder_text = "실적에서 확인한 사실과 나의 판단을 구분해 기록하세요."
	note_editor.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	note_editor.custom_minimum_size.y = 250
	notes.add_child(note_editor)
	note_status = _label("",11,T.MUTED,true)
	notes.add_child(note_status)
	notes.add_child(_label("읽는 기준",13,T.GOLD))
	notes.add_child(_label("가격은 KRX 수정주가 일봉, 재무는 연간 연결 기준입니다. 서로의 기준일을 확인하세요.\n\nPER·PBR·컨센서스: 자료 없음\n분기·반기 추이: 미포함",12,T.MUTED,true))
	var source := _button("KIS 일봉 안내 열기 ↗",_open_price_source)
	notes.add_child(source)
	notes.add_child(_label("일봉 종가와 계좌 조회가는 기준 시점이 다릅니다. 배분 변경은 계좌를 조회한 시점의 가격으로 계산합니다.",11,T.MUTED,true))

func select_stock(index: int) -> void:
	select_security(Data.STOCKS[index])

func select_security(stock: Dictionary) -> void:
	nh_generation += 1
	current_code = stock.code
	title_label.text = stock.name+"  /  종목 분석"
	nh_button.disabled = not NhModel.valid_code(current_code)
	nh_status.text = "NH투자증권 현재가는 버튼으로 별도 조회 · KIS 일봉과 기준 시각이 다릅니다."
	gateway.select_stock(current_code)
	if is_visible_in_tree(): gateway.activate()

func _fetch_nh() -> void:
	if not NhModel.valid_code(current_code):
		return
	nh_generation += 1
	nh_button.disabled = true
	nh_status.text = "NH투자증권 KRX 현재가 조회 중…"
	nh_process.request(current_code,nh_generation)

func _nh_completed(code: String, token: int, envelope: Dictionary) -> void:
	if token!=nh_generation or code!=current_code:
		return
	nh_button.disabled = false
	var quote := NhModel.parse(envelope.get("payload"),code,int(Time.get_unix_time_from_system())) if envelope.get("ok")==true else {}
	if not quote.is_empty():
		var observed := Time.get_datetime_string_from_unix_time(int(quote.fetched_at)+9*3600).replace("T"," ")
		nh_status.text = "NH투자증권 KRX 현재가 %s 원 · 수신 %s KST · KIS 일봉과 별도" % [Data.money(quote.price),observed]
		return
	match envelope.get("error",""):
		"NH_SDK_MISSING":
			nh_status.text = "NH SDK가 없습니다. WSL Python에 nhplug를 설치해 주세요."
		"NH_CONFIG_MISSING":
			nh_status.text = "NH 키 설정을 확인해 주세요: WSL ~/.nhplug/.env"
		_:
			nh_status.text = "NH 현재가 조회 실패 · 설정/연결 상태를 확인해 주세요."

func activate() -> void:
	gateway.activate()

func _set_period(value: int) -> void:
	chart.set_period(value)
	for index: int in period_buttons.size():
		period_buttons[index].set_pressed_no_signal([22,66,252][index]==value)

func _set_mode(value: String) -> void:
	chart.display_mode = value
	chart.queue_redraw()
	for index: int in mode_buttons.size():
		mode_buttons[index].set_pressed_no_signal(["candles","line"][index]==value)

func _render() -> void:
	if not is_instance_valid(chart):
		return
	refresh_button.disabled = gateway.quote_state=="loading" or gateway.financial_state=="loading"
	status_label.text = gateway.quote_message
	status_label.add_theme_color_override("font_color",T.RED if gateway.quote_state in ["error","stale"] else T.MUTED)
	var quote: Dictionary = gateway.quote
	if quote.is_empty():
		price_label.text = "—"
		change_label.text = "일봉 자료 없음"
		change_label.add_theme_color_override("font_color",T.MUTED)
		source_label.text = "가격 출처: 한국투자증권 · 현재 조회한 값이 없습니다."
		chart.set_history([])
		current_quote = {}
	else:
		var candles: Array = quote.candles
		var change: float = (float(candles[-1].close)/float(candles[-2].close)-1)*100
		price_label.text = Data.money(candles[-1].close)+" 원"
		change_label.text = "%+.2f%%  이전 일봉 대비" % change
		change_label.add_theme_color_override("font_color",T.ACCENT if change>=0 else T.RED)
		var observed := Time.get_datetime_string_from_unix_time(int(quote.fetched_at)+9*3600).replace("T"," ")
		source_label.text = "%s · 일봉 %s · 수신 %s KST · %s" % [quote.source,quote.as_of,observed,quote.adjustment]
		if Time.get_unix_time_from_system()-int(quote.fetched_at)>86400:
			status_label.text += " · 하루 이상 지난 저장 자료"
		if current_quote!=quote:
			chart.set_history(candles)
			current_quote = quote
	finance_status.text = gateway.financial_message
	finance_status.add_theme_color_override("font_color",T.RED if gateway.financial_state in ["error","stale"] else T.MUTED)
	var financials: Dictionary = gateway.financials
	if financials==current_financials and not values_table.get_children().is_empty():
		return
	current_financials = financials
	for child: Node in values_table.get_children():
		values_table.remove_child(child)
		child.queue_free()
	for child: Node in source_links.get_children():
		source_links.remove_child(child)
		child.queue_free()
	if financials.is_empty():
		finance_heading.text = "연간 실적 · 자료 없음"
		for value: Label in metrics:
			value.text = "자료 없음"
		trend.set_rows([])
		return
	var rows: Array = financials.rows
	var last: Dictionary = rows[-1]
	finance_heading.text = "%d년 실적 · %s" % [last.year,financials.basis]
	for index: int in 3:
		metrics[index].text = Model.trillion(last.get(["revenue","operating_profit","operating_cash_flow"][index]))
	metrics[3].text = Model.margin(last)
	trend.set_rows(rows)
	for caption: String in ["연도","매출액","영업이익","영업현금흐름"]:
		_table_label(caption,T.MUTED)
	for row: Dictionary in rows:
		_table_label(str(row.year),T.MUTED)
		for key: String in ["revenue","operating_profit","operating_cash_flow"]:
			_table_label(Model.trillion(row.get(key)),T.TEXT)
	var seen := {}
	for row: Dictionary in rows:
		for key: String in ["source_url","cash_flow_url"]:
			var url: String = row.get(key,"")
			if url.is_empty() or seen.has(url):
				continue
			seen[url] = true
			var link := LinkButton.new()
			link.text = "%s · %d 보고서 · %s ↗" % [financials.source,row.get("source_year",row.year),"현금흐름" if key=="cash_flow_url" else "재무"]
			link.add_theme_font_size_override("font_size",10)
			link.pressed.connect(func() -> void: OS.shell_open(url))
			source_links.add_child(link)
	var date_text: String = financials.get("verified_on","")
	if financials.has("fetched_at"):
		date_text = Model.kst_date(int(financials.fetched_at))
	var unit_text := "원문 백만원 → 조원" if financials.get("mode")=="verified_snapshot" else "원문 원 → 조원"
	source_links.add_child(_label("출처 확인/수신: "+date_text+" · "+unit_text,10,T.MUTED,true))

func _table_label(text: String, color: Color) -> void:
	var label := _label(text,11,color)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	values_table.add_child(label)

func _open_price_source() -> void:
	if Data.valid_code(current_code):
		OS.shell_open(Model.KIS_SOURCE)

func _responsive() -> void:
	if main_columns==null:
		return
	main_columns.vertical = size.x<940
	right_column.custom_minimum_size.x = 0 if main_columns.vertical else 360

func _show_evidence(kind: String) -> void:
	var target: Control = chart if kind=="quote" else (finance_panel if kind=="financial" else note_editor)
	var ancestor := get_parent()
	while ancestor != null and not ancestor is ScrollContainer:
		ancestor = ancestor.get_parent()
	if ancestor is ScrollContainer:
		ancestor.ensure_control_visible(target)
	if kind=="note":
		note_editor.grab_focus()

extends Control

const Data = preload("res://scripts/demo_data.gd")
const Chart = preload("res://scripts/price_chart.gd")
const BG := Color("0c131e")
const PANEL := Color("131e2d")
const BORDER := Color("26364a")
const TEXT := Color("e5edf6")
const MUTED := Color("8fa2b9")
const ACCENT := Color("58d4b3")
const GOLD := Color("d4b678")
const RED := Color("ee8592")

@export var embedded_in_camp := false

var selected := 0
var targets: Array = []
var stock_buttons: Array[Button] = []
var period_buttons: Array[Button] = []
var body: HBoxContainer
var center: VBoxContainer
var account: PanelContainer
var chart: Control
var title_label: Label
var sector_label: Label
var price_label: Label
var change_label: Label
var holding_label: Label
var thesis_label: Label
var risk_label: Label
var score_label: Label
var weight_label: Label
var target_input: SpinBox
var weight_bar: ProgressBar
var plan_label: Label
var total_label: Label
var preview_button: Button
var empty_label: Label
var stock_list: VBoxContainer
var dialog: AcceptDialog
var updating := false
var compact := false

func _ready() -> void:
	if not embedded_in_camp:
		var ui_scale := clampf(DisplayServer.screen_get_dpi() / 96.0, 1.0, 2.0)
		get_window().content_scale_factor = ui_scale
		if not Engine.is_embedded_in_editor():
			DisplayServer.window_set_min_size(Vector2i(Vector2(900, 680) * ui_scale))
	for stock in Data.STOCKS:
		targets.append(stock.target)
	_build_theme()
	_build_ui()
	_select_stock(0)
	get_viewport().size_changed.connect(_responsive)
	_responsive.call_deferred()

func _build_theme() -> void:
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"])
	var ui_theme := Theme.new()
	ui_theme.default_font = font
	ui_theme.default_font_size = 14
	ui_theme.set_color("font_color", "Label", TEXT)
	ui_theme.set_color("font_color", "Button", TEXT)
	ui_theme.set_color("font_hover_color", "Button", Color.WHITE)
	ui_theme.set_color("font_pressed_color", "Button", ACCENT)
	ui_theme.set_stylebox("normal", "Button", _style(Color("192637"), BORDER, 7, 12))
	ui_theme.set_stylebox("hover", "Button", _style(Color("22374a"), Color("4d7184"), 7, 12))
	ui_theme.set_stylebox("pressed", "Button", _style(Color("173a39"), ACCENT, 7, 12))
	ui_theme.set_stylebox("focus", "Button", _style(Color(0, 0, 0, 0), GOLD, 7, 0))
	ui_theme.set_stylebox("disabled", "Button", _style(Color("19222e"), BORDER, 7, 12))
	ui_theme.set_stylebox("normal", "LineEdit", _style(Color("0e1724"), BORDER, 6, 10))
	ui_theme.set_stylebox("focus", "LineEdit", _style(Color(0, 0, 0, 0), ACCENT, 6, 0))
	ui_theme.set_color("font_color", "LineEdit", TEXT)
	ui_theme.set_color("font_placeholder_color", "LineEdit", MUTED)
	ui_theme.set_stylebox("background", "ProgressBar", _style(Color("283447"), Color.TRANSPARENT, 3, 0))
	ui_theme.set_stylebox("fill", "ProgressBar", _style(ACCENT, Color.TRANSPARENT, 3, 0))
	theme = ui_theme

func _style(color: Color, border: Color, radius: int, padding: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	style.content_margin_left = padding
	style.content_margin_right = padding
	style.content_margin_top = padding
	style.content_margin_bottom = padding
	return style

func _label(text: String, font_size: int = 14, color: Color = TEXT) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	return label

func _wrap(text: String, font_size: int = 14, color: Color = TEXT) -> Label:
	var label := _label(text, font_size, color)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label

func _vbox(gap: int = 12) -> VBoxContainer:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", gap)
	return box

func _hbox(gap: int = 12) -> HBoxContainer:
	var box := HBoxContainer.new()
	box.add_theme_constant_override("separation", gap)
	return box

func _panel() -> PanelContainer:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _style(PANEL, BORDER, 12, 20))
	return panel

func _expand(control: Control) -> void:
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL

func _divider(parent: Node) -> void:
	var line := HSeparator.new()
	line.add_theme_color_override("separator", BORDER)
	parent.add_child(line)

func _build_ui() -> void:
	var background := ColorRect.new()
	background.color = BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)
	var scroll := ScrollContainer.new()
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	var margin := MarginContainer.new()
	_expand(margin)
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 28)
	scroll.add_child(margin)
	var page := _vbox(22)
	_expand(page)
	margin.add_child(page)
	var header := _hbox(14)
	page.add_child(header)
	var mark := _label("Φ", 34, ACCENT)
	header.add_child(mark)
	var brand := _vbox(0)
	_expand(brand)
	header.add_child(brand)
	brand.add_child(_label("P H A L A N X", 22))
	brand.add_child(_label("투자 사령부  /  HEADQUARTERS", 11, MUTED))
	header.add_child(_label("●  가상 데이터", 13, GOLD))
	_divider(page)
	var intro := _hbox()
	page.add_child(intro)
	var heading := _vbox(6)
	_expand(heading)
	intro.add_child(heading)
	heading.add_child(_label("오늘의 투자 현황", 27))
	heading.add_child(_label("관심종목을 살펴보고, 다음 포트폴리오를 준비하세요.", 13, MUTED))
	var demo := _vbox(6)
	intro.add_child(demo)
	demo.add_child(_label("DEMO ACCOUNT  01", 12, ACCENT))
	demo.add_child(_label("실시간 시세 · 실제 계좌 미연결", 12, MUTED))
	var stats := _hbox(16)
	page.add_child(stats)
	_stat(stats, "총 평가자산", Data.money(Data.total_assets()) + " 원", "현금과 보유종목 평가액 합계", TEXT)
	_stat(stats, "보유종목 평가손익", "+" + Data.money(Data.profit()) + " 원", "평균매입가 대비  ·  예시 계좌", ACCENT)
	_stat(stats, "가용 현금", Data.money(Data.CASH) + " 원", "현금 비중  %.2f%%" % (Data.CASH / Data.total_assets() * 100), GOLD)
	body = _hbox(18)
	page.add_child(body)
	_build_watchlist()
	center = _vbox(18)
	_expand(center)
	body.add_child(center)
	_build_detail()
	_build_analysis()
	_build_account()
	var footer := _wrap("PROTOTYPE 0.1    ·    모든 가격·차트·분석 점수·계좌는 UI 검증용 가상 데이터입니다. 매매계획은 수수료·세금·체결 오차를 제외한 모의 계산입니다.", 11, MUTED)
	page.add_child(footer)
	dialog = AcceptDialog.new()
	dialog.title = "팔랑크스 · 모의 매매계획"
	dialog.ok_button_text = "닫기"
	dialog.min_size = Vector2i(660, 430)
	add_child(dialog)

func _stat(parent: Node, heading: String, value: String, caption: String, color: Color) -> void:
	var panel := _panel()
	_expand(panel)
	parent.add_child(panel)
	var box := _vbox(7)
	panel.add_child(box)
	box.add_child(_label(heading, 12, MUTED))
	box.add_child(_label(value, 24, color))
	box.add_child(_label(caption, 11, MUTED))

func _build_watchlist() -> void:
	var panel := _panel()
	panel.custom_minimum_size.x = 214
	panel.size_flags_vertical = Control.SIZE_FILL
	body.add_child(panel)
	var box := _vbox(15)
	panel.add_child(box)
	box.add_child(_label("관심종목  /  05", 16))
	var search := LineEdit.new()
	search.name = "StockSearch"
	search.placeholder_text = "종목명 · 코드 검색"
	search.custom_minimum_size.y = 38
	search.text_changed.connect(_filter_stocks)
	box.add_child(search)
	stock_list = _vbox(8)
	box.add_child(stock_list)
	for i in range(Data.STOCKS.size()):
		var stock: Dictionary = Data.STOCKS[i]
		var button := Button.new()
		button.name = "Stock_" + stock.code
		button.text = "%s\n%s    %+.2f%%" % [stock.name, Data.money(stock.price), stock.change]
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.custom_minimum_size = Vector2(172, 68)
		button.toggle_mode = true
		button.pressed.connect(_select_stock.bind(i))
		button.tooltip_text = stock.code + " · " + stock.sector
		stock_list.add_child(button)
		stock_buttons.append(button)
	empty_label = _label("검색 결과가 없습니다.", 12, MUTED)
	empty_label.visible = false
	box.add_child(empty_label)
	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(spacer)
	_divider(box)
	box.add_child(_wrap("관찰 → 분석 → 비중 검토", 12, ACCENT))
	box.add_child(_wrap("종목을 선택하면 차트와 분석, 보유 현황이 함께 바뀝니다.", 12, MUTED))

func _build_detail() -> void:
	var panel := _panel()
	center.add_child(panel)
	var box := _vbox(12)
	panel.add_child(box)
	var row := _hbox()
	box.add_child(row)
	var names := _vbox(4)
	_expand(names)
	row.add_child(names)
	sector_label = _label("", 11, MUTED)
	names.add_child(sector_label)
	title_label = _label("", 25)
	names.add_child(title_label)
	row.add_child(_label("일봉  ·  KRW", 11, MUTED))
	var quote := _hbox(16)
	box.add_child(quote)
	price_label = _label("", 31)
	quote.add_child(price_label)
	change_label = _label("", 15, ACCENT)
	quote.add_child(change_label)
	var controls := _hbox(6)
	box.add_child(controls)
	var periods := [["1개월", 22], ["3개월", 66], ["1년", 252]]
	for period in periods:
		var button := Button.new()
		button.text = period[0]
		button.toggle_mode = true
		button.button_pressed = period[1] == 66
		button.add_theme_font_size_override("font_size", 11)
		button.pressed.connect(_set_period.bind(period[1]))
		controls.add_child(button)
		period_buttons.append(button)
	var spacer := Control.new()
	_expand(spacer)
	controls.add_child(spacer)
	var average := CheckButton.new()
	average.text = "20일 평균"
	average.button_pressed = true
	average.add_theme_font_size_override("font_size", 11)
	average.toggled.connect(func(value: bool): chart.show_average = value; chart.queue_redraw())
	controls.add_child(average)
	chart = Chart.new()
	chart.name = "PriceChart"
	box.add_child(chart)
	box.add_child(_label("민트 상승  ·  분홍 하락  ·  금색 20일 평균  /  하단 거래량", 10, MUTED))

func _build_analysis() -> void:
	var panel := _panel()
	center.add_child(panel)
	var box := _vbox(9)
	panel.add_child(box)
	var header := _hbox()
	box.add_child(header)
	var label := _label("참모의 브리핑", 16)
	_expand(label)
	header.add_child(label)
	score_label = _label("", 12, GOLD)
	header.add_child(score_label)
	thesis_label = _wrap("", 13)
	box.add_child(thesis_label)
	risk_label = _wrap("", 12, MUTED)
	box.add_child(risk_label)
	box.add_child(_label("예시 분석 문구 · 실제 선정엔진 미연결", 10, MUTED))

func _build_account() -> void:
	account = _panel()
	account.custom_minimum_size.x = 285
	account.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	body.add_child(account)
	var box := _vbox(14)
	account.add_child(box)
	box.add_child(_label("포트폴리오 편성", 17))
	box.add_child(_label("선택한 종목의 보유 현황", 11, MUTED))
	holding_label = _wrap("", 13)
	box.add_child(holding_label)
	_divider(box)
	weight_label = _label("", 13)
	box.add_child(weight_label)
	weight_bar = ProgressBar.new()
	weight_bar.custom_minimum_size.y = 7
	weight_bar.show_percentage = false
	box.add_child(weight_bar)
	var target_row := _hbox()
	box.add_child(target_row)
	var target_text := _label("목표 비중", 13, MUTED)
	_expand(target_text)
	target_row.add_child(target_text)
	target_input = SpinBox.new()
	target_input.name = "TargetWeight"
	target_input.min_value = 0
	target_input.max_value = 100
	target_input.step = 0.5
	target_input.suffix = "%"
	target_input.custom_minimum_size.x = 100
	target_input.value_changed.connect(_target_changed)
	target_row.add_child(target_input)
	plan_label = _wrap("", 13, ACCENT)
	box.add_child(plan_label)
	_divider(box)
	box.add_child(_label("전체 목표 배분", 13))
	total_label = _wrap("", 12, MUTED)
	box.add_child(total_label)
	preview_button = Button.new()
	preview_button.name = "PreviewPlan"
	preview_button.text = "모의 매매계획 보기  →"
	preview_button.custom_minimum_size.y = 48
	preview_button.add_theme_stylebox_override("normal", _style(Color("1d4540"), Color("376e61"), 7, 12))
	preview_button.pressed.connect(_show_plan)
	box.add_child(preview_button)
	var reset := Button.new()
	reset.text = "목표 비중 초기화"
	reset.add_theme_font_size_override("font_size", 11)
	reset.pressed.connect(_reset_targets)
	box.add_child(reset)
	box.add_child(_wrap("1주 단위로 계산합니다.\n목표 비중은 이번 실행 동안 유지됩니다.", 11, MUTED))

func _select_stock(index: int) -> void:
	selected = index
	var stock: Dictionary = Data.STOCKS[index]
	for i in range(stock_buttons.size()):
		stock_buttons[i].set_pressed_no_signal(i == index)
	title_label.text = stock.name
	sector_label.text = stock.code + "  /  " + stock.sector
	price_label.text = Data.money(stock.price) + " 원"
	change_label.text = "%+.2f%%  전일 대비" % stock.change
	change_label.add_theme_color_override("font_color", ACCENT if stock.change >= 0 else RED)
	chart.set_stock(index)
	thesis_label.text = "관찰 포인트   " + stock.thesis
	risk_label.text = "위험 점검   " + stock.risk
	score_label.text = "예시 점수  %d / 100" % stock.score
	var pnl: float = (stock.price - stock.average) * stock.quantity
	holding_label.text = "%s  ·  %d주\n평균매입가  %s 원\n평가액  %s 원\n평가손익  %s%s 원" % [stock.name, stock.quantity, Data.money(stock.average), Data.money(stock.price * stock.quantity), "+" if pnl >= 0 else "", Data.money(pnl)]
	var weight: float = stock.price * stock.quantity / Data.total_assets() * 100
	weight_label.text = "현재 비중    %.2f%%" % weight
	weight_bar.value = weight
	updating = true
	target_input.value = targets[index]
	updating = false
	_update_plan()

func _filter_stocks(query: String) -> void:
	var visible_count := 0
	for i in range(stock_buttons.size()):
		var stock: Dictionary = Data.STOCKS[i]
		stock_buttons[i].visible = query.strip_edges().is_empty() or (stock.name + stock.code).to_lower().contains(query.strip_edges().to_lower())
		if stock_buttons[i].visible:
			visible_count += 1
	empty_label.visible = visible_count == 0

func _set_period(days: int) -> void:
	chart.set_period(days)
	var options := [22, 66, 252]
	for i in range(period_buttons.size()):
		period_buttons[i].set_pressed_no_signal(options[i] == days)

func _target_changed(value: float) -> void:
	if updating:
		return
	targets[selected] = value
	_update_plan()

func _update_plan() -> void:
	var result := Data.plan(targets)
	preview_button.disabled = not result.valid
	if not result.valid:
		plan_label.text = "목표 비중을 조정해 주세요."
		total_label.text = result.get("reason", "가용 현금이 부족합니다.")
		total_label.add_theme_color_override("font_color", RED)
		return
	var row: Dictionary = result.rows[selected]
	var action := "매수" if row.delta > 0 else "매도"
	plan_label.text = "변경할 수량이 없습니다." if row.delta == 0 else "%s %d주 예상\n약 %s 원" % [action, absi(row.delta), Data.money(row.amount)]
	total_label.text = "주식 %.1f%%  /  목표 현금 %.1f%%\n계획 후 현금  %s 원" % [result.target_total, 100.0 - result.target_total, Data.money(result.cash)]
	total_label.add_theme_color_override("font_color", MUTED)

func _reset_targets() -> void:
	for i in range(targets.size()):
		targets[i] = Data.STOCKS[i].target
	_select_stock(selected)

func _show_plan() -> void:
	var result := Data.plan(targets)
	if not result.valid:
		return
	var lines := PackedStringArray(["가상 계좌의 목표 비중을 바탕으로 계산한 모의 계획입니다.", ""])
	for row in result.rows:
		var action := "매수" if row.delta > 0 else "매도"
		lines.append("%s   |   %s %d주   |   %s 원   |   목표 %.1f%%" % [row.name, action if row.delta != 0 else "유지", absi(row.delta), Data.money(row.amount), row.target])
	lines.append("")
	lines.append("계획 후 예상 현금   %s 원" % Data.money(result.cash))
	lines.append("매도 금액을 반영한 계산 · 수수료, 세금, 체결 오차 제외")
	lines.append("실제 주문 기능은 연결되어 있지 않습니다.")
	dialog.dialog_text = "\n".join(lines)
	dialog.popup_centered(Vector2i(740, 430))

func _responsive() -> void:
	if not is_instance_valid(account):
		return
	var should_compact := get_viewport_rect().size.x < 1180
	if should_compact == compact:
		return
	compact = should_compact
	account.reparent(center if compact else body)
	account.size_flags_horizontal = Control.SIZE_EXPAND_FILL if compact else Control.SIZE_FILL

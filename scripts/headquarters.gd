extends Control
## Investment workspace: one shared selection, chart period and allocation model.
## Demo account stays synthetic; research has a separate public-data provider.
const Data = preload("res://scripts/demo_data.gd")
const Chart = preload("res://scripts/price_chart.gd")
const T = preload("res://scripts/terminal_theme.gd")
const Spark = preload("res://scripts/terminal_sparkline.gd")
const Fixtures = preload("res://scripts/terminal_fixtures.gd")
const ResearchDetail = preload("res://scripts/research_detail.gd")
const Store = preload("res://scripts/workspace_store.gd")
const Desk = preload("res://scripts/command_surface.gd")
const CommandPanel = preload("res://scripts/command_panel.gd")
const Record = preload("res://scripts/operation_record.gd")
const Order = preload("res://scripts/operation_order.gd")
const Simulator = preload("res://scripts/portfolio_simulator.gd")
var storage_path := Store.default_path()
@export var embedded_in_camp := false

var selected := 0
var targets: Array = []
var stock_buttons: Array[Button] = []
var period_buttons: Array[Button] = []
var workspace_buttons: Array[Button] = []
var workspace := "market"
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
var search: LineEdit
var market_page: Control
var portfolio_page: ScrollContainer
var live_portfolio_page: ScrollContainer
var simulator: Control
var simulation_plan: Dictionary = {}
var live_operation_draft: Dictionary = {}
var _order_is_live := false
var research_page: ScrollContainer
var portfolio_split: BoxContainer
var portfolio_rows: Array[Dictionary] = []
var research_buttons: Array[Button] = []
var research_title: Label
var research_view: Control
var note_editor: TextEdit
var note_status: Label
var notes_by_code: Dictionary = {}
var brief_panel: PanelContainer
var watch_panel: PanelContainer
var market_tiles: Array[Control] = []
var compact_plan_button: Button
var account_scroll: ScrollContainer
var market_strip: Control
var summary_strip: Control
var data_badge: Label
var status_label: Label
var chart_mode_buttons: Array[Button] = []
var profile: RefCounted
var watchlist_codes: Array = []
var watch_only := true
var favorite_button: Button
var all_stocks_button: Button
var watch_count: Label
var save_label: Label
var retry_save_button: Button
var save_timer: Timer
var profile_dirty := false
var save_failed := false
var operation_draft: Dictionary = {}
var operations: Array = []
var _recording := false

func _ready() -> void:
	if not embedded_in_camp:
		get_window().min_size = Vector2i(900,680)
	for stock: Dictionary in Data.STOCKS:
		targets.append(stock.target)
	profile = Store.new(storage_path)
	var saved: Dictionary = profile.load_profile()
	watchlist_codes = saved.watchlist
	notes_by_code = saved.notes
	operation_draft = saved.operation_draft
	live_operation_draft = saved.get("live_operation_draft",Record.empty_draft()).duplicate(true)
	simulation_plan = saved.get("simulation_plan",{}).duplicate(true)
	operations = saved.operations
	for index: int in Data.STOCKS.size():
		targets[index] = saved.targets.get(Data.STOCKS[index].code,Data.STOCKS[index].target)
	save_timer = Timer.new()
	save_timer.one_shot = true
	save_timer.wait_time = 0.5
	save_timer.timeout.connect(flush_profile)
	add_child(save_timer)
	theme = T.create()
	_build_ui()
	_select_stock(0)
	_filter_stocks("")
	_refresh_save_status()
	resized.connect(_responsive)
	_responsive.call_deferred()

func _label(text: String, font_size := 14, color := T.TEXT, mono := false) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	if mono:
		label.add_theme_font_override("font",T.font(true))
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label

func _wrap(text: String, font_size := 14, color := T.TEXT) -> Label:
	var label := _label(text,font_size,color)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label

func _vbox(gap := 10) -> VBoxContainer:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation",gap)
	return box

func _hbox(gap := 10) -> HBoxContainer:
	var box := HBoxContainer.new()
	box.add_theme_constant_override("separation",gap)
	return box

func _panel(padding := 14) -> PanelContainer:
	var panel := CommandPanel.new()
	panel.add_theme_stylebox_override("panel",T.panel_style(padding))
	return panel

func _expand(control: Control, vertical := false) -> void:
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if vertical:
		control.size_flags_vertical = Control.SIZE_EXPAND_FILL

func _button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.pressed.connect(action)
	return button

func _section(parent: Node, heading: String, caption := "") -> void:
	var row := _hbox()
	parent.add_child(row)
	var label := _label(heading,14,T.GOLD)
	_expand(label)
	row.add_child(label)
	if not caption.is_empty():
		row.add_child(_label(caption,11,T.MUTED))

func _divider(parent: Node) -> void:
	var line := ColorRect.new()
	line.color = T.BORDER
	line.custom_minimum_size.y = 1
	line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(line)

func _build_ui() -> void:
	var background := Desk.new()
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side: String in ["left","right"]:
		margin.add_theme_constant_override("margin_"+side,22)
	for side: String in ["top","bottom"]:
		margin.add_theme_constant_override("margin_"+side,16)
	add_child(margin)
	var page := _vbox(10)
	margin.add_child(page)
	_build_header(page)
	_build_markets(page)
	_build_summary(page)
	var workspace_host := Control.new()
	workspace_host.name = "WorkspacePages"
	_expand(workspace_host,true)
	page.add_child(workspace_host)
	body = _hbox(12)
	body.name = "MarketWorkspace"
	body.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	workspace_host.add_child(body)
	market_page = body
	_build_watchlist()
	center = _vbox(10)
	_expand(center,true)
	body.add_child(center)
	_build_detail()
	_build_brief()
	_build_account()
	_build_portfolio(workspace_host)
	_build_research(workspace_host)
	var status := _hbox()
	page.add_child(status)
	status_label = _label("가상 계좌  /  리서치 가격·재무는 별도 출처 표시",11,T.MUTED)
	_expand(status_label)
	status.add_child(status_label)
	status_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	save_label = _label("",11,T.MUTED)
	save_label.custom_minimum_size.x = 105
	status.add_child(save_label)
	retry_save_button = _button("저장 재시도",flush_profile)
	retry_save_button.add_theme_font_size_override("font_size",10)
	status.add_child(retry_save_button)
	status.add_child(_label("KRW   ·   실제 주문 미연결",11,T.MUTED))
	dialog = Order.new()
	add_child(dialog)
	dialog.draft_changed.connect(_operation_draft_changed)
	dialog.record_requested.connect(_record_operation)
	_select_workspace("market")

func _build_header(page: Node) -> void:
	var header := _hbox(20)
	header.custom_minimum_size.y = 62
	page.add_child(header)
	var seal := _label("Φ",42,T.GOLD)
	seal.add_theme_font_override("font",T.title_font())
	header.add_child(seal)
	var brand := _vbox(0)
	header.add_child(brand)
	brand.add_child(_label("전략 분석실",24,T.TEXT))
	brand.add_child(_label("P H A L A N X  /  COMMAND LEDGER",9,T.GOLD,true))
	var tabs := _hbox(4)
	header.add_child(tabs)
	for item: Array in [["Ⅰ  시장","market"],["Ⅱ  포트폴리오","portfolio"],["Ⅲ  리서치","research"]]:
		var button := _button(item[0],_select_workspace.bind(item[1]))
		button.name = "Workspace_"+item[1]
		button.toggle_mode = true
		button.custom_minimum_size = Vector2(94,40)
		tabs.add_child(button)
		workspace_buttons.append(button)
	var spacer := Control.new()
	_expand(spacer)
	header.add_child(spacer)
	var badge := _panel(8)
	badge.add_theme_stylebox_override("panel",T.style(Color("30291d"),Color("57482f"),5,8))
	data_badge = _label("DEMO ACCOUNT  01",11,T.GOLD,true)
	badge.add_child(data_badge)
	header.add_child(badge)

func _build_markets(page: Node) -> void:
	var strip := _hbox(8)
	market_strip = strip
	page.add_child(strip)
	for item: Dictionary in Fixtures.MARKETS:
		var tile := _panel(10)
		_expand(tile)
		strip.add_child(tile)
		market_tiles.append(tile)
		var row := _hbox(10)
		tile.add_child(row)
		var names := _vbox(1)
		_expand(names)
		row.add_child(names)
		names.add_child(_label(item.name,10,T.MUTED,true))
		names.add_child(_label(item.value,18,T.TEXT,true))
		var trend := Spark.new()
		trend.values = PackedFloat32Array(item.trend)
		trend.line_color = T.ACCENT if item.up else T.RED
		trend.custom_minimum_size = Vector2(48,30)
		row.add_child(trend)
		row.add_child(_label(item.change,11,trend.line_color,true))
		tile.tooltip_text = "화면 구성용 가상 지수 · 실시간 시세가 아닙니다."

func _build_summary(page: Node) -> void:
	var strip := _hbox(12)
	summary_strip = strip
	strip.custom_minimum_size.y = 50
	page.add_child(strip)
	for item: Array in [["총 평가자산",Data.money(Data.total_assets()),T.TEXT],["평가손익","+"+Data.money(Data.profit()),T.ACCENT],["가용 현금",Data.money(Data.CASH),T.TEXT]]:
		var group := _vbox(0)
		_expand(group)
		strip.add_child(group)
		group.add_child(_label(item[0],11,T.MUTED))
		group.add_child(_label(item[1]+"  KRW",22,item[2],true))
	compact_plan_button = _button("샘플 비중 계획  ↗",_select_workspace.bind("sample"))
	compact_plan_button.tooltip_text = "포트폴리오에서 목표 비중을 편집합니다."
	strip.add_child(compact_plan_button)

func _build_watchlist() -> void:
	watch_panel = _panel(12)
	watch_panel.custom_minimum_size.x = 222
	body.add_child(watch_panel)
	var box := _vbox(10)
	watch_panel.add_child(box)
	var heading := _hbox(4)
	box.add_child(heading)
	var title := _label("관심종목",14,T.GOLD)
	_expand(title)
	heading.add_child(title)
	watch_count = _label("",11,T.GOLD,true)
	heading.add_child(watch_count)
	all_stocks_button = _button("전체 보기",_toggle_catalogue)
	all_stocks_button.toggle_mode = true
	all_stocks_button.add_theme_font_size_override("font_size",10)
	heading.add_child(all_stocks_button)
	search = LineEdit.new()
	search.name = "StockSearch"
	search.placeholder_text = "종목명 · 코드 검색"
	search.tooltip_text = "Ctrl+K로 전체 종목 검색 · Enter로 첫 검색 결과 선택"
	search.custom_minimum_size.y = 34
	search.add_theme_font_size_override("font_size",12)
	search.text_changed.connect(_filter_stocks)
	search.text_submitted.connect(_submit_search)
	box.add_child(search)
	var scroll := ScrollContainer.new()
	_expand(scroll,true)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	box.add_child(scroll)
	stock_list = _vbox(5)
	_expand(stock_list)
	scroll.add_child(stock_list)
	for index: int in Data.STOCKS.size():
		var stock: Dictionary = Data.STOCKS[index]
		var button := _button("",_select_stock.bind(index))
		button.name = "Stock_"+stock.code
		button.toggle_mode = true
		button.custom_minimum_size.y = 60
		button.tooltip_text = "%s · %s · %s" % [stock.name,stock.code,stock.sector]
		stock_list.add_child(button)
		stock_buttons.append(button)
		var margin := MarginContainer.new()
		margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		for side: String in ["left","right"]:
			margin.add_theme_constant_override("margin_"+side,9)
		margin.add_theme_constant_override("margin_top",6)
		margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
		button.add_child(margin)
		var row := _hbox(4)
		row.mouse_filter = Control.MOUSE_FILTER_IGNORE
		margin.add_child(row)
		var names := _vbox(4)
		names.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_expand(names)
		row.add_child(names)
		var name_label := _label(stock.name,12)
		name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		names.add_child(name_label)
		names.add_child(_label(stock.code,10,T.MUTED,true))
		var quote := _vbox(2)
		quote.mouse_filter = Control.MOUSE_FILTER_IGNORE
		row.add_child(quote)
		var price := _label(Data.money(stock.price),14,T.TEXT,true)
		price.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		quote.add_child(price)
		var change := _label("%+.2f%%" % stock.change,11,T.ACCENT if stock.change >= 0 else T.RED,true)
		change.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		quote.add_child(change)
	empty_label = _wrap("검색 결과가 없습니다.",12,T.MUTED)
	empty_label.hide()
	stock_list.add_child(empty_label)
	box.add_child(_label("샘플 시세  ·  Ctrl+K 검색",10,T.MUTED))

func _build_detail() -> void:
	var panel := _panel(16)
	_expand(panel,true)
	center.add_child(panel)
	var box := _vbox(7)
	panel.add_child(box)
	var row := _hbox()
	box.add_child(row)
	var names := _vbox(1)
	_expand(names)
	row.add_child(names)
	sector_label = _label("",10,T.MUTED)
	names.add_child(sector_label)
	title_label = _label("",22)
	names.add_child(title_label)
	favorite_button = _button("",_toggle_favorite)
	favorite_button.name = "ToggleFavorite"
	favorite_button.toggle_mode = true
	favorite_button.add_theme_font_size_override("font_size",11)
	row.add_child(favorite_button)
	row.add_child(_label("일봉  /  KRW",11,T.MUTED,true))
	var quote := _hbox(14)
	box.add_child(quote)
	price_label = _label("",30,T.TEXT,true)
	quote.add_child(price_label)
	change_label = _label("",13,T.ACCENT,true)
	quote.add_child(change_label)
	var controls := _hbox(5)
	box.add_child(controls)
	for period: Array in [["1개월",22],["3개월",66],["1년",252]]:
		var button := _button(period[0],_set_period.bind(period[1]))
		button.toggle_mode = true
		button.button_pressed = period[1] == 66
		button.add_theme_font_size_override("font_size",11)
		controls.add_child(button)
		period_buttons.append(button)
	var spacer := Control.new()
	_expand(spacer)
	controls.add_child(spacer)
	for mode: Array in [["캔들","candles"],["라인","line"]]:
		var button := _button(mode[0],_set_chart_mode.bind(mode[1]))
		button.toggle_mode = true
		button.button_pressed = mode[1] == "candles"
		button.add_theme_font_size_override("font_size",11)
		controls.add_child(button)
		chart_mode_buttons.append(button)
	chart = Chart.new()
	chart.name = "PriceChart"
	_expand(chart,true)
	box.add_child(chart)
	var legend := _hbox()
	box.add_child(legend)
	var average := CheckButton.new()
	average.text = "20일 평균"
	average.button_pressed = true
	average.add_theme_font_size_override("font_size",11)
	average.toggled.connect(func(value: bool) -> void: chart.show_average=value; chart.queue_redraw())
	legend.add_child(average)
	var legend_text := _label("녹색 상승 · 적갈색 하락  /  하단 거래량",10,T.MUTED)
	_expand(legend_text)
	legend_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	legend.add_child(legend_text)

func _build_brief() -> void:
	brief_panel = _panel(14)
	center.add_child(brief_panel)
	var box := _vbox(6)
	brief_panel.add_child(box)
	var row := _hbox()
	box.add_child(row)
	var title := _label("◆  작전 브리핑 · 예시",13,T.GOLD)
	_expand(title)
	row.add_child(title)
	score_label = _label("",11,T.GOLD)
	row.add_child(score_label)
	row.add_child(_button("실제 종목 분석 ↗",_select_workspace.bind("research")))
	thesis_label = _wrap("",12)
	box.add_child(thesis_label)
	risk_label = _wrap("",11,T.MUTED)
	box.add_child(risk_label)

func _build_account() -> void:
	account = _panel(14)
	account.name = "AllocationPlanner"
	account.custom_minimum_size.x = 254
	body.add_child(account)
	var layout := _vbox(8)
	account.add_child(layout)
	account_scroll = ScrollContainer.new()
	account_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_expand(account_scroll,true)
	layout.add_child(account_scroll)
	var box := _vbox(9)
	_expand(box)
	account_scroll.add_child(box)
	_section(box,"비중 계획","SIMULATION")
	holding_label = _wrap("",12)
	box.add_child(holding_label)
	_divider(box)
	weight_label = _label("",12,T.MUTED)
	box.add_child(weight_label)
	weight_bar = ProgressBar.new()
	weight_bar.custom_minimum_size.y = 4
	weight_bar.show_percentage = false
	box.add_child(weight_bar)
	var row := _hbox()
	box.add_child(row)
	var target := _label("목표 비중",13)
	_expand(target)
	row.add_child(target)
	target_input = SpinBox.new()
	target_input.name = "TargetWeight"
	target_input.min_value = 0
	target_input.max_value = 100
	target_input.step = 0.5
	target_input.suffix = "%"
	target_input.custom_minimum_size.x = 94
	target_input.value_changed.connect(_target_changed)
	row.add_child(target_input)
	plan_label = _wrap("",13,T.ACCENT)
	box.add_child(plan_label)
	_divider(box)
	_section(box,"전체 목표 배분")
	total_label = _wrap("",12,T.MUTED)
	box.add_child(total_label)
	preview_button = _button("작전 명령서 작성  →",_show_plan)
	preview_button.name = "PreviewPlan"
	preview_button.custom_minimum_size.y = 40
	preview_button.add_theme_stylebox_override("normal",T.style(Color("543322"),T.GOLD,2,10))
	layout.add_child(preview_button)
	var reset := _button("목표 비중 초기화",_reset_targets)
	reset.add_theme_font_size_override("font_size",11)
	layout.add_child(reset)
	layout.add_child(_wrap("1주 단위 모의 계산 · 수수료·세금 제외",10,T.MUTED))

func _scroll_page(host: Node, node_name: String) -> ScrollContainer:
	var scroll := ScrollContainer.new()
	scroll.name = node_name
	scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	host.add_child(scroll)
	return scroll

func _build_portfolio(host: Node) -> void:
	live_portfolio_page = _scroll_page(host,"LivePortfolioWorkspace")
	simulator = Simulator.new()
	live_portfolio_page.add_child(simulator)
	simulator.sample_requested.connect(_select_workspace.bind("sample"))
	simulator.order_requested.connect(_show_simulation_plan)
	simulator.resume_requested.connect(func() -> void:
		if simulation_plan.is_empty():
			simulator.status_label.text = "저장된 실계좌 기반 명령서 초안이 없습니다. 계산 후 적용해주세요."
			return
		_order_is_live = true
		dialog.open_plan(simulation_plan,live_operation_draft))
	portfolio_page = _scroll_page(host,"PortfolioWorkspace")
	portfolio_split = BoxContainer.new()
	portfolio_split.add_theme_constant_override("separation",12)
	_expand(portfolio_split)
	portfolio_page.add_child(portfolio_split)
	var panel := _panel(18)
	_expand(panel)
	portfolio_split.add_child(panel)
	var box := _vbox(16)
	panel.add_child(box)
	_section(box,"포트폴리오","DEMO ACCOUNT  01")
	box.add_child(_button("실계좌 · 작전 시뮬레이터로 돌아가기",_select_workspace.bind("portfolio")))
	box.add_child(_wrap("보유 비중과 목표 비중을 한눈에 검토하세요.",12,T.MUTED))
	var head := _hbox(8)
	box.add_child(head)
	for cell: Array in [["종목",2.1],["평가액",1.5],["평가손익",1.3],["현재",0.8],["목표",0.8]]:
		var heading := _table_cell(head,cell[0],cell[1],T.MUTED,11)
		if cell[0] == "종목":
			heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	_divider(box)
	for index: int in Data.STOCKS.size():
		var stock: Dictionary = Data.STOCKS[index]
		var row := _hbox(8)
		row.custom_minimum_size.y = 46
		box.add_child(row)
		var button := _button(stock.name,_select_stock.bind(index))
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.size_flags_stretch_ratio = 2.1
		_expand(button)
		button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		row.add_child(button)
		var pnl: float = (stock.price-stock.average)*stock.quantity
		_table_cell(row,Data.money(stock.price*stock.quantity),1.5,T.TEXT)
		_table_cell(row,("+" if pnl>=0 else "")+Data.money(pnl),1.3,T.ACCENT if pnl>=0 else T.RED)
		_table_cell(row,"%.1f%%" % (stock.price*stock.quantity/Data.total_assets()*100),0.8,T.MUTED)
		var target := _table_cell(row,"",0.8,T.GOLD)
		portfolio_rows.append({"button":button,"target":target})
	_divider(box)
	var cash := _hbox()
	box.add_child(cash)
	var cash_title := _label("현금",13,T.MUTED)
	_expand(cash_title)
	cash.add_child(cash_title)
	cash.add_child(_label(Data.money(Data.CASH)+" KRW   /   %.2f%%" % (Data.CASH/Data.total_assets()*100),14,T.GOLD,true))
	box.add_child(_wrap("종목을 누르면 비중 계획에 반영됩니다. 변경한 목표는 모의 계획에서 함께 검토할 수 있습니다.",12,T.MUTED))

func _table_cell(parent: Node, text: String, ratio: float, color: Color, font_size := 13) -> Label:
	var label := _label(text,font_size,color,true)
	_expand(label)
	label.size_flags_stretch_ratio = ratio
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	parent.add_child(label)
	return label

func _build_research(host: Node) -> void:
	research_page = _scroll_page(host,"ResearchWorkspace")
	var box := _vbox(12)
	_expand(box)
	research_page.add_child(box)
	var stocks := _hbox(6)
	box.add_child(stocks)
	for index: int in Data.STOCKS.size():
		var button := _button(Data.STOCKS[index].name,_select_stock.bind(index))
		button.toggle_mode = true
		_expand(button)
		stocks.add_child(button)
		research_buttons.append(button)
	research_view = ResearchDetail.new()
	box.add_child(research_view)
	research_title = research_view.title_label
	note_editor = research_view.note_editor
	note_status = research_view.note_status
	note_editor.text_changed.connect(_note_changed)
	research_view.context_changed.connect(_sync_advisor)
	research_view.advisor.append_to_order.connect(_append_advisor)

func _select_workspace(value: String) -> void:
	if not value in ["market","portfolio","research","sample"]:
		return
	flush_profile()
	workspace = value
	market_strip.visible = value in ["market","sample"] and size.y >= 620
	summary_strip.visible = value in ["market","sample"]
	data_badge.text = "KIS · READ ONLY" if value=="portfolio" else ("KIS · OFFICIAL IR" if value=="research" else "DEMO ACCOUNT  01")
	status_label.text = "실계좌 조회  /  배분 변경은 모의 계획" if value=="portfolio" else "가상 계좌  /  리서치 가격·재무는 별도 출처 표시"
	market_page.visible = value == "market"
	portfolio_page.visible = value == "sample"
	live_portfolio_page.visible = value == "portfolio"
	research_page.visible = value == "research"
	for index: int in workspace_buttons.size():
		workspace_buttons[index].set_pressed_no_signal(["market","portfolio","research"][index] == ("portfolio" if value=="sample" else value))
	compact_plan_button.visible = compact and workspace == "market"
	_place_account()
	if value == "research":
		research_view.activate()
	if value == "portfolio":
		simulator.activate()

func _place_account() -> void:
	if account == null or portfolio_split == null:
		return
	var desired_parent: Node = portfolio_split if workspace != "market" or compact else body
	if account.get_parent() != desired_parent:
		account.reparent(desired_parent)
	account.visible = workspace == "sample" or (workspace == "market" and not compact)
	account.custom_minimum_size.x = 0 if compact else 254
	account.custom_minimum_size.y = 450 if workspace == "sample" else 0
	account.size_flags_horizontal = Control.SIZE_EXPAND_FILL if compact else Control.SIZE_FILL
	account.size_flags_vertical = Control.SIZE_FILL

func _select_stock(index: int) -> void:
	if index < 0 or index >= Data.STOCKS.size():
		return
	flush_profile()
	selected = index
	var stock: Dictionary = Data.STOCKS[index]
	for i: int in stock_buttons.size():
		stock_buttons[i].set_pressed_no_signal(i == index)
		research_buttons[i].set_pressed_no_signal(i == index)
		portfolio_rows[i].button.add_theme_stylebox_override("normal",T.style(T.SELECTED if i==index else T.INSET,T.BORDER,2,8))
	title_label.text = stock.name
	sector_label.text = stock.code+"   /   "+stock.sector
	price_label.text = Data.money(stock.price)
	change_label.text = "%+.2f%%  전일 대비" % stock.change
	change_label.add_theme_color_override("font_color",T.ACCENT if stock.change>=0 else T.RED)
	chart.set_stock(index)
	thesis_label.text = stock.thesis
	risk_label.text = "위험 · "+stock.risk
	score_label.text = "예시 점수  %d / 100" % stock.score
	research_view.select_stock(index)
	var pnl: float = (stock.price-stock.average)*stock.quantity
	holding_label.text = "%s  ·  %d주\n\n평균매입가   %s 원\n평가액       %s 원\n평가손익     %s%s 원" % [stock.name,stock.quantity,Data.money(stock.average),Data.money(stock.price*stock.quantity),"+" if pnl>=0 else "",Data.money(pnl)]
	var weight: float = stock.price*stock.quantity/Data.total_assets()*100
	weight_label.text = "현재 비중   %.2f%%" % weight
	weight_bar.value = weight
	updating = true
	target_input.value = targets[index]
	note_editor.text = notes_by_code.get(stock.code,"")
	updating = false
	_refresh_favorite()
	_refresh_save_status()
	_update_plan()
	_sync_advisor()

func _filter_stocks(query: String) -> void:
	var count := 0
	for index: int in stock_buttons.size():
		var stock: Dictionary = Data.STOCKS[index]
		var query_text := query.strip_edges().to_lower()
		stock_buttons[index].visible = (not watch_only or stock.code in watchlist_codes) if query_text.is_empty() else (stock.name+stock.code).to_lower().contains(query_text)
		if stock_buttons[index].visible:
			count += 1
	empty_label.visible = count == 0
	empty_label.text = "관심종목이 없습니다.\n전체 보기에서 종목을 추가하세요." if query.strip_edges().is_empty() and watch_only else "검색 결과가 없습니다."
	var known_count := 0
	for stock: Dictionary in Data.STOCKS:
		if stock.code in watchlist_codes:
			known_count += 1
	watch_count.text = str(known_count)

func _submit_search(_text: String) -> void:
	for index: int in stock_buttons.size():
		if stock_buttons[index].visible:
			_select_stock(index)
			stock_buttons[index].grab_focus()
			return

func _set_period(days: int) -> void:
	chart.set_period(days)
	for index: int in period_buttons.size():
		period_buttons[index].set_pressed_no_signal([22,66,252][index] == days)

func _set_chart_mode(value: String) -> void:
	chart.display_mode = value
	chart.queue_redraw()
	for index: int in chart_mode_buttons.size():
		chart_mode_buttons[index].set_pressed_no_signal(["candles","line"][index] == value)

func _target_changed(value: float) -> void:
	if updating:
		return
	targets[selected] = value
	_update_plan()
	_queue_profile_save()
	_sync_advisor()

func _update_plan() -> void:
	for index: int in portfolio_rows.size():
		portfolio_rows[index].target.text = "%.1f%%" % targets[index]
	var result := Data.plan(targets)
	preview_button.disabled = not result.valid
	if not result.valid:
		plan_label.text = "목표 비중을 조정해 주세요."
		total_label.text = result.get("reason","가용 현금이 부족합니다.")
		total_label.add_theme_color_override("font_color",T.RED)
		return
	var row: Dictionary = result.rows[selected]
	var action := "매수" if row.delta>0 else "매도"
	plan_label.text = "변경할 수량이 없습니다." if row.delta==0 else "%s %d주 예상\n약 %s 원" % [action,absi(row.delta),Data.money(row.amount)]
	total_label.text = "주식 %.1f%%  ·  목표 현금 %.1f%%\n계획 후 현금  %s 원" % [result.target_total,100.0-result.target_total,Data.money(result.cash)]
	total_label.add_theme_color_override("font_color",T.MUTED)

func _reset_targets() -> void:
	for index: int in targets.size():
		targets[index] = Data.STOCKS[index].target
	_queue_profile_save()
	_select_stock(selected)

func _show_plan() -> void:
	_order_is_live = false
	var result := Record.snapshot(targets)
	if result.is_empty():
		return
	dialog.open_plan(result,operation_draft)

func _show_simulation_plan(plan: Dictionary, evidence: String) -> void:
	var combined: String = live_operation_draft.get("rationale","")
	if not combined.contains(evidence): combined += ("\n\n" if not combined.is_empty() else "")+evidence
	if combined.length()>Record.MAX_TEXT:
		simulator.status_label.text = "기존 초안과 합치면 2,000자를 넘습니다. 참모 검토 없이 계산안을 적용하거나 초안을 줄여주세요."
		return
	var proposed := live_operation_draft.duplicate(true)
	proposed.rationale = combined
	if not Record.validate(Record.from_snapshot(plan,{"title":"검증","rationale":"검증","risk":"검증"})):
		simulator.status_label.text = "계산안의 수량과 금액을 검증하지 못했습니다."
		return
	simulation_plan = plan.duplicate(true)
	live_operation_draft = proposed
	_order_is_live = true
	_queue_profile_save()
	flush_profile()
	dialog.open_plan(simulation_plan,live_operation_draft)

func _current_draft() -> Dictionary:
	return live_operation_draft if _order_is_live else operation_draft

func _operation_draft_changed(value: Dictionary) -> void:
	if _order_is_live: live_operation_draft = value.duplicate(true)
	else: operation_draft = value.duplicate(true)
	_queue_profile_save()
	_sync_advisor()
	if not Record.valid_draft(value):
		dialog.show_feedback("판단 근거와 위험은 각각 2,000자 이내로 작성해주세요.")
	else:
		dialog.show_feedback("작성 중인 초안을 자동 저장합니다. 봉인하면 확정 시점의 기록으로 남습니다.",false)

func _profile_extra(draft: Dictionary, entries: Array) -> Dictionary:
	var by_code: Dictionary = profile.state.targets.duplicate(true)
	for index: int in Data.STOCKS.size():
		by_code[Data.STOCKS[index].code] = targets[index]
	return {"targets":by_code,"operation_draft":draft,"operations":entries,"live_operation_draft":live_operation_draft,"simulation_plan":simulation_plan}

func _record_operation() -> void:
	if _recording or dialog.recorded:
		return
	if not Record.valid_draft(_current_draft(),true):
		dialog.show_feedback("작전 이름·판단 근거·주요 위험을 모두 작성해주세요. 근거와 위험은 각각 2,000자까지입니다.")
		return
	if operations.size() >= Record.MAX_OPERATIONS:
		dialog.show_feedback("작전 일지의 200건 한도에 도달했습니다. 기존 기록은 그대로 보존됩니다.")
		return
	var record := Record.from_snapshot(simulation_plan,live_operation_draft) if _order_is_live else Record.create(targets,operation_draft)
	if record.is_empty():
		dialog.show_feedback("목표 비중과 가용 현금을 확인한 뒤 다시 작성해주세요.")
		return
	_recording = true
	save_timer.stop()
	var proposed := operations.duplicate(true)
	proposed.append(record)
	var next_draft := Record.empty_draft()
	var extra := _profile_extra(operation_draft if _order_is_live else next_draft,proposed)
	if _order_is_live:
		extra.live_operation_draft = next_draft
		extra.simulation_plan = {}
	if profile.save_profile(watchlist_codes,notes_by_code,extra):
		operations = proposed
		if _order_is_live:
			live_operation_draft = next_draft
			simulation_plan = {}
		else: operation_draft = next_draft
		profile_dirty = false
		save_failed = false
		dialog.saved(record)
	else:
		profile_dirty = true
		save_failed = true
		dialog.show_feedback(profile.message+" 기록 완료로 처리하지 않았습니다. 같은 버튼으로 다시 시도할 수 있습니다.")
	_recording = false
	_refresh_save_status()
	_sync_advisor()

func _note_changed() -> void:
	if updating:
		return
	var code: String = Data.STOCKS[selected].code
	if note_editor.text.is_empty():
		notes_by_code.erase(code)
	else:
		notes_by_code[code] = note_editor.text
	_queue_profile_save()
	_sync_advisor()

func _sync_advisor() -> void:
	if updating or not is_instance_valid(research_view) or targets.size()!=Data.STOCKS.size():
		return
	var stock: Dictionary = Data.STOCKS[selected]
	research_view.advisor.set_context({"code":stock.code,"name":stock.name,
		"quote":research_view.gateway.quote.duplicate(true),"financials":research_view.gateway.financials.duplicate(true),
		"note":notes_by_code.get(stock.code,""),"plan":Record.snapshot(targets),"draft":operation_draft.duplicate(true)})

func _append_advisor(field: String, text: String) -> void:
	if field not in ["rationale","risk"] or text.is_empty():
		return
	var previous: String = operation_draft.get(field,"")
	if previous.contains(text):
		research_view.advisor.status_label.text = "이미 명령서 초안에 들어 있는 내용입니다."
		return
	var combined := previous+("\n\n" if not previous.is_empty() else "")+text
	if combined.length()>Record.MAX_TEXT:
		research_view.advisor.status_label.text = "명령서의 2,000자 한도를 넘습니다. 기존 초안을 줄인 뒤 추가하세요."
		return
	operation_draft[field] = combined
	_queue_profile_save()
	flush_profile()
	_sync_advisor()
	research_view.advisor.status_label.text = "초안에 추가했습니다. 저장 상태를 확인해주세요." if save_failed else "명령서 초안에 추가하고 저장했습니다."
	_show_plan()

func active_popup() -> Window:
	if research_view.advisor.settings.visible:
		return research_view.advisor.settings
	return dialog if is_instance_valid(dialog) and dialog.visible else null

func _responsive() -> void:
	market_strip.visible = workspace in ["market","sample"] and size.y >= 620
	if account == null:
		return
	compact = size.x < 1120
	watch_panel.custom_minimum_size.x = 202 if compact else 222
	portfolio_split.vertical = compact
	brief_panel.visible = size.y >= 780
	compact_plan_button.visible = compact and workspace == "market"
	# The market strip stays useful on smaller desktops without forcing overflow.
	market_tiles[3].visible = size.x >= 1060
	_place_account()

func _unhandled_key_input(event: InputEvent) -> void:
	if not is_visible_in_tree() or dialog.visible:
		return
	if event is InputEventKey and event.pressed and not event.echo and event.ctrl_pressed and event.keycode == KEY_K:
		_select_workspace("market")
		search.grab_focus()
		search.select_all()
		get_viewport().set_input_as_handled()

func _toggle_catalogue() -> void:
	watch_only = not watch_only
	all_stocks_button.set_pressed_no_signal(not watch_only)
	all_stocks_button.text = "관심만" if not watch_only else "전체 보기"
	_filter_stocks(search.text)

func _toggle_favorite() -> void:
	var code: String = Data.STOCKS[selected].code
	if code in watchlist_codes:
		watchlist_codes.erase(code)
	else:
		watchlist_codes.append(code)
	_refresh_favorite()
	_filter_stocks(search.text)
	_queue_profile_save()
	flush_profile()

func _refresh_favorite() -> void:
	var included: bool = Data.STOCKS[selected].code in watchlist_codes
	favorite_button.set_pressed_no_signal(included)
	favorite_button.text = "★ 관심" if included else "☆ 추가"
	favorite_button.tooltip_text = "관심종목에서 해제" if included else "관심종목에 추가"

func _queue_profile_save() -> void:
	profile_dirty = true
	save_failed = false
	save_timer.start()
	_refresh_save_status()

func flush_profile() -> void:
	if profile == null or not profile_dirty:
		return
	save_timer.stop()
	if profile.save_profile(watchlist_codes,notes_by_code,_profile_extra(operation_draft,operations)):
		profile_dirty = false
		save_failed = false
	else:
		save_failed = true
	_refresh_save_status()

func _refresh_save_status() -> void:
	if save_label == null or note_status == null:
		return
	var problem: bool = save_failed or profile.blocked
	save_label.text = "저장 확인 필요" if problem else ("저장 대기 중…" if profile_dirty else ("이전 저장본 복원" if not profile.message.is_empty() else "이 기기에 저장"))
	save_label.add_theme_color_override("font_color",T.RED if problem else T.MUTED)
	save_label.tooltip_text = profile.message+"\n"+profile.path
	retry_save_button.visible = save_failed and not profile.blocked
	note_status.text = profile.message if not profile.message.is_empty() else ("입력 후 자동 저장합니다…" if profile_dirty else "이 기기에 자동 저장됩니다. 앱을 다시 열어도 유지됩니다.")
	note_status.add_theme_color_override("font_color",T.RED if problem else T.MUTED)

func _exit_tree() -> void:
	flush_profile()

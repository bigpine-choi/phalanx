extends Control
## Investment workspace: one shared selection, chart period and allocation model.
## Shared KIS observations connect market, research and portfolio planning.
const Data = preload("res://scripts/market_data.gd")
const Chart = preload("res://scripts/price_chart.gd")
const T = preload("res://scripts/terminal_theme.gd")
const ResearchDetail = preload("res://scripts/research_detail.gd")
const Store = preload("res://scripts/workspace_store.gd")
const Desk = preload("res://scripts/command_surface.gd")
const CommandPanel = preload("res://scripts/command_panel.gd")
const Record = preload("res://scripts/operation_record.gd")
const Order = preload("res://scripts/operation_order.gd")
const Simulator = preload("res://scripts/portfolio_simulator.gd")
const MarketCatalog = preload("res://scripts/market_catalog.gd")
const MarketCatalogPanel = preload("res://scripts/market_catalog_panel.gd")
const WatchGroups = preload("res://scripts/watchlist_groups.gd")
const WatchTable = preload("res://scripts/watchlist_table_panel.gd")
const WatchTableData = preload("res://scripts/watchlist_table_data.gd")
var storage_path := Store.default_path()
@export var embedded_in_camp := false

var securities: Array = Data.STOCKS.duplicate(true)
var security_names: Dictionary = {}
var stock_prices: Array[Label] = []
var stock_tags: Array[Label] = []
var research_stock_row: HBoxContainer
var account_labels: Array[Label] = []
var account_status: Label
var account_refresh: Button
var quote_status: Label
var quote_refresh: Button
var position_heading: Label
var position_detail: Label
var position_time: Label
var position_button: Button
var _seen_snapshot := ""
var selected := 0
var _chart_selection_code := ""
var stock_buttons: Array[Button] = []
var period_buttons: Array[Button] = []
var workspace_buttons: Array[Button] = []
var workspace := "market"
var body: HBoxContainer
var market_detail_scroll: ScrollContainer
var center: VBoxContainer
var chart: Control
var title_label: Label
var sector_label: Label
var price_label: Label
var change_label: Label
var empty_label: Label
var stock_list: VBoxContainer
var dialog: AcceptDialog
var updating := false
var compact := false
var search: LineEdit
var market_page: Control
var live_portfolio_page: ScrollContainer
var simulator: Control
var simulation_plan: Dictionary = {}
var live_operation_draft: Dictionary = {}
var research_page: ScrollContainer
var research_buttons: Array[Button] = []
var research_title: Label
var research_view: Control
var note_editor: TextEdit
var note_status: Label
var notes_by_code: Dictionary = {}
var brief_panel: PanelContainer
var watch_panel: PanelContainer
var market_tiles: Array[Control] = []
var market_strip: Control
var market_actions: Control
var portfolio_button: Button
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
var operations: Array = []
var _recording := false
var catalog: Node
var catalog_panel: Control
var catalog_preview_code := ""
var watch_groups: RefCounted
var watch_table: Control
var watch_table_button: Button

func _ready() -> void:
	if not embedded_in_camp:
		get_window().min_size = Vector2i(900,680)
	profile = Store.new(storage_path)
	var saved: Dictionary = profile.load_profile()
	watch_groups = WatchGroups.new()
	watch_groups.load_state(saved.get("watchlist_view", WatchGroups.defaults()))
	watchlist_codes = saved.watchlist
	security_names = saved.get("security_names",{}).duplicate()
	for code: String in watchlist_codes:
		if Data.valid_code(code) and _security_index(code)<0:
			securities.append({"code":code,"name":security_names.get(code,code),"sector":"KRX"})
	notes_by_code = saved.notes
	live_operation_draft = saved.get("live_operation_draft",Record.empty_draft()).duplicate(true)
	simulation_plan = saved.get("simulation_plan",{}).duplicate(true)
	operations = saved.operations
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
	_build_portfolio_link(page)
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
	market_detail_scroll = ScrollContainer.new()
	market_detail_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_expand(market_detail_scroll,true)
	body.add_child(market_detail_scroll)
	center = _vbox(10)
	_expand(center,true)
	market_detail_scroll.add_child(center)
	_build_detail()
	_build_brief()
	_build_portfolio(workspace_host)
	_build_research(workspace_host)
	var status := _hbox()
	page.add_child(status)
	status_label = _label("일봉은 전일까지 · 계좌는 조회 시점 기준 · 자동 시세 갱신 없음",11,T.MUTED)
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
	catalog = MarketCatalog.new()
	catalog.name = "MarketCatalog"
	add_child(catalog)
	catalog_panel = MarketCatalogPanel.new()
	add_child(catalog_panel)
	catalog_panel.set_catalog(catalog)
	catalog_panel.set_watched_codes(watchlist_codes)
	catalog_panel.security_chosen.connect(_catalog_security_chosen)
	watch_table = WatchTable.new()
	add_child(watch_table)
	watch_table.set_model(watch_groups)
	watch_table.preferences_changed.connect(_watch_preferences_changed)
	watch_table.membership_requested.connect(_group_membership_requested)
	watch_table.security_selected.connect(_table_security_selected)
	watch_table.open_security.connect(_table_open_security)
	watch_table.research_requested.connect(_table_open_research)
	watch_table.catalog_requested.connect(_watch_catalog_requested)
	watch_table.quotes_refresh_requested.connect(_watch_quotes_requested)
	watch_table.quotes_cancel_requested.connect(research_view.nh_quotes.cancel)
	research_view.nh_quotes.changed.connect(_refresh_watch_table)
	catalog.changed.connect(_refresh_watch_table)
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
	data_badge = _label("KIS · OBSERVED",11,T.GOLD,true)
	badge.add_child(data_badge)
	header.add_child(badge)

func _build_markets(page: Node) -> void:
	var strip := _hbox(8)
	market_strip = strip
	page.add_child(strip)
	for caption: String in ["순자산 · 증권사 기준","예수금 · 주문가능금액 아님","주식평가액 · 증권사 기준","평가손익 · 증권사 기준"]:
		var tile := _panel(10)
		_expand(tile)
		strip.add_child(tile)
		market_tiles.append(tile)
		var box := _vbox(2)
		tile.add_child(box)
		box.add_child(_label(caption,10,T.MUTED))
		var amount := _label("—",20,T.GOLD,true)
		box.add_child(amount)
		account_labels.append(amount)

func _build_portfolio_link(page: Node) -> void:
	market_actions = _hbox(8)
	page.add_child(market_actions)
	account_status = _wrap("계좌를 조회하면 보유종목이 관심종목과 함께 표시됩니다.",11,T.MUTED)
	market_actions.add_child(account_status)
	account_refresh = _button("잔고 새로고침",func() -> void: simulator.refresh_account())
	market_actions.add_child(account_refresh)
	portfolio_button = _button("작전 시뮬레이터 →",_select_workspace.bind("portfolio"))
	market_actions.add_child(portfolio_button)

func _build_watchlist() -> void:
	watch_panel = _panel(12)
	watch_panel.custom_minimum_size.x = 222
	body.add_child(watch_panel)
	var box := _vbox(10)
	watch_panel.add_child(box)
	var heading := _hbox(4)
	box.add_child(heading)
	var title := _label("보유 · 관심",14,T.GOLD)
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
	search.placeholder_text = "현재 보유·관심 검색"
	search.tooltip_text = "Ctrl+K로 현재 목록 검색 · 결과가 없으면 Enter로 시장 전체 검색"
	search.custom_minimum_size.y = 34
	search.add_theme_font_size_override("font_size",12)
	search.text_changed.connect(_filter_stocks)
	search.text_submitted.connect(_submit_search)
	box.add_child(search)
	var catalog_open := _button("시장 전체 검색 ↗",_open_catalog)
	catalog_open.name = "OpenMarketCatalog"
	catalog_open.tooltip_text = "저장된 시장 종목 마스터 · ETF와 우선주 포함"
	catalog_open.add_theme_font_size_override("font_size",11)
	box.add_child(catalog_open)
	watch_table_button = _button("관심그룹 · 종목표 ↗", _open_watch_table)
	watch_table_button.name = "OpenWatchlistTable"
	watch_table_button.add_theme_font_size_override("font_size",11)
	box.add_child(watch_table_button)
	var scroll := ScrollContainer.new()
	_expand(scroll,true)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.follow_focus = true
	box.add_child(scroll)
	stock_list = _vbox(5)
	_expand(stock_list)
	scroll.add_child(stock_list)
	empty_label = _wrap("검색 결과가 없습니다.",12,T.MUTED)
	stock_list.add_child(empty_label)
	_rebuild_stock_buttons()
	box.add_child(_label("현재 목록 · 시장 전체 검색은 위 버튼",10,T.MUTED))

func _rebuild_stock_buttons() -> void:
	for button: Button in stock_buttons:
		stock_list.remove_child(button)
		button.queue_free()
	stock_buttons.clear()
	stock_prices.clear()
	stock_tags.clear()
	for index: int in securities.size():
		var stock: Dictionary = securities[index]
		var button := _button("",_select_stock.bind(index))
		button.name = "Stock_"+stock.code
		button.toggle_mode = true
		button.custom_minimum_size.y = 68
		stock_list.add_child(button)
		stock_buttons.append(button)
		var margin := MarginContainer.new()
		margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		for side: String in ["left","right"]: margin.add_theme_constant_override("margin_"+side,9)
		margin.add_theme_constant_override("margin_top",7)
		margin.mouse_filter = Control.MOUSE_FILTER_IGNORE
		button.add_child(margin)
		var box := _vbox(5)
		box.mouse_filter = Control.MOUSE_FILTER_IGNORE
		margin.add_child(box)
		var name_label := _label(stock.name,13)
		name_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		box.add_child(name_label)
		var row := _hbox(4)
		row.mouse_filter = Control.MOUSE_FILTER_IGNORE
		box.add_child(row)
		var tag := _label(stock.code,10,T.MUTED)
		_expand(tag)
		row.add_child(tag)
		stock_tags.append(tag)
		var price := _label("—",12,T.TEXT,true)
		row.add_child(price)
		stock_prices.append(price)
	stock_list.move_child(empty_label,stock_list.get_child_count()-1)

func _rebuild_research_buttons() -> void:
	for button: Button in research_buttons:
		research_stock_row.remove_child(button)
		button.queue_free()
	research_buttons.clear()
	for index: int in securities.size():
		var button := _button(securities[index].name,_select_stock.bind(index))
		button.toggle_mode = true
		research_stock_row.add_child(button)
		research_buttons.append(button)

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
	quote_status = _wrap("",10,T.MUTED)
	box.add_child(quote_status)
	var controls := _hbox(5)
	box.add_child(controls)
	quote_refresh = _button("일봉 갱신",func() -> void: research_view.gateway.refresh())
	quote_refresh.add_theme_font_size_override("font_size",11)
	controls.add_child(quote_refresh)
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
	var legend_text := _label("휠 확대·축소 · 드래그 이동 · 더블클릭 복원",10,T.MUTED)
	legend_text.tooltip_text = "녹색 상승 · 적갈색 하락 · 하단 거래량\n휠은 커서 위치를 기준으로 확대·축소합니다."
	_expand(legend_text)
	legend_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	legend.add_child(legend_text)

func _build_brief() -> void:
	brief_panel = _panel(12)
	center.add_child(brief_panel)
	var box := _vbox(4)
	brief_panel.add_child(box)
	var row := _hbox(8)
	box.add_child(row)
	position_heading = _label("나의 배치 · 계좌 조회 전",13,T.GOLD)
	_expand(position_heading)
	row.add_child(position_heading)
	row.add_child(_button("종목 분석 · 참모 →",_open_selected_advisor))
	position_button = _button("이 종목 비중 변경 →",_open_selected_position)
	row.add_child(position_button)
	position_detail = _wrap("잔고를 조회하면 수량·평가액·손익·주식 내 비중을 표시합니다.",12)
	box.add_child(position_detail)
	position_time = _wrap("",10,T.MUTED)
	box.add_child(position_time)

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
	simulator.order_requested.connect(_show_simulation_plan)
	simulator.account_state_changed.connect(_account_changed)
	simulator.resume_requested.connect(func() -> void:
		if simulation_plan.is_empty():
			simulator.status_label.text = "저장된 실계좌 기반 명령서 초안이 없습니다. 계산 후 적용해주세요."
			return
		dialog.open_plan(simulation_plan,live_operation_draft))

func _build_research(host: Node) -> void:
	research_page = _scroll_page(host,"ResearchWorkspace")
	var box := _vbox(12)
	_expand(box)
	research_page.add_child(box)
	var stock_scroll := ScrollContainer.new()
	stock_scroll.custom_minimum_size.y = 48
	stock_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	stock_scroll.follow_focus = true
	box.add_child(stock_scroll)
	research_stock_row = _hbox(6)
	stock_scroll.add_child(research_stock_row)
	_rebuild_research_buttons()
	research_view = ResearchDetail.new()
	box.add_child(research_view)
	research_title = research_view.title_label
	note_editor = research_view.note_editor
	note_status = research_view.note_status
	note_editor.text_changed.connect(_note_changed)
	research_view.context_changed.connect(_sync_advisor)
	research_view.context_changed.connect(_render_market)
	research_view.advisor.append_to_order.connect(_append_advisor)

func _select_workspace(value: String) -> void:
	if not value in ["market","portfolio","research"]:
		return
	flush_profile()
	workspace = value
	market_strip.visible = value == "market" and size.y >= 800
	market_actions.visible = value == "market"
	data_badge.text = "KIS · READ ONLY" if value=="portfolio" else ("KIS · OFFICIAL IR" if value=="research" else "KIS · OBSERVED")
	status_label.text = "실계좌 조회  /  배분 변경은 모의 계획" if value=="portfolio" else "일봉은 전일까지 · 계좌는 조회 시점 기준 · 자동 시세 갱신 없음"
	market_page.visible = value == "market"
	live_portfolio_page.visible = value == "portfolio"
	research_page.visible = value == "research"
	for index: int in workspace_buttons.size():
		workspace_buttons[index].set_pressed_no_signal(["market","portfolio","research"][index] == value)
	if value == "research":
		research_view.activate()
	if value in ["market","portfolio"]:
		simulator.activate()
	if value=="market": research_view.activate()

func _select_stock(index: int) -> void:
	if index<0 or index>=securities.size(): return
	flush_profile()
	if _chart_selection_code != securities[index].code:
		chart.set_history([])
	_chart_selection_code = securities[index].code
	selected = index
	var stock: Dictionary = securities[index]
	for i: int in stock_buttons.size():
		stock_buttons[i].set_pressed_no_signal(i==index)
		research_buttons[i].set_pressed_no_signal(i==index)
	title_label.text = stock.name
	sector_label.text = stock.code+"   /   "+stock.sector+"   /   마지막 일봉 종가"
	updating = true
	research_view.select_security(stock)
	note_editor.text = notes_by_code.get(stock.code,"")
	updating = false
	if workspace in ["market","research"]: research_view.activate()
	_refresh_favorite()
	_refresh_save_status()
	_render_market()
	_sync_advisor()

func _filter_stocks(query: String) -> void:
	var count := 0
	for index: int in stock_buttons.size():
		var stock: Dictionary = securities[index]
		var query_text := query.strip_edges().to_lower()
		stock_buttons[index].visible = (not watch_only or stock.code in watchlist_codes or stock.has("account_identity_conflict") or not _position_for(stock.code).is_empty()) if query_text.is_empty() else (stock.name+stock.code).to_lower().contains(query_text)
		if stock_buttons[index].visible:
			count += 1
	empty_label.visible = count == 0
	empty_label.text = "보유·관심 종목이 없습니다.\n계좌를 조회하거나 전체 보기에서 추가하세요." if query.strip_edges().is_empty() and watch_only else "검색 결과가 없습니다."
	watch_count.text = str(count)

func _submit_search(_text: String) -> void:
	for index: int in stock_buttons.size():
		if stock_buttons[index].visible:
			_select_stock(index)
			stock_buttons[index].grab_focus()
			return
	_open_catalog(search.text)

func _open_catalog(initial_query: String = "") -> void:
	_select_workspace("market")
	catalog_panel.set_watched_codes(watchlist_codes)
	catalog_panel.set_query(initial_query)
	catalog_panel.open(search)

func _catalog_security_chosen(item: Dictionary, add_to_watchlist: bool) -> void:
	if not MarketCatalog.can_register(item):
		catalog_panel.set_feedback(str(item.get("reason","식별자가 충돌하거나 저장 형식에 맞지 않습니다.")))
		return
	var code: String = str(item.get("code",""))
	var name_value: String = str(item.get("name",""))
	if not Data.valid_code(code) or name_value.is_empty() or name_value.length()>80:
		catalog_panel.set_feedback("종목 코드 또는 이름이 저장 형식에 맞지 않아 등록할 수 없습니다.")
		return
	if add_to_watchlist and code not in watchlist_codes and watchlist_codes.size()>=1000:
		catalog_panel.set_feedback("관심종목은 최대 1,000개까지 저장할 수 있습니다. 기존 관심종목을 해제한 뒤 다시 시도해주세요.")
		return
	var index := _security_index(code)
	if index>=0:
		var existing: Dictionary = securities[index]
		if existing.has("account_identity_conflict"):
			catalog_panel.set_feedback("같은 종목코드에 카탈로그와 계좌의 종목명이 달라 등록할 수 없습니다. 식별자를 확인해주세요.")
			return
		if existing.name!=name_value or (not str(existing.get("market","")).is_empty() and existing.get("market")!=item.get("market")) or (not str(existing.get("kind","")).is_empty() and existing.get("kind")!=item.get("kind")):
			catalog_panel.set_feedback("같은 종목코드에 다른 이름·시장·종류가 이미 있습니다. 식별자 충돌을 확인한 뒤 다시 시도해주세요.")
			return
	if not catalog_preview_code.is_empty() and catalog_preview_code!=code and catalog_preview_code not in watchlist_codes and not _account_contains_code(catalog_preview_code):
		var preview_index := _security_index(catalog_preview_code)
		if preview_index>=0:
			securities.remove_at(preview_index)
			if preview_index<index:
				index -= 1
	catalog_preview_code = ""
	if index<0:
		var support: Dictionary = MarketCatalog.chart_support(item)
		securities.append({"code":code,"name":name_value,"sector":str(item.get("market","KRX"))+" · "+str(item.get("kind","종목")),
			"market":item.get("market",""),"kind":item.get("kind",""),"source":item.get("source",""),
			"collected_at":item.get("collected_at",""),"chart_unsupported_reason":"" if bool(support.get("supported",false)) else str(support.get("reason","일봉 조회 미지원"))})
		index = securities.size()-1
	# Re-selecting the same preview must keep its temporary ownership marker.
	if not add_to_watchlist and code not in watchlist_codes and not _account_contains_code(code):
		catalog_preview_code = code
	_rebuild_stock_buttons()
	_rebuild_research_buttons()
	if add_to_watchlist and code not in watchlist_codes:
		watchlist_codes.append(code)
		_queue_profile_save()
		flush_profile()
	if not add_to_watchlist and code not in watchlist_codes and _position_for(code).is_empty():
		watch_only = false
		all_stocks_button.set_pressed_no_signal(true)
		all_stocks_button.text = "보유·관심"
	catalog_panel.set_watched_codes(watchlist_codes)
	search.clear()
	_filter_stocks("")
	_select_stock(index)
	catalog_panel.close()
	_focus_catalog_stock.call_deferred(code)

func _focus_catalog_stock(code: String) -> void:
	var index := _security_index(code)
	if index>=0 and index<stock_buttons.size() and stock_buttons[index].is_inside_tree():
		stock_buttons[index].grab_focus()

func _table_rows() -> Array:
	var rows: Array = WatchTableData.build(securities, simulator.account, research_view.gateway, catalog.items if is_instance_valid(catalog) else [])
	for row: Dictionary in rows:
		if row.get("identity_conflict") == true:
			row.merge({"price":null,"quote_source":"—","quote_time":"—","quote_status":"식별자 확인","quote_reason":"종목 식별자가 충돌해 NH 현재가 연결을 보류합니다."},true)
		else:
			row.merge(research_view.nh_quotes.row_fields(row.code),true)
	return rows

func _refresh_watch_table(force := false) -> void:
	if not is_instance_valid(watch_table) or not is_instance_valid(research_view):
		return
	var rows := _table_rows()
	var previous_reason: String = research_view.gateway.unsupported_reason
	for row: Dictionary in rows:
		if row.code == securities[selected].code:
			research_view.set_identity_conflict(row.get("identity_conflict") == true)
			break
	if research_view.gateway.unsupported_reason != previous_reason:
		rows = _table_rows()
	if watch_table.visible or force:
		watch_table.set_rows(rows, watchlist_codes, securities[selected].code)
		watch_table.set_quote_progress(research_view.nh_quotes.busy, research_view.nh_quotes.summary)

func _watch_quotes_requested(codes: Array) -> void:
	# Re-check the current group and identity at the integration boundary.
	var allowed := {}
	for row: Dictionary in watch_groups.rows_for(_table_rows(), watchlist_codes):
		if row.get("identity_conflict") != true:
			allowed[row.code] = true
	var requested: Array = []
	for code: Variant in codes:
		if code is String and allowed.has(code):
			requested.append(code)
	research_view.nh_quotes.refresh(requested)

func _open_watch_table() -> void:
	_select_workspace("market")
	catalog_panel.close()
	_refresh_watch_table(true)
	watch_table.open(watch_table_button)

func _watch_preferences_changed() -> void:
	_queue_profile_save()
	_refresh_watch_table()

func _group_membership_requested(group_id: String, code: String, add: bool) -> void:
	if not watch_groups.has_group(group_id):
		watch_table.set_feedback("사용자 그룹을 먼저 선택하세요.")
		return
	if add:
		var index := _security_index(code)
		if index < 0 or not Data.valid_code(code) or securities[index].has("account_identity_conflict"):
			watch_table.set_feedback("종목 식별자를 확인할 수 없어 그룹에 편입하지 않았습니다.")
			return
		if code not in watchlist_codes and watchlist_codes.size() >= 1000:
			watch_table.set_feedback("전체 관심은 최대 1,000개입니다. 기존 관심을 해제한 뒤 추가하세요.")
			return
		if not watch_groups.add_code(group_id,code):
			watch_table.set_feedback(watch_groups.message)
			return
		if code not in watchlist_codes:
			watchlist_codes.append(code)
		if catalog_preview_code == code:
			catalog_preview_code = ""
	else:
		if not watch_groups.remove_code(group_id,code):
			watch_table.set_feedback(watch_groups.message)
			return
	watch_table.set_feedback("그룹에 편입했습니다. 전체 관심에도 보존됩니다." if add else "그룹에서 제거했습니다. 관심과 노트는 유지됩니다.", false)
	catalog_panel.set_watched_codes(watchlist_codes)
	_refresh_favorite()
	_filter_stocks(search.text)
	_watch_preferences_changed()

func _table_security_selected(code: String) -> void:
	var index := _security_index(code)
	if index >= 0 and securities[selected].code != code:
		_select_stock(index)

func _table_open_security(code: String) -> void:
	_table_security_selected(code)
	watch_table.close()
	_focus_catalog_stock.call_deferred(code)

func _table_open_research(code: String) -> void:
	_table_security_selected(code)
	watch_table.close()
	_open_selected_advisor()

func _watch_catalog_requested() -> void:
	watch_table.close()
	_open_catalog()

func _set_period(days: int) -> void:
	chart.set_period(days)
	for index: int in period_buttons.size():
		period_buttons[index].set_pressed_no_signal([22,66,252][index] == days)

func _set_chart_mode(value: String) -> void:
	chart.display_mode = value
	chart.queue_redraw()
	for index: int in chart_mode_buttons.size():
		chart_mode_buttons[index].set_pressed_no_signal(["candles","line"][index] == value)

func _show_plan() -> void:
	if simulation_plan.is_empty():
		_select_workspace("portfolio")
		simulator.status_label.text = "실계좌 변경안을 계산하고 명령서에 적용해주세요."
		return
	dialog.open_plan(simulation_plan,live_operation_draft)

func _show_simulation_plan(plan: Dictionary, evidence: String) -> void:
	var combined: String = live_operation_draft.get("rationale","")
	if not combined.contains(evidence): combined += ("\n\n" if not combined.is_empty() else "")+evidence
	if combined.length()>Record.MAX_TEXT:
		simulator.status_label.text = "기존 초안과 합치면 2,000자를 넘습니다. 참모 검토 없이 계산안을 적용하거나 초안을 줄여주세요."
		return
	var proposed := live_operation_draft.duplicate(true)
	proposed.rationale = combined
	if plan.get("source") != Record.LIVE_SOURCE or not Record.validate(Record.from_snapshot(plan,{"title":"검증","rationale":"검증","risk":"검증"})):
		simulator.status_label.text = "계산안의 수량과 금액을 검증하지 못했습니다."
		return
	simulation_plan = plan.duplicate(true)
	live_operation_draft = proposed
	_sync_advisor()
	_queue_profile_save()
	flush_profile()
	dialog.open_plan(simulation_plan,live_operation_draft)

func _current_draft() -> Dictionary:
	return live_operation_draft

func _operation_draft_changed(value: Dictionary) -> void:
	live_operation_draft = value.duplicate(true)
	_queue_profile_save()
	_sync_advisor()
	if not Record.valid_draft(value):
		dialog.show_feedback("판단 근거와 위험은 각각 2,000자 이내로 작성해주세요.")
	else:
		dialog.show_feedback("작성 중인 초안을 자동 저장합니다. 봉인하면 확정 시점의 기록으로 남습니다.",false)

func _profile_extra(entries: Array) -> Dictionary:
	var watched_names := {}
	for stock: Dictionary in securities:
		if stock.code in watchlist_codes: watched_names[stock.code] = stock.name
	return {"operations":entries,"live_operation_draft":live_operation_draft,"simulation_plan":simulation_plan,"security_names":watched_names,"watchlist_view":watch_groups.export_state()}

func _record_operation() -> void:
	if _recording or dialog.recorded:
		return
	if not Record.valid_draft(_current_draft(),true):
		dialog.show_feedback("작전 이름·판단 근거·주요 위험을 모두 작성해주세요. 근거와 위험은 각각 2,000자까지입니다.")
		return
	if operations.size() >= Record.MAX_OPERATIONS:
		dialog.show_feedback("작전 일지의 200건 한도에 도달했습니다. 기존 기록은 그대로 보존됩니다.")
		return
	var record := Record.from_snapshot(simulation_plan,live_operation_draft)
	if record.is_empty():
		dialog.show_feedback("목표 비중과 가용 현금을 확인한 뒤 다시 작성해주세요.")
		return
	_recording = true
	save_timer.stop()
	var proposed := operations.duplicate(true)
	proposed.append(record)
	var next_draft := Record.empty_draft()
	var extra := _profile_extra(proposed)
	extra.live_operation_draft = next_draft
	extra.simulation_plan = {}
	if profile.save_profile(watchlist_codes,notes_by_code,extra):
		operations = proposed
		live_operation_draft = next_draft
		simulation_plan = {}
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
	var code: String = securities[selected].code
	if note_editor.text.is_empty():
		notes_by_code.erase(code)
	else:
		notes_by_code[code] = note_editor.text
	_queue_profile_save()
	_sync_advisor()

func _sync_advisor() -> void:
	if updating or not is_instance_valid(research_view):
		return
	var stock: Dictionary = securities[selected]
	var conflict: String = str(stock.get("account_identity_conflict",""))
	var matched: bool = research_view.gateway.code==stock.code and conflict.is_empty()
	research_view.advisor.set_context({"code":stock.code,"name":stock.name,
		"quote":research_view.gateway.quote.duplicate(true) if matched else {},"financials":research_view.gateway.financials.duplicate(true) if matched else {},
		"note":notes_by_code.get(stock.code,""),"plan":_advisor_plan() if conflict.is_empty() else {},"draft":live_operation_draft.duplicate(true),
		"identity_conflict":conflict})

func _advisor_plan() -> Dictionary:
	if simulation_plan.is_empty(): return {}
	var plan_rows: Array = []
	for row: Dictionary in simulation_plan.rows:
		plan_rows.append({"code":row.code,"name":row.name,"target":row.target})
	return {"source":Record.LIVE_SOURCE,"observed_at":simulation_plan.observed_at,"rows":plan_rows}

func _append_advisor(field: String, text: String) -> void:
	if field not in ["rationale","risk"] or text.is_empty():
		return
	var previous: String = live_operation_draft.get(field,"")
	if previous.contains(text):
		research_view.advisor.status_label.text = "이미 명령서 초안에 들어 있는 내용입니다."
		return
	var combined := previous+("\n\n" if not previous.is_empty() else "")+text
	if combined.length()>Record.MAX_TEXT:
		research_view.advisor.status_label.text = "명령서의 2,000자 한도를 넘습니다. 기존 초안을 줄인 뒤 추가하세요."
		return
	live_operation_draft[field] = combined
	_queue_profile_save()
	flush_profile()
	_sync_advisor()
	research_view.advisor.status_label.text = "초안에 추가했습니다. 저장 상태를 확인해주세요." if save_failed else "명령서 초안에 추가하고 저장했습니다."
	if not simulation_plan.is_empty(): _show_plan()

func active_popup() -> Window:
	if research_view.advisor.settings.visible:
		return research_view.advisor.settings
	return dialog if is_instance_valid(dialog) and dialog.visible else null

func _responsive() -> void:
	market_strip.visible = workspace == "market" and size.y >= 800
	compact = size.x < 1120
	chart.custom_minimum_size.y = 145 if size.y<720 else 190
	watch_panel.custom_minimum_size.x = 202 if compact else 222
	brief_panel.show()
	# The market strip stays useful on smaller desktops without forcing overflow.
	market_tiles[3].visible = size.x >= 1060

func _unhandled_key_input(event: InputEvent) -> void:
	if not is_visible_in_tree() or dialog.visible:
		return
	if is_instance_valid(watch_table) and watch_table.visible:
		if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE:
			watch_table.handle_escape()
			get_viewport().set_input_as_handled()
		return
	if is_instance_valid(catalog_panel) and catalog_panel.visible:
		if event is InputEventKey and event.pressed and not event.echo and event.keycode==KEY_ESCAPE:
			catalog_panel.close()
			get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and event.pressed and not event.echo and event.ctrl_pressed and event.keycode == KEY_K:
		_select_workspace("market")
		search.grab_focus()
		search.select_all()
		get_viewport().set_input_as_handled()

func _toggle_catalogue() -> void:
	watch_only = not watch_only
	all_stocks_button.set_pressed_no_signal(not watch_only)
	all_stocks_button.text = "보유·관심" if not watch_only else "전체 보기"
	_filter_stocks(search.text)

func _toggle_favorite() -> void:
	var code: String = securities[selected].code
	if code in watchlist_codes:
		watchlist_codes.erase(code)
		watch_groups.remove_code_everywhere(code)
	else:
		if securities[selected].has("account_identity_conflict"):
			_refresh_favorite()
			return
		if watchlist_codes.size()>=1000:
			_refresh_favorite()
			return
		watchlist_codes.append(code)
		if catalog_preview_code==code:
			catalog_preview_code = ""
	if is_instance_valid(catalog_panel):
		catalog_panel.set_watched_codes(watchlist_codes)
	_refresh_favorite()
	_filter_stocks(search.text)
	_queue_profile_save()
	_refresh_watch_table()
	flush_profile()

func _refresh_favorite() -> void:
	var included: bool = securities[selected].code in watchlist_codes
	favorite_button.set_pressed_no_signal(included)
	favorite_button.text = "★ 관심" if included else "☆ 추가"
	favorite_button.disabled = not included and (watchlist_codes.size()>=1000 or securities[selected].has("account_identity_conflict"))
	favorite_button.tooltip_text = "전체 관심과 모든 그룹에서 해제 · 노트는 유지" if included else ("계좌와 카탈로그의 종목명이 달라 등록할 수 없습니다" if securities[selected].has("account_identity_conflict") else ("관심종목 최대 1,000개 · 기존 항목을 해제한 뒤 추가하세요" if favorite_button.disabled else "관심종목에 추가"))

func _queue_profile_save() -> void:
	profile_dirty = true
	save_failed = false
	save_timer.start()
	_refresh_save_status()

func flush_profile() -> void:
	if profile == null or not profile_dirty:
		return
	save_timer.stop()
	if profile.save_profile(watchlist_codes,notes_by_code,_profile_extra(operations)):
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

func _security_index(code: String) -> int:
	for index: int in securities.size():
		if securities[index].code==code: return index
	return -1

func _position_for(code: String) -> Dictionary:
	if not is_instance_valid(simulator): return {}
	var security_index := _security_index(code)
	if security_index>=0 and securities[security_index].has("account_identity_conflict"):
		return {}
	for row: Dictionary in simulator.account.get("rows",[]):
		if row.code==code: return row
	return {}

func _account_contains_code(code: String) -> bool:
	if not is_instance_valid(simulator): return false
	for row: Dictionary in simulator.account.get("rows",[]):
		if row.code==code: return true
	return false

func _account_changed() -> void:
	var account: Dictionary = simulator.account
	var snapshot: String = account.get("snapshot_id","")
	if not account.is_empty() and snapshot!=_seen_snapshot:
		_seen_snapshot = snapshot
		var selected_name: String = securities[selected].name
		var selected_conflict: String = str(securities[selected].get("account_identity_conflict",""))
		for stock: Dictionary in securities:
			if stock.has("account_identity_conflict"):
				stock.erase("account_identity_conflict")
				stock["chart_unsupported_reason"] = ""
		for row: Dictionary in account.rows:
			if not Data.valid_code(row.code): continue
			var index := _security_index(row.code)
			if index<0:
				securities.append({"code":row.code,"name":row.name,"sector":"KRX"})
			elif (securities[index].has("source") or security_names.has(row.code)) and securities[index].name!=row.name:
				# A code with conflicting catalogue/account identities cannot inherit a position or quote.
				securities[index]["account_identity_conflict"] = row.name
				securities[index]["chart_unsupported_reason"] = "같은 종목코드에 카탈로그와 계좌의 종목명이 달라 일봉 대상을 확정할 수 없습니다."
			else:
				securities[index].name = row.name
		_rebuild_stock_buttons()
		_rebuild_research_buttons()
		_filter_stocks(search.text)
		for i: int in securities.size():
			stock_buttons[i].set_pressed_no_signal(i==selected)
			research_buttons[i].set_pressed_no_signal(i==selected)
		if securities[selected].name!=selected_name or str(securities[selected].get("account_identity_conflict",""))!=selected_conflict:
			var selected_stock: Dictionary = securities[selected]
			title_label.text = selected_stock.name
			sector_label.text = selected_stock.code+"   /   "+selected_stock.sector+"   /   마지막 일봉 종가"
			updating = true
			research_view.select_security(selected_stock)
			updating = false
			_refresh_favorite()
			_sync_advisor()
		# Persist only explicitly watched names; balances remain in memory.
		_queue_profile_save()
	account_refresh.disabled = simulator.busy
	if account.is_empty():
		account_status.text = simulator.status_label.text
	else:
		var summary: Dictionary = account.summary
		for i: int in 4:
			account_labels[i].text = Data.money(float(summary[["net_assets","deposit_total","securities_evaluation_amount","profit_loss_total"][i]]))+" 원"
		account_labels[3].add_theme_color_override("font_color",T.ACCENT if float(summary.profit_loss_total)>=0 else T.RED)
		account_status.text = "%d종목 · 잔고 %s" % [account.rows.size(),simulator._time(account.observed_at)]
		if simulator.stale: account_status.text += " · 이전 잔고 / 재조회 필요"
		if not account.get("warnings",[]).is_empty(): account_status.text += " · 계좌 요약 변동 확인 필요"
	account_status.add_theme_color_override("font_color",T.RED if simulator.stale else T.MUTED)
	_render_market()

func _render_market() -> void:
	if not is_instance_valid(research_view) or not is_instance_valid(quote_status): return
	var gateway: Node = research_view.gateway
	var quote: Dictionary = gateway.quote if gateway.code==securities[selected].code else {}
	quote_refresh.disabled = gateway.quote_state in ["loading","unsupported"]
	quote_status.text = gateway.quote_message
	quote_status.add_theme_color_override("font_color",T.RED if gateway.quote_state in ["stale","error","unsupported"] else T.MUTED)
	if quote.is_empty():
		price_label.text = "—"
		change_label.text = "일봉 자료 없음"
		change_label.add_theme_color_override("font_color",T.MUTED)
		chart.set_history([])
	else:
		var candles: Array = quote.candles
		var change: float = (float(candles[-1].close)/float(candles[-2].close)-1)*100
		price_label.text = Data.money(candles[-1].close)+" 원"
		change_label.text = "%+.2f%% · 이전 일봉 대비" % change
		change_label.add_theme_color_override("font_color",T.ACCENT if change>=0 else T.RED)
		var received := Time.get_datetime_string_from_unix_time(int(quote.fetched_at)+9*3600).replace("T"," ")
		quote_status.text += "\n일봉 %s · 거래량 %s주 · 수신 %s KST" % [quote.as_of,Data.money(candles[-1].volume),received]
		if Time.get_unix_time_from_system()-int(quote.fetched_at)>86400: quote_status.text += " · 하루 이상 지난 자료"
		if chart.full_history!=candles: chart.set_history(candles)
	for i: int in securities.size():
		var code: String = securities[i].code
		var position := _position_for(code)
		var stored: Dictionary = gateway.memory_quotes.get(code,{})
		if code==gateway.code: stored = gateway.quote
		if securities[i].has("account_identity_conflict"): stored = {}
		stock_tags[i].text = code+(" · 식별자 확인" if securities[i].has("account_identity_conflict") else (" · 보유" if not position.is_empty() else ""))
		stock_prices[i].text = Data.money(float(position.price)) if not position.is_empty() else (Data.money(stored.candles[-1].close) if not stored.is_empty() else "—")
		stock_buttons[i].tooltip_text = securities[i].name+" · "+code
		if securities[i].has("account_identity_conflict"):
			stock_buttons[i].tooltip_text += "\n계좌 종목명 "+str(securities[i].account_identity_conflict)+"과 일치하지 않아 연결을 보류합니다."
		if not position.is_empty(): stock_buttons[i].tooltip_text += "\n잔고 조회가 · "+simulator._time(position.price_observed_at)+(" · 이전 잔고" if simulator.stale else "")
		elif not stored.is_empty(): stock_buttons[i].tooltip_text += "\n마지막 일봉 종가 · "+stored.as_of
	_render_position()
	_refresh_watch_table()

func _render_position() -> void:
	var position := _position_for(securities[selected].code)
	position_button.disabled = position.is_empty() or simulator.stale or simulator.busy
	if securities[selected].has("account_identity_conflict"):
		position_heading.text = "나의 배치 · 식별자 확인 필요"
		position_detail.text = "같은 코드의 카탈로그 종목명("+securities[selected].name+")과 계좌 종목명("+str(securities[selected].account_identity_conflict)+")이 다릅니다."
		position_time.text = "계좌 보유량과 일봉 연결을 보류합니다. 종목 식별자를 확인해주세요."
		return
	if simulator.account.is_empty():
		position_heading.text = "나의 배치 · 계좌 조회 전"
		position_detail.text = "잔고를 조회하면 수량·평가액·손익·주식 내 비중을 표시합니다."
		position_time.text = "계좌 조회 실패 시 잔고 새로고침으로 다시 시도할 수 있습니다."
	elif position.is_empty():
		position_heading.text = "나의 배치 · 이 종목 미보유" if not simulator.stale else "나의 배치 · 이전 조회에서 미보유"
		position_detail.text = "관심종목으로 추적하고, 종목 분석에서 근거와 참모 의견을 검토하세요."
		position_time.text = "현재 시뮬레이터는 계좌에 보유한 종목의 배분 변경을 지원합니다."
	else:
		position_heading.text = "나의 배치 · "+securities[selected].name+(" / 이전 잔고" if simulator.stale else "")
		position_detail.text = "%s주 · 평가액 %s원 · 증권사 손익 %s원 · 주식 내 %.2f%%" % [position.quantity,Data.money(float(position.value)),Data.money(float(position.profit_loss)),float(position.stock_weight)]
		position_time.text = "잔고 조회가 %s원 · %s · 주식 내 비중은 조회 주식 평가액 기준" % [Data.money(float(position.price)),simulator._time(position.price_observed_at)]

func _open_selected_position() -> void:
	if position_button.disabled: return
	var code: String = securities[selected].code
	_select_workspace("portfolio")
	simulator.focus_position.call_deferred(code)

func _open_selected_advisor() -> void:
	_select_workspace("research")
	# Opening the advisor does not automatically send data or spend API credit.
	# Keep the selected security heading, chart and advisor heading together.
	research_page.set_deferred("scroll_vertical",0)

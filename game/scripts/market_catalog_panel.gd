extends Control
## Bounded, local catalogue search UI. The catalogue model owns data and refresh.

signal security_chosen(item: Dictionary, add_to_watchlist: bool)

const T = preload("res://scripts/terminal_theme.gd")
const Catalog = preload("res://scripts/market_catalog.gd")
const RESULT_LIMIT := 30

var catalog: Node
var watched_codes: Array = []
var selected_item: Dictionary = {}
var previous_focus: Control
var card: PanelContainer
var query_edit: LineEdit
var refresh_button: Button
var status_label: Label
var count_label: Label
var results: VBoxContainer
var detail_title: Label
var detail_code: Label
var detail_meta: Label
var detail_source: Label
var detail_support: Label
var feedback: Label
var add_button: Button
var view_button: Button

func _ready() -> void:
	name = "MarketCatalogPanel"
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	var shade := ColorRect.new()
	shade.color = Color(0.025,0.02,0.015,0.9)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(shade)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(center)
	card = PanelContainer.new()
	card.add_theme_stylebox_override("panel",T.panel_style(16))
	center.add_child(card)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation",10)
	card.add_child(content)
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation",8)
	content.add_child(header)
	var heading := _label("시장 전체 종목 검색",21,T.GOLD)
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(heading)
	refresh_button = _button("목록 갱신",_refresh)
	refresh_button.name = "RefreshMarketCatalog"
	header.add_child(refresh_button)
	header.add_child(_button("닫기  Esc",close))
	status_label = _label("",12,T.MUTED,true)
	content.add_child(status_label)
	query_edit = LineEdit.new()
	query_edit.name = "CatalogQuery"
	query_edit.placeholder_text = "종목 이름 또는 코드 검색 · ETF와 우선주 포함"
	query_edit.custom_minimum_size.y = 38
	query_edit.text_changed.connect(_query_changed)
	query_edit.text_submitted.connect(_submit_query)
	content.add_child(query_edit)
	count_label = _label("",12,T.MUTED)
	content.add_child(count_label)
	var columns := HBoxContainer.new()
	columns.add_theme_constant_override("separation",12)
	columns.size_flags_vertical = Control.SIZE_EXPAND_FILL
	content.add_child(columns)
	var scroll := ScrollContainer.new()
	scroll.name = "CatalogResultsScroll"
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	columns.add_child(scroll)
	results = VBoxContainer.new()
	results.name = "CatalogResults"
	results.add_theme_constant_override("separation",5)
	results.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(results)
	var details := PanelContainer.new()
	details.custom_minimum_size.x = 280
	details.add_theme_stylebox_override("panel",T.style(T.INSET,T.BORDER,2,14))
	columns.add_child(details)
	var detail_box := VBoxContainer.new()
	detail_box.add_theme_constant_override("separation",10)
	details.add_child(detail_box)
	detail_title = _label("종목을 선택하세요",17,T.TEXT,true)
	detail_box.add_child(detail_title)
	detail_code = _label("",13,T.GOLD)
	detail_box.add_child(detail_code)
	detail_meta = _label("",13,T.TEXT,true)
	detail_box.add_child(detail_meta)
	detail_source = _label("",12,T.MUTED,true)
	detail_box.add_child(detail_source)
	detail_support = _label("",12,T.MUTED,true)
	detail_box.add_child(detail_support)
	var detail_spacer := Control.new()
	detail_spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	detail_box.add_child(detail_spacer)
	feedback = _label("",12,T.RED,true)
	detail_box.add_child(feedback)
	add_button = _button("☆ 관심 추가 · 차트 보기",func() -> void: _choose(true))
	add_button.name = "CatalogAddFavorite"
	detail_box.add_child(add_button)
	view_button = _button("차트 · 리서치 보기",func() -> void: _choose(false))
	view_button.name = "CatalogViewSecurity"
	detail_box.add_child(view_button)
	content.add_child(_label("저장된 종목 목록에서 검색합니다. 선택만으로 참모 AI를 요청하지 않습니다.",11,T.MUTED))
	resized.connect(_layout)
	_layout()
	hide()

func _label(value: String, font_size: int, color: Color, wrap := false) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size",font_size)
	label.add_theme_color_override("font_color",color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if wrap:
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label

func _button(value: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = value
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size",13)
	button.pressed.connect(action)
	return button

func _layout() -> void:
	if card == null:
		return
	card.custom_minimum_size = Vector2(minf(920.0,maxf(500.0,size.x-32.0)),minf(610.0,maxf(450.0,size.y-28.0)))

func set_catalog(value: Node) -> void:
	if catalog != null and catalog.changed.is_connected(_render):
		catalog.changed.disconnect(_render)
	catalog = value
	if catalog != null:
		catalog.changed.connect(_render)
	_render()

func set_watched_codes(codes: Array) -> void:
	watched_codes = codes.duplicate()
	_show_selected()

func open(from_control: Control = null) -> void:
	previous_focus = from_control
	show()
	_render()
	query_edit.grab_focus()
	query_edit.select_all()

func set_query(value: String) -> void:
	query_edit.text = value
	set_feedback("")
	_render()

func _query_changed(_value: String) -> void:
	set_feedback("")
	_render()

func close() -> void:
	hide()
	if is_instance_valid(previous_focus) and previous_focus.is_visible_in_tree():
		previous_focus.grab_focus()

func set_feedback(value: String, is_error := true) -> void:
	feedback.text = value
	feedback.add_theme_color_override("font_color",T.RED if is_error else T.ACCENT)

func _refresh() -> void:
	if catalog != null:
		catalog.refresh()

func _render(_unused: String = "") -> void:
	if catalog == null or not is_instance_valid(results):
		return
	refresh_button.disabled = catalog.state == "loading"
	var time_text := _time_text(catalog.fetched_at)
	var catalog_message: String = catalog.message
	if catalog.items.is_empty():
		status_label.text = "최초 종목 자료 없음 · " + catalog_message
	else:
		status_label.text = catalog_message + " · 목록 수집 " + time_text
	status_label.add_theme_color_override("font_color",T.RED if catalog.state in ["stale","error"] else T.MUTED)
	var found: Dictionary = catalog.search(query_edit.text,RESULT_LIMIT)
	var shown: Array = found.get("items",[])
	var total: int = int(found.get("total",0))
	count_label.text = "검색 결과 %d건 · %d건 표시" % [total,shown.size()]
	if total > shown.size():
		count_label.text += " · 이름이나 코드로 좁혀주세요"
	for child: Node in results.get_children():
		results.remove_child(child)
		child.queue_free()
	if shown.is_empty():
		var empty_text := "최초 종목 자료가 없습니다. 목록 갱신을 눌러주세요." if catalog.items.is_empty() else "검색 결과 0건 · 다른 이름이나 코드를 입력해주세요."
		if catalog.state == "loading" and catalog.items.is_empty():
			empty_text = "최초 종목 목록을 가져오는 중…"
		elif catalog.state == "error" and catalog.items.is_empty():
			empty_text = "목록 갱신 실패 · 최초 자료가 없습니다. WSL 연결을 확인하고 다시 시도해주세요."
		results.add_child(_label(empty_text,13,T.MUTED,true))
	if not _selected_in(shown):
		selected_item = shown[0] if not shown.is_empty() else {}
	for item: Dictionary in shown:
		var code: String = str(item.get("code",""))
		var label: String = str(item.get("name","")) + "\n" + code + "  ·  " + str(item.get("market","")) + "  ·  " + str(item.get("kind",""))
		if bool(item.get("collision",false)):
			label = "⚠  " + label
		var row := _button(label,_select_item.bind(item))
		row.name = "CatalogResult_" + code
		row.alignment = HORIZONTAL_ALIGNMENT_LEFT
		row.custom_minimum_size.y = 55
		row.toggle_mode = true
		row.set_meta("catalog_item",item)
		row.set_pressed_no_signal(_same_item(item,selected_item))
		row.tooltip_text = "출처: %s\n수집: %s" % [item.get("source",""),item.get("collected_at","")]
		results.add_child(row)
	_show_selected()

func _selected_in(shown: Array) -> bool:
	for item: Dictionary in shown:
		if _same_item(item,selected_item):
			selected_item = item
			return true
	return false

func _same_item(left: Dictionary, right: Dictionary) -> bool:
	return not left.is_empty() and not right.is_empty() and left.get("code") == right.get("code") and left.get("name") == right.get("name") and left.get("market") == right.get("market") and left.get("kind") == right.get("kind")

func _select_item(item: Dictionary) -> void:
	selected_item = item
	set_feedback("")
	for child: Node in results.get_children():
		if child is Button:
			child.set_pressed_no_signal(_same_item(child.get_meta("catalog_item",{}),item))
	_show_selected()

func _show_selected() -> void:
	if not is_instance_valid(detail_title):
		return
	var item := selected_item
	if item.is_empty():
		detail_title.text = "종목을 선택하세요"
		detail_code.text = ""
		detail_meta.text = ""
		detail_source.text = ""
		detail_support.text = ""
		add_button.disabled = true
		view_button.disabled = true
		return
	var code: String = str(item.get("code",""))
	detail_title.text = str(item.get("name",""))
	detail_code.text = code
	detail_meta.text = "시장  %s\n종류  %s" % [item.get("market",""),item.get("kind","")]
	detail_source.text = "출처  %s\n수집  %s" % [item.get("source",""),item.get("collected_at","")]
	var support: Dictionary = Catalog.chart_support(item)
	var allowed: bool = Catalog.can_register(item)
	detail_support.text = "일봉  %s" % ["기존 KIS 경로로 조회 가능" if bool(support.get("supported",false)) else str(support.get("reason","지원되지 않는 코드입니다."))]
	if not allowed:
		detail_support.text += "\n등록 불가  " + str(item.get("reason","식별자 충돌 또는 저장 형식 미지원"))
	detail_support.add_theme_color_override("font_color",T.RED if not allowed or not bool(support.get("supported",false)) else T.MUTED)
	add_button.disabled = not allowed or code in watched_codes
	add_button.text = "★ 관심 등록됨" if code in watched_codes else "☆ 관심 추가 · 차트 보기"
	view_button.disabled = not allowed

func _submit_query(_query: String) -> void:
	if not selected_item.is_empty():
		_choose(false)

func _choose(add_to_watchlist: bool) -> void:
	if selected_item.is_empty() or not Catalog.can_register(selected_item):
		set_feedback("식별자 충돌 또는 지원하지 않는 저장 코드여서 등록할 수 없습니다.")
		return
	security_chosen.emit(selected_item.duplicate(true),add_to_watchlist)

func _time_text(value: Variant) -> String:
	if value is int or value is float:
		if int(value) > 0:
			return Time.get_datetime_string_from_unix_time(int(value) + 9 * 3600).replace("T"," ") + " KST"
	return str(value) if not str(value).is_empty() else "시각 없음"

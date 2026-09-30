extends Control
## Scrollable watchlist and holdings table. Prices remain in the market chart.

signal preferences_changed
signal membership_requested(group_id: String, code: String, add: bool)
signal security_selected(code: String)
signal open_security(code: String)
signal research_requested(code: String)
signal catalog_requested

const T = preload("res://scripts/terminal_theme.gd")
const COLUMNS := ["name", "code", "market", "kind", "held", "status"]
const TITLES := ["종목명", "코드", "시장", "종류", "보유", "조회 상태"]

var model: RefCounted
var source_rows: Array = []
var watched_codes: Array = []
var selected_code := ""
var previous_focus: Control
var visible_rows := {}
var _rendering := false
var _render_generation := 0
var _selection_generation := 0
var _pending_selection_code := ""
var _pending_delete_id := ""

var card: PanelContainer
var scope_picker: OptionButton
var group_name_edit: LineEdit
var create_button: Button
var rename_button: Button
var delete_button: Button
var confirm_bar: HBoxContainer
var confirm_label: Label
var filter_edit: LineEdit
var table: Tree
var count_label: Label
var selected_label: Label
var target_picker: OptionButton
var add_button: Button
var remove_button: Button
var chart_button: Button
var research_button: Button
var feedback_label: Label


func _ready() -> void:
	name = "WatchlistTablePanel"
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	var shade := ColorRect.new()
	shade.color = Color(0.025, 0.02, 0.015, 0.9)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(shade)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(center)
	card = PanelContainer.new()
	card.add_theme_stylebox_override("panel", T.panel_style(16))
	center.add_child(card)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 8)
	card.add_child(content)
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 8)
	content.add_child(header)
	var heading := _label("관심그룹 · 종목표", 21, T.GOLD)
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(heading)
	header.add_child(_button("닫기  Esc", close, "CloseWatchlistTable"))
	content.add_child(_label("관심종목과 보유종목을 그룹별로 살펴봅니다. 가격은 선택한 종목의 시장 차트에서 확인하세요.", 12, T.MUTED))

	var group_bar := HBoxContainer.new()
	group_bar.add_theme_constant_override("separation", 7)
	content.add_child(group_bar)
	group_bar.add_child(_label("목록", 13, T.TEXT))
	scope_picker = OptionButton.new()
	scope_picker.name = "GroupScope"
	scope_picker.custom_minimum_size = Vector2(190, 36)
	scope_picker.fit_to_longest_item = false
	scope_picker.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	scope_picker.item_selected.connect(_scope_changed)
	group_bar.add_child(scope_picker)
	group_name_edit = LineEdit.new()
	group_name_edit.name = "GroupNameEdit"
	group_name_edit.placeholder_text = "그룹 이름 · 새로 만들기 / 이름 변경"
	group_name_edit.custom_minimum_size.y = 36
	group_name_edit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	group_bar.add_child(group_name_edit)
	create_button = _button("새 그룹", _create_group, "CreateGroup")
	group_bar.add_child(create_button)
	rename_button = _button("이름 변경", _rename_group, "RenameGroup")
	group_bar.add_child(rename_button)
	delete_button = _button("삭제", _ask_delete_group, "DeleteGroup")
	group_bar.add_child(delete_button)

	confirm_bar = HBoxContainer.new()
	confirm_bar.name = "DeleteGroupConfirmation"
	confirm_bar.add_theme_constant_override("separation", 8)
	content.add_child(confirm_bar)
	confirm_label = _label("", 13, T.RED)
	confirm_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	confirm_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	confirm_bar.add_child(confirm_label)
	confirm_bar.add_child(_button("그룹 삭제 확인", _confirm_delete_group, "ConfirmDeleteGroup"))
	confirm_bar.add_child(_button("취소", _cancel_delete_group, "CancelDeleteGroup"))
	confirm_bar.hide()

	var filter_bar := HBoxContainer.new()
	filter_bar.add_theme_constant_override("separation", 8)
	content.add_child(filter_bar)
	filter_edit = LineEdit.new()
	filter_edit.name = "TableFilter"
	filter_edit.placeholder_text = "현재 목록에서 종목명 또는 코드 찾기"
	filter_edit.custom_minimum_size.y = 36
	filter_edit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	filter_edit.text_changed.connect(_filter_changed)
	filter_bar.add_child(filter_edit)
	count_label = _label("", 12, T.MUTED)
	count_label.custom_minimum_size.x = 210
	filter_bar.add_child(count_label)

	table = Tree.new()
	table.name = "WatchlistTree"
	table.columns = COLUMNS.size()
	table.column_titles_visible = true
	table.hide_root = true
	table.select_mode = Tree.SELECT_ROW
	table.custom_minimum_size.y = 210
	table.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	table.size_flags_vertical = Control.SIZE_EXPAND_FILL
	table.add_theme_stylebox_override("panel", T.style(T.INSET, T.BORDER, 2, 5))
	for column: int in COLUMNS.size():
		table.set_column_title(column, TITLES[column])
		table.set_column_expand(column, column == 0 or column == 5)
		table.set_column_custom_minimum_width(column, [210, 90, 82, 136, 90, 245][column])
		table.set_column_expand_ratio(column, 3 if column == 0 else 2)
	table.column_title_clicked.connect(_column_clicked)
	table.item_selected.connect(_tree_selected)
	table.item_activated.connect(_tree_activated)
	content.add_child(table)

	selected_label = _label("종목을 선택하세요.", 13, T.TEXT, true)
	selected_label.custom_minimum_size.y = 34
	selected_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	selected_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	content.add_child(selected_label)
	var membership_bar := HBoxContainer.new()
	membership_bar.add_theme_constant_override("separation", 8)
	content.add_child(membership_bar)
	membership_bar.add_child(_label("그룹 편입", 13, T.TEXT))
	target_picker = OptionButton.new()
	target_picker.name = "GroupTarget"
	target_picker.custom_minimum_size = Vector2(220, 36)
	target_picker.fit_to_longest_item = false
	target_picker.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	target_picker.item_selected.connect(_target_changed)
	membership_bar.add_child(target_picker)
	add_button = _button("선택 종목 추가", func() -> void: _request_membership(true), "AddToGroup")
	membership_bar.add_child(add_button)
	remove_button = _button("그룹에서 해제", func() -> void: _request_membership(false), "RemoveFromGroup")
	membership_bar.add_child(remove_button)
	var membership_spacer := Control.new()
	membership_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	membership_bar.add_child(membership_spacer)
	membership_bar.add_child(_label("그룹 추가 시 전체 관심에도 편입", 11, T.MUTED))

	var footer := HBoxContainer.new()
	footer.add_theme_constant_override("separation", 8)
	content.add_child(footer)
	chart_button = _button("차트 보기", _open_chart, "OpenSelectedChart")
	footer.add_child(chart_button)
	research_button = _button("리서치 · 참모", _open_research, "OpenSelectedResearch")
	footer.add_child(research_button)
	footer.add_child(_button("시장 전체 검색", _open_catalog, "OpenMarketCatalog"))
	var footer_spacer := Control.new()
	footer_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer.add_child(footer_spacer)
	feedback_label = _label("", 12, T.RED, true)
	feedback_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer.add_child(feedback_label)
	resized.connect(_layout)
	_layout()
	_render_all()
	hide()


func _label(value: String, font_size: int, color: Color, wrap := false) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if wrap:
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label


func _button(value: String, action: Callable, control_name := "") -> Button:
	var button := Button.new()
	button.text = value
	button.name = control_name
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_font_size_override("font_size", 13)
	button.pressed.connect(action)
	return button


func _layout() -> void:
	if card == null:
		return
	card.custom_minimum_size = Vector2(minf(1140.0, maxf(600.0, size.x - 28.0)), minf(790.0, maxf(540.0, size.y - 16.0)))


func set_model(value: RefCounted) -> void:
	if model != null and model.changed.is_connected(_render_all):
		model.changed.disconnect(_render_all)
	model = value
	if model != null:
		model.changed.connect(_render_all)
	_render_all()


func set_rows(rows: Array, watchlist: Array, code: String) -> void:
	source_rows = rows.duplicate(true)
	watched_codes = watchlist.duplicate()
	if not _pending_selection_code.is_empty() and _source_has_code(_pending_selection_code):
		selected_code = _pending_selection_code
	else:
		if not _pending_selection_code.is_empty():
			_pending_selection_code = ""
			_selection_generation += 1
		if not code.is_empty():
			selected_code = code
	_render_rows()


func _source_has_code(code: String) -> bool:
	for row: Dictionary in source_rows:
		if str(row.get("code", "")) == code:
			return true
	return false


func open(from_control: Control = null) -> void:
	previous_focus = from_control
	show()
	_render_all()
	filter_edit.grab_focus()


func close() -> void:
	_cancel_delete_group()
	if not _pending_selection_code.is_empty():
		_pending_selection_code = ""
		_selection_generation += 1
	hide()
	if is_instance_valid(previous_focus) and previous_focus.is_visible_in_tree():
		previous_focus.grab_focus()


func handle_escape() -> bool:
	if not visible:
		return false
	if confirm_bar.visible:
		_cancel_delete_group()
		return true
	close()
	return true


func _input(event: InputEvent) -> void:
	if not visible or not event is InputEventKey:
		return
	var key: InputEventKey = event
	if key.pressed and not key.echo and key.keycode == KEY_ESCAPE and handle_escape():
		get_viewport().set_input_as_handled()


func set_feedback(value: String, is_error := true) -> void:
	if feedback_label == null:
		return
	feedback_label.text = value
	feedback_label.add_theme_color_override("font_color", T.RED if is_error else T.ACCENT)


func _render_all() -> void:
	if scope_picker == null or model == null:
		return
	_render_group_controls()
	_render_rows()


func _render_group_controls() -> void:
	_rendering = true
	var old_target := _selected_option_id(target_picker)
	scope_picker.clear()
	_add_option(scope_picker, "전체 관심종목", "all")
	_add_option(scope_picker, "보유종목", "holdings")
	for group: Dictionary in model.groups:
		_add_option(scope_picker, str(group.get("name", "")), str(group.get("id", "")))
	_select_option(scope_picker, model.selected_group)
	var user_group: bool = model.has_group(model.selected_group)
	rename_button.disabled = not user_group
	delete_button.disabled = not user_group
	group_name_edit.text = str(model.get_group(model.selected_group).get("name", "")) if user_group else ""
	target_picker.clear()
	for group: Dictionary in model.groups:
		_add_option(target_picker, str(group.get("name", "")), str(group.get("id", "")))
	_select_option(target_picker, model.selected_group if user_group else old_target)
	_rendering = false
	_update_selected_controls()


func _add_option(picker: OptionButton, label: String, id: String) -> void:
	var index := picker.item_count
	picker.add_item(label)
	picker.set_item_metadata(index, id)


func _select_option(picker: OptionButton, id: String) -> void:
	for index: int in picker.item_count:
		if str(picker.get_item_metadata(index)) == id:
			picker.select(index)
			return
	if picker.item_count > 0:
		picker.select(0)


func _selected_option_id(picker: OptionButton) -> String:
	if picker == null or picker.selected < 0:
		return ""
	return str(picker.get_item_metadata(picker.selected))


func _render_rows() -> void:
	if table == null:
		return
	var anchor_code := ""
	if visible and table.get_root() != null and table.size.y > 0:
		var anchor: TreeItem = table.get_item_at_position(Vector2(18, table.size.y * 0.5))
		if anchor != null:
			anchor_code = str(anchor.get_metadata(0))
	_rendering = true
	_render_generation += 1
	visible_rows.clear()
	table.clear()
	var root := table.create_item()
	var rows: Array = model.rows_for(source_rows, watched_codes) if model != null else []
	var needle := filter_edit.text.strip_edges().to_lower()
	var selected_item: TreeItem
	for row: Dictionary in rows:
		var code := str(row.get("code", ""))
		if not needle.is_empty() and not (str(row.get("name", "")) + code).to_lower().contains(needle):
			continue
		if code.is_empty():
			continue
		visible_rows[code] = row
		var item := table.create_item(root)
		item.set_metadata(0, code)
		var member_names := _membership_names(code)
		var status := _cell(row, "status")
		var held_text := "확인 필요" if row.get("identity_conflict") == true and row.get("account_present") == true else ("보유" if bool(row.get("held", false)) else "—")
		for column: int in COLUMNS.size():
			var value := status if column == 5 else held_text if column == 4 else _cell(row, COLUMNS[column])
			item.set_text(column, value)
			item.set_selectable(column, true)
			item.set_tooltip_text(column, _row_tooltip(row, member_names))
		item.set_custom_color(0, T.TEXT)
		if held_text != "—":
			item.set_custom_color(4, T.RED if held_text == "확인 필요" else T.ACCENT)
		if code == selected_code:
			selected_item = item
	if selected_item != null:
		table.set_selected(selected_item, 0)
	if not anchor_code.is_empty():
		call_deferred("_restore_scroll_anchor", anchor_code, _render_generation)
	var total := rows.size()
	count_label.text = "%d개 중 %d개 표시" % [total, visible_rows.size()]
	for column: int in COLUMNS.size():
		var title: String = TITLES[column]
		if model != null and model.sort_column == COLUMNS[column]:
			title += " ↑" if model.sort_ascending else " ↓"
		table.set_column_title(column, title)
	_rendering = false
	_update_selected_controls()


func _restore_scroll_anchor(code: String, generation: int) -> void:
	if generation != _render_generation or not visible or table.get_root() == null:
		return
	var item: TreeItem = table.get_root().get_first_child()
	while item != null:
		if str(item.get_metadata(0)) == code:
			table.scroll_to_item(item, true)
			return
		item = item.get_next()


func _cell(row: Dictionary, key: String) -> String:
	var value: Variant = row.get(key)
	if value == null:
		return "—"
	var text_value := str(value).strip_edges()
	return text_value if not text_value.is_empty() else "—"


func _membership_names(code: String) -> Array:
	var names: Array = []
	if model == null:
		return names
	for group: Dictionary in model.groups:
		if code in group.get("codes", []):
			names.append(str(group.get("name", "")))
	return names


func _row_tooltip(row: Dictionary, names: Array) -> String:
	var result := "%s · %s\n시장 %s · 종류 %s\n상태 %s" % [_cell(row, "name"), _cell(row, "code"), _cell(row, "market"), _cell(row, "kind"), _cell(row, "status")]
	if row.get("status_reason") is String and not str(row.status_reason).is_empty():
		result += "\n" + str(row.status_reason)
	result += "\n포함 그룹: " + (", ".join(names) if not names.is_empty() else "없음")
	return result


func _update_selected_controls() -> void:
	if selected_label == null:
		return
	var row: Dictionary = visible_rows.get(selected_code, {})
	var target := _selected_option_id(target_picker)
	var visible_selection := not row.is_empty()
	if visible_selection:
		var names := _membership_names(selected_code)
		var short_names := ", ".join(names.slice(0, 2)) if not names.is_empty() else "없음"
		if names.size() > 2:
			short_names += " 외 %d개" % [names.size() - 2]
		selected_label.text = "선택  %s (%s) · 포함 그룹  %s" % [_cell(row, "name"), selected_code, short_names]
		selected_label.tooltip_text = "포함 그룹: " + (", ".join(names) if not names.is_empty() else "없음")
	elif selected_code.is_empty():
		selected_label.text = "종목을 선택하세요."
		selected_label.tooltip_text = ""
	else:
		selected_label.text = "현재 필터 밖 · 선택 코드 %s 유지 중" % selected_code
		selected_label.tooltip_text = selected_label.text
	var has_target: bool = model != null and model.has_group(target)
	var member: bool = has_target and selected_code in model.get_group(target).get("codes", [])
	add_button.disabled = not visible_selection or not has_target or member or row.get("identity_conflict") == true
	remove_button.disabled = not visible_selection or not has_target or not member
	chart_button.disabled = not visible_selection
	research_button.disabled = not visible_selection
	target_picker.disabled = target_picker.item_count == 0


func _scope_changed(_index: int) -> void:
	if _rendering or model == null:
		return
	var id := _selected_option_id(scope_picker)
	_cancel_delete_group()
	if model.select_group(id):
		preferences_changed.emit()
		set_feedback("")
	_render_group_controls()
	_render_rows()


func _target_changed(_index: int) -> void:
	if not _rendering:
		_update_selected_controls()


func _filter_changed(_value: String) -> void:
	_render_rows()


func _column_clicked(column: int, _mouse_button_index: int) -> void:
	if model == null or column < 0 or column >= COLUMNS.size():
		return
	var key: String = COLUMNS[column]
	var ascending: bool = not model.sort_ascending if model.sort_column == key else true
	model.set_sort(key, ascending)
	preferences_changed.emit()
	_render_rows()


func _tree_selected() -> void:
	if _rendering:
		return
	var item := table.get_selected()
	if item == null:
		return
	var code := str(item.get_metadata(0))
	if code.is_empty():
		return
	selected_code = code
	_update_selected_controls()
	# A synchronous market/research update can rebuild Tree during its own
	# mouse selection notification. Deliver only the last code after that event.
	_selection_generation += 1
	_pending_selection_code = code
	call_deferred("_emit_selected_code", code, _selection_generation)


func _emit_selected_code(code: String, generation: int) -> void:
	if generation == _selection_generation and _pending_selection_code == code and selected_code == code and _source_has_code(code) and visible:
		_pending_selection_code = ""
		security_selected.emit(code)


func _tree_activated() -> void:
	var item := table.get_selected()
	if item == null:
		return
	var code := str(item.get_metadata(0))
	selected_code = code
	call_deferred("_open_activated_code", code)


func _open_activated_code(code: String) -> void:
	if visible and selected_code == code and visible_rows.has(code):
		_open_chart()


func _create_group() -> void:
	if model == null:
		return
	var id: String = model.create_group(group_name_edit.text)
	if id.is_empty():
		set_feedback(str(model.message))
		return
	model.select_group(id)
	preferences_changed.emit()
	set_feedback("그룹을 만들었습니다.", false)
	_render_all()


func _rename_group() -> void:
	if model == null or not model.has_group(model.selected_group):
		return
	if not model.rename_group(model.selected_group, group_name_edit.text):
		set_feedback(str(model.message))
		return
	preferences_changed.emit()
	set_feedback("그룹 이름을 변경했습니다.", false)
	_render_group_controls()
	_render_rows()


func _ask_delete_group() -> void:
	if model == null or not model.has_group(model.selected_group):
		return
	_pending_delete_id = model.selected_group
	confirm_label.text = "'%s' 그룹을 삭제하시겠습니까? 전체 관심종목과 노트는 유지됩니다." % model.get_group(_pending_delete_id).get("name", "")
	confirm_label.tooltip_text = confirm_label.text
	confirm_bar.show()


func _confirm_delete_group() -> void:
	if model == null or _pending_delete_id.is_empty():
		return
	var id := _pending_delete_id
	_cancel_delete_group()
	if not model.delete_group(id):
		set_feedback(str(model.message))
		return
	preferences_changed.emit()
	set_feedback("그룹을 삭제했습니다. 관심종목과 노트는 유지됩니다.", false)
	_render_all()


func _cancel_delete_group() -> void:
	_pending_delete_id = ""
	if confirm_bar != null:
		confirm_bar.hide()


func _request_membership(add: bool) -> void:
	if model == null or not visible_rows.has(selected_code):
		return
	var target := _selected_option_id(target_picker)
	if not model.has_group(target):
		return
	membership_requested.emit(target, selected_code, add)


func _open_chart() -> void:
	if not visible_rows.has(selected_code):
		return
	var code := selected_code
	close()
	open_security.emit(code)


func _open_research() -> void:
	if not visible_rows.has(selected_code):
		return
	var code := selected_code
	close()
	research_requested.emit(code)


func _open_catalog() -> void:
	close()
	catalog_requested.emit()

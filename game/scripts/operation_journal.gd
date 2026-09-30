extends PanelContainer
const T := preload("res://scripts/terminal_theme.gd")
const Document := preload("res://scripts/operation_document.gd")
var records: Array = []
var list: ScrollContainer
var entries: VBoxContainer
var entry_buttons: Array[Button] = []
var document: PanelContainer
var empty: Label
var count_label: Label
var layout: BoxContainer

func _ready() -> void:
	add_theme_stylebox_override("panel",T.panel_style(18))
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation",12)
	add_child(page)
	var heading := Label.new()
	heading.text = "작전 일지"
	heading.add_theme_font_size_override("font_size",26)
	heading.add_theme_color_override("font_color",T.GOLD)
	page.add_child(heading)
	count_label = Label.new()
	count_label.add_theme_font_size_override("font_size",12)
	page.add_child(count_label)
	layout = BoxContainer.new()
	layout.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_theme_constant_override("separation",16)
	page.add_child(layout)
	list = ScrollContainer.new()
	list.name = "OperationEntries"
	list.custom_minimum_size.x = 245
	list.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	layout.add_child(list)
	entries = VBoxContainer.new()
	entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	entries.add_theme_constant_override("separation",8)
	list.add_child(entries)
	document = Document.new()
	document.name = "RecordedOrder"
	document.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	document.size_flags_vertical = Control.SIZE_EXPAND_FILL
	layout.add_child(document)
	empty = Label.new()
	empty.text = "아직 봉인한 작전이 없습니다.\n\n작전 지도 → 비중 계획 → 명령서 작성에서\n첫 계획과 판단 근거를 기록하세요."
	empty.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	empty.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	empty.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	layout.add_child(empty)
	resized.connect(_fit)
	_fit()

func set_records(value: Array) -> void:
	records = value.duplicate(true)
	records.reverse()
	for child: Node in entries.get_children():
		entries.remove_child(child)
		child.queue_free()
	entry_buttons.clear()
	for record: Dictionary in records:
		var button := Button.new()
		button.toggle_mode = true
		button.custom_minimum_size.y = 82
		button.tooltip_text = record.local_time+"\n"+record.title
		button.add_theme_stylebox_override("normal",T.style(T.INSET,T.BORDER,2,10))
		button.add_theme_stylebox_override("pressed",T.style(T.SELECTED,T.GOLD,2,10))
		var index := entry_buttons.size()
		button.pressed.connect(func() -> void: _select(index))
		entries.add_child(button)
		entry_buttons.append(button)
		var text := VBoxContainer.new()
		text.mouse_filter = Control.MOUSE_FILTER_IGNORE
		button.add_child(text)
		text.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		text.offset_left = 12
		text.offset_right = -12
		text.offset_top = 10
		text.offset_bottom = -10
		var date := Label.new()
		date.text = record.local_time
		date.add_theme_font_size_override("font_size",11)
		date.add_theme_color_override("font_color",T.MUTED)
		date.mouse_filter = Control.MOUSE_FILTER_IGNORE
		text.add_child(date)
		var caption := Label.new()
		caption.text = record.title
		caption.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		caption.max_lines_visible = 2
		caption.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		caption.add_theme_font_size_override("font_size",14)
		caption.add_theme_color_override("font_color",T.GOLD)
		caption.mouse_filter = Control.MOUSE_FILTER_IGNORE
		text.add_child(caption)
	count_label.text = "%d건의 기록  ·  최신 기록부터 표시  ·  확정 당시의 모의 계획" % records.size()
	document.visible = not records.is_empty()
	empty.visible = records.is_empty()
	list.visible = not records.is_empty()
	if not records.is_empty():
		_select(0)

func _select(index: int) -> void:
	if index >= 0 and index < records.size():
		for i: int in entry_buttons.size():
			entry_buttons[i].set_pressed_no_signal(i == index)
		document.display(records[index],records[index],true)

func _fit() -> void:
	layout.vertical = size.x < 1000
	list.custom_minimum_size = Vector2(0,108) if layout.vertical else Vector2(245,0)
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL if layout.vertical else Control.SIZE_FILL
	list.size_flags_vertical = Control.SIZE_FILL if layout.vertical else Control.SIZE_EXPAND_FILL

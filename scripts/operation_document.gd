extends PanelContainer
## Shared paper document for a draft and an immutable historical record.
signal draft_changed(value: Dictionary)
const T := preload("res://scripts/terminal_theme.gd")
const Data := preload("res://scripts/market_data.gd")
const Record := preload("res://scripts/operation_record.gd")
const PAPER := Color("dbc69e")
const INK := Color("3f3022")
var title_input: LineEdit
var rationale_input: TextEdit
var risk_input: TextEdit
var heading: Label
var date_label: Label
var summary: Label
var source_label: Label
var grid: GridContainer
var seal: Control
var scroll: ScrollContainer
var _updating := false
var _seal_tween: Tween

class Seal extends Control:
	var font: Font = T.font()
	func _ready() -> void:
		custom_minimum_size = Vector2(90,90)
		mouse_filter = Control.MOUSE_FILTER_IGNORE
	func _draw() -> void:
		var center := size*0.5
		var ink := Color("8e372b")
		draw_arc(center,35,0,TAU,80,ink,2,true)
		draw_arc(center,30,0,TAU,80,Color(ink,0.65),1,true)
		draw_string(font,center+Vector2(-20,-2),"기 록",HORIZONTAL_ALIGNMENT_LEFT,-1,16,ink)
		draw_string(font,center+Vector2(-20,19),"완 료",HORIZONTAL_ALIGNMENT_LEFT,-1,16,ink)
		draw_line(center+Vector2(-20,3),center+Vector2(20,3),ink,1)

func _ready() -> void:
	add_theme_stylebox_override("panel",T.style(PAPER,Color("9d7c4a"),2,20))
	scroll = ScrollContainer.new()
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	var page := VBoxContainer.new()
	page.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.add_theme_constant_override("separation",12)
	scroll.add_child(page)
	var header := HBoxContainer.new()
	page.add_child(header)
	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_label("P H A L A N X   /   COMMAND ORDER",11))
	heading = _label("작전 명령서",26)
	titles.add_child(heading)
	date_label = _label("작성 중 · 확정 전 초안",11)
	titles.add_child(date_label)
	seal = Seal.new()
	header.add_child(seal)
	seal.modulate.a = 0
	source_label = _label(Record.LIVE_SOURCE,11)
	page.add_child(source_label)
	_line(page)
	page.add_child(_label("작전 이름",12))
	title_input = LineEdit.new()
	title_input.max_length = 80
	title_input.custom_minimum_size.y = 38
	_skin_edit(title_input)
	page.add_child(title_input)
	title_input.text_changed.connect(func(_value: String) -> void: _changed())
	page.add_child(_label("Ⅰ  병력 배치 · 목표 비중",16))
	grid = GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation",14)
	grid.add_theme_constant_override("v_separation",8)
	page.add_child(grid)
	summary = _label("",13)
	page.add_child(summary)
	_line(page)
	page.add_child(_label("Ⅱ  판단 근거",16))
	rationale_input = _text_area("이 비중을 정한 이유와 확인한 근거를 적으세요.")
	page.add_child(rationale_input)
	page.add_child(_label("Ⅲ  주요 위험 · 다시 확인할 조건",16))
	risk_input = _text_area("판단이 틀릴 수 있는 이유와 다음에 확인할 조건을 적으세요.")
	page.add_child(risk_input)
	page.add_child(_label("확정 시점의 모의 계획을 기록합니다. 수수료·세금·체결 오차는 포함하지 않습니다.",11))

func _label(text: String, font_size: int) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_color_override("font_color",INK)
	label.add_theme_font_size_override("font_size",font_size)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label

func _line(parent: Node) -> void:
	var line := ColorRect.new()
	line.color = Color("a78b5e")
	line.custom_minimum_size.y = 1
	parent.add_child(line)

func _skin_edit(control: Control) -> void:
	control.add_theme_stylebox_override("normal",T.style(Color("e7d7b6"),Color("a58a61"),2,8))
	control.add_theme_stylebox_override("read_only",T.style(Color("dfcda9"),Color("b29a72"),2,8))
	control.add_theme_stylebox_override("focus",T.style(Color("ecdfc5"),Color("79592e"),2,8))
	control.add_theme_color_override("font_color",INK)
	control.add_theme_color_override("font_uneditable_color",INK)
	control.add_theme_color_override("font_readonly_color",INK)
	control.add_theme_color_override("font_placeholder_color",Color("806c50"))
	control.add_theme_color_override("caret_color",INK)
	control.add_theme_color_override("selection_color",Color("bdac86"))

func _text_area(placeholder: String) -> TextEdit:
	var edit := TextEdit.new()
	edit.placeholder_text = placeholder
	edit.custom_minimum_size.y = 100
	edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	edit.text_changed.connect(_changed)
	_skin_edit(edit)
	return edit

func get_draft() -> Dictionary:
	return {"title":title_input.text,"rationale":rationale_input.text,"risk":risk_input.text}

func _changed() -> void:
	if not _updating:
		draft_changed.emit(get_draft())

func display(plan: Dictionary, draft: Dictionary, recorded := false) -> void:
	_updating = true
	source_label.text = str(plan.get("source",Record.LIVE_SOURCE))
	if plan.get("source")==Record.LIVE_SOURCE:
		source_label.text += "\n조회: "+str(plan.observed_at)+"\n"+str(plan.cash_basis)+" · 계좌 전체 순자산과 다른 계산 범위"
	if is_instance_valid(_seal_tween):
		_seal_tween.kill()
	title_input.text = draft.title
	rationale_input.text = draft.rationale
	risk_input.text = draft.risk
	title_input.editable = not recorded
	rationale_input.editable = not recorded
	risk_input.editable = not recorded
	heading.text = "작전 기록" if recorded else "작전 명령서"
	date_label.text = Record.dated_label(plan) if recorded else "작성 중 · 확정 전 초안"
	seal.modulate.a = 1.0 if recorded else 0.0
	seal.scale = Vector2.ONE
	seal.rotation = -0.10 if recorded else 0.0
	for child: Node in grid.get_children():
		grid.remove_child(child)
		child.queue_free()
	for caption: String in ["종목","보유 → 계획","모의 매매","목표"]:
		grid.add_child(_label(caption,11))
	for row: Dictionary in plan.rows:
		var action := "유지" if row.delta == 0 else ("매수" if row.delta > 0 else "매도")
		for cell: String in [row.name+"\n"+row.code,"%d → %d주" % [row.quantity,row.result_quantity],"%s %d주\n%s원/주" % [action,absi(int(row.delta)),Data.money(row.price)],"%.1f%%" % row.target]:
			grid.add_child(_label(cell,12))
	summary.text = "기준 자산  %s원  ·  목표 주식 %.1f%%\n계획 후 현금  %s원" % [Data.money(plan.base_assets),plan.target_total,Data.money(plan.planned_cash)]
	scroll.scroll_vertical = 0
	_updating = false

func stamp() -> void:
	scroll.scroll_vertical = 0
	seal.pivot_offset = seal.size*0.5
	seal.scale = Vector2.ONE*1.7
	seal.rotation = -0.28
	seal.modulate.a = 0.0
	_seal_tween = create_tween().set_parallel(true)
	_seal_tween.tween_property(seal,"scale",Vector2.ONE,0.4).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	_seal_tween.tween_property(seal,"rotation",-0.10,0.3)
	_seal_tween.tween_property(seal,"modulate:a",1.0,0.18)

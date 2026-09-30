extends SceneTree
## Separate NH quote columns and bounded manual refresh on synthetic rows only.
const Groups = preload("res://scripts/watchlist_groups.gd")
const TablePanel = preload("res://scripts/watchlist_table_panel.gd")
const TableData = preload("res://scripts/watchlist_table_data.gd")

var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func frames(count := 3) -> void:
	for index: int in count:
		await process_frame

func row(code: String, name: String, price: Variant = null, quote_time := "") -> Dictionary:
	return {"code":code,"name":name,"market":"KOSPI","kind":"보통주","held":false,"status":"일봉 미조회",
		"status_reason":"일봉과 구분","identity_conflict":false,"price":price,
		"quote_source":"NH투자증권 NHPLUG" if price != null else "","quote_time":quote_time,
		"quote_status":"조회됨" if price != null else "미조회","quote_reason":"수동 조회" if price != null else ""}

func tree_item(panel: Control, code: String) -> TreeItem:
	var item: TreeItem = panel.table.get_root().get_first_child() if panel.table.get_root()!=null else null
	while item != null:
		if str(item.get_metadata(0)) == code:
			return item
		item = item.get_next()
	return null

func run() -> void:
	root.size = Vector2i(1280,720)
	var model := Groups.new()
	var rows: Array = []
	var watched: Array = []
	for index: int in 25:
		var code := "%06d" % (300000 + index)
		rows.append(row(code,"검증 종목 %02d" % index,1200 if index==0 else null,"2026-09-30 21:10" if index==0 else ""))
		watched.append(code)
	rows[1].identity_conflict = true
	rows[1].price = 9900
	rows[1].quote_status = "조회됨"
	rows.append(row("ABC123","지원 밖 종목"))
	watched.append("ABC123")
	var panel: Control = TablePanel.new()
	root.add_child(panel)
	await frames()
	panel.set_model(model)
	panel.set_rows(rows,watched,"300000")
	panel.open()
	await frames()
	check(panel.table.columns==10 and panel.table.get_column_title(4)=="보유" and panel.table.get_column_title(5)=="일봉 상태","Original six columns remain in place with four quote columns appended")
	var first: TreeItem = tree_item(panel,"300000")
	check(first!=null and first.get_text(6)=="1,200원" and first.get_text(7)=="NH · KRX" and first.get_text(8)=="2026-09-30 21:10" and first.get_text(9)=="조회됨","Price, source, observation time and quote state are visible on the row")
	check(first.get_tooltip_text(6).contains("NH투자증권 NHPLUG") and first.get_tooltip_text(6).contains("수동 조회"),"Row tooltip retains full source and quote reason")
	var conflict: TreeItem = tree_item(panel,"300001")
	check(conflict!=null and conflict.get_text(6)=="—" and conflict.get_text(9)=="식별자 확인","Identity conflict never paints a stale quote")
	check(tree_item(panel,"300002").get_text(6)=="—" and tree_item(panel,"300002").get_text(9)=="미조회","Missing quote does not invent a price")
	for dimensions: Vector2i in [Vector2i(1280,720),Vector2i(1440,960)]:
		root.size = dimensions
		await frames()
		var card: Rect2 = panel.card.get_global_rect()
		var last_cell: Rect2 = panel.table.get_item_area_rect(tree_item(panel,"300000"),9)
		check(card.position.x>=0 and card.end.x<=dimensions.x+1 and panel.table.get_global_rect().position.x+last_cell.end.x<=card.end.x+1,"All quote columns fit viewport "+str(dimensions))
	model.set_sort("price",true)
	var sorted: Array = model.rows_for(rows,watched)
	check(sorted[0].code=="300000" and sorted[-1].price==null,"Numeric price sorting puts missing prices last ascending")
	rows[2].price = 25
	rows[3].price = 100
	rows[2].quote_time = "2026-09-29 11:00:00"
	rows[3].quote_time = "2026-10-01 09:00:00"
	model.set_sort("price",true)
	sorted = model.rows_for(rows,watched)
	check(sorted[0].code=="300002" and sorted[1].code=="300003" and sorted[2].code=="300000","Prices sort numerically instead of lexicographically")
	model.set_sort("price",false)
	sorted = model.rows_for(rows,watched)
	check(sorted[0].code=="300001" and sorted[-1].price==null,"Descending price also leaves missing values last")
	model.set_sort("quote_time",true)
	sorted = model.rows_for(rows,watched)
	check(sorted[0].code=="300002" and sorted[2].code=="300003" and sorted[-1].quote_time.is_empty(),"Observation times sort chronologically with missing times last")
	model.set_sort("quote_time",false)
	sorted = model.rows_for(rows,watched)
	check(sorted[0].code=="300003" and sorted[-1].quote_time.is_empty(),"Descending observation time also leaves missing values last")
	check(Groups.validate_state(model.export_state()) and model.export_state().sort.column=="quote_time" and Groups.validate_state(Groups.defaults()),"New sort keys fit unchanged v3 preference schema and old defaults")
	panel.set_rows(rows,watched,"300000")
	panel.table.column_title_clicked.emit(6,MOUSE_BUTTON_LEFT)
	check(model.sort_column=="price" and tree_item(panel,"300002")==panel.table.get_root().get_first_child(),"Price header applies numeric order to the rendered Tree")
	panel.table.column_title_clicked.emit(8,MOUSE_BUTTON_LEFT)
	check(model.sort_column=="quote_time" and tree_item(panel,"300002")==panel.table.get_root().get_first_child(),"Receive-time header applies chronological order to the rendered Tree")
	model.set_sort("name",true)
	var requests: Array = []
	var cancellations: Array = []
	panel.quotes_refresh_requested.connect(func(codes: Array) -> void: requests.append(codes.duplicate()))
	panel.quotes_cancel_requested.connect(func() -> void: cancellations.append(true))
	panel.quotes_refresh_button.pressed.emit()
	check(requests.size()==1 and requests[0].size()==20 and requests[0][0]=="300000" and requests[0][-1]=="300020","Manual refresh sends first 20 eligible visible codes in table order")
	check(not "300001" in requests[0] and not "ABC123" in requests[0] and panel.quote_busy and panel.quotes_refresh_button.disabled and not panel.quotes_cancel_button.disabled,"Conflict and unsupported code are excluded while refresh is busy")
	panel.set_quote_progress(true,"7/20 완료")
	check(panel.quote_progress_label.text=="7/20 완료","Progress summary is shown without automatic quote requests")
	panel.close()
	check(cancellations.size()==1 and not panel.visible,"Closing table cancels active refresh once")
	panel.set_quote_progress(false,"중단됨")
	panel.open()
	var group_id: String = model.create_group("범위 전환")
	model.add_code(group_id,"300000")
	panel.quotes_refresh_button.pressed.emit()
	check(requests.size()==2,"A later manual refresh can start after cancellation")
	model.select_group(group_id)
	check(cancellations.size()==2 and panel.visible,"Group transition cancels active refresh without closing the table")
	panel.set_quote_progress(false,"중단됨")
	model.select_group("all")
	panel.filter_edit.text = "300024"
	panel._filter_changed("300024")
	check(panel.selected_code=="300000" and panel.visible_order==["300024"],"Text filtering preserves selected code while limiting refresh scope")
	panel.quotes_refresh_button.pressed.emit()
	check(requests.size()==3 and requests[2]==["300024"],"Filtered refresh requests only the visible eligible row")
	panel.set_quote_progress(false,"완료")
	panel.queue_free()
	await frames()
	var mismatched: Array = TableData.build([{"code":"005930","name":"삼성전자"}],{},null,[{"code":"005930","name":"다른 이름","market":"KOSPI","kind":"보통주"}])
	check(mismatched.size()==1 and mismatched[0].identity_conflict and mismatched[0].quote_status=="식별자 확인" and mismatched[0].price==null,"Catalogue name mismatch blocks quote identity")
	var duplicated: Array = TableData.build([{"code":"005930","name":"삼성전자"}],{},null,[{"code":"005930","name":"삼성전자"},{"code":"005930","name":"삼성전자"}])
	check(duplicated[0].identity_conflict and duplicated[0].status_reason.contains("중복"),"Duplicate catalogue identifier remains unresolved")
	print("WATCHLIST_QUOTE_TABLE_TEST: %s (%d checks)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

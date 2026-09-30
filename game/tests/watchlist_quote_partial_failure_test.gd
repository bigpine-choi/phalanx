extends SceneTree
## One isolated manual batch: two fresh NH prices and one failed refresh with a cached price.

class FakeProcess extends Node:
	signal completed(code: String, token: int, envelope: Dictionary)
	var requests: Array = []

	func request(code: String, token: int) -> void:
		requests.append({"code":code,"token":token})

	func deliver(index: int, envelope: Dictionary) -> void:
		completed.emit(requests[index].code,requests[index].token,envelope)

var checks := 0
var failures := 0
var directory := ""

func _initialize() -> void:
	directory = OS.get_environment("TEMP").path_join("phalanx-nh-partial-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	DirAccess.make_dir_recursive_absolute(directory)
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE","PHALANX_NH_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("profile.json"))
	OS.set_environment("PHALANX_CATALOG_CACHE",directory.path_join("catalog.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	OS.set_environment("PHALANX_NH_QUOTE_CACHE",directory.path_join("nh-quotes"))
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func payload(code: String, price: int, stamp: int) -> Dictionary:
	return {"provider":"NHPLUG","code":code,"market":"KRX","currency":"KRW","price":price,"fetched_at":stamp}

func row_for(rows: Array, code: String) -> Dictionary:
	for row: Dictionary in rows:
		if row.code==code:
			return row
	return {}

func tree_item(panel: Control, code: String) -> TreeItem:
	var item: TreeItem = panel.table.get_root().get_first_child() if panel.table.get_root()!=null else null
	while item!=null:
		if str(item.get_metadata(0))==code:
			return item
		item = item.get_next()
	return null

func run() -> void:
	var cache_dir := directory.path_join("nh-quotes")
	var cached_stamp := int(Time.get_unix_time_from_system())-30
	var cache_path := cache_dir.path_join("quotes.json")
	check(DirAccess.make_dir_recursive_absolute(cache_dir)==OK,"Isolated NH cache directory created")
	var cache_file := FileAccess.open(cache_path,FileAccess.WRITE)
	if cache_file==null:
		push_error("Could not seed isolated public quote cache")
		quit(1)
		return
	cache_file.store_string(JSON.stringify({"version":1,"quotes":[payload("005380",333000,cached_stamp)]}))
	cache_file.close()
	root.size = Vector2i(1280,720)
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	root.add_child(view)
	for index: int in 6:
		await process_frame
	var gateway: Node = view.research_view.nh_quotes
	var old_quote: Dictionary = gateway.quote_for("005380")
	var old_time: String = gateway.row_fields("005380").quote_time
	check(old_quote.get("price")==333000 and old_quote.get("fetched_at")==cached_stamp and gateway.row_fields("005380").quote_status=="저장된 시세","Third stock starts with a separately cached price and receipt time")
	var original_process: Node = gateway.process
	var fake := FakeProcess.new()
	gateway.add_child(fake)
	gateway.process = fake
	fake.completed.connect(gateway._completed)
	check(gateway.process==fake and original_process.pid<0,"Fake process replaces the request path before enabling batch calls")
	OS.set_environment("PHALANX_NH_OFFLINE","0")
	view.watch_groups.set_sort("price",false)
	view._table_security_selected("005380")
	view._open_watch_table()
	var panel: Control = view.watch_table
	check(panel.selected_code=="005380" and panel.visible_order[0]=="005380","Cached stock is selected before price-sort rebuilds")
	check(gateway.refresh(["005930","000660","005380"]) and fake.requests.size()==1 and fake.requests[0].code=="005930","Exactly three ordered codes start a manual batch")
	var now := int(Time.get_unix_time_from_system())
	fake.deliver(0,{"ok":true,"payload":payload("005930",444000,now)})
	gateway._next_start_msec = 0
	gateway._kick()
	check(fake.requests.size()==2 and fake.requests[1].code=="000660","Second stock waits for its queue turn")
	fake.deliver(1,{"ok":true,"payload":payload("000660",555000,now)})
	gateway._next_start_msec = 0
	gateway._kick()
	check(fake.requests.size()==3 and fake.requests[2].code=="005380","Previously cached stock runs third")
	fake.deliver(2,{"ok":false,"error":"NH_READ_FAILED"})
	check(not gateway.busy and gateway.summary.contains("성공 2개") and gateway.summary.contains("실패 1개") and fake.requests.size()==3,"Batch finishes with two successes and one failure only")
	var rows: Array = view._table_rows()
	var first: Dictionary = row_for(rows,"005930")
	var second: Dictionary = row_for(rows,"000660")
	var failed: Dictionary = row_for(rows,"005380")
	check(first.price==444000 and second.price==555000 and first.quote_status=="조회 완료" and second.quote_status=="조회 완료","Two successful rows display their fresh prices")
	check(failed.price==333000 and failed.quote_time==old_time and failed.quote_source=="NH · KRX" and failed.quote_status.contains("갱신 실패"),"Failed refresh retains the old price and time alongside failure status")
	check(gateway.quote_for("005380").fetched_at==cached_stamp and failed.quote_reason.contains("이전 정상 가격"),"Failure leaves cached receipt timestamp unchanged and explains stale value")
	var failed_item: TreeItem = tree_item(panel,"005380")
	check(failed_item!=null and failed_item.get_text(6)=="333,000원" and failed_item.get_text(8)==old_time and failed_item.get_text(9).contains("갱신 실패"),"Tree shows old price, old time and failure state in the same row")
	check(panel.visible_order.slice(0,3)==["000660","005930","005380"] and panel.selected_code=="005380" and str(panel.table.get_selected().get_metadata(0))=="005380","Numeric reordering and repeated Tree rebuilds preserve selection by code")
	check(original_process.pid<0,"No WSL or NH network process was started")
	panel.close()
	view.queue_free()
	await process_frame
	print("WATCHLIST_QUOTE_PARTIAL_FAILURE_TEST: %s (%d checks; isolated cache, fake process)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

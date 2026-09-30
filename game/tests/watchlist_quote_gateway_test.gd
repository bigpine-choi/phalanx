extends SceneTree
## Offline NH batch, cache, and stale-response behavior with a fake process.

const Gateway = preload("res://scripts/watchlist_quote_gateway.gd")
const Model = preload("res://scripts/nhplug_quote_model.gd")

class FakeProcess extends Node:
	signal completed(code: String, token: int, envelope: Dictionary)
	var requests: Array = []

	func request(code: String, token: int) -> void:
		requests.append({"code":code,"token":token,"started":Time.get_ticks_msec()})

	func deliver(index: int, envelope: Dictionary) -> void:
		completed.emit(requests[index].code, requests[index].token, envelope)


var checks := 0
var failures := 0


func _initialize() -> void:
	OS.set_environment("PHALANX_NH_OFFLINE", "0")
	call_deferred("run")


func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)


func payload(code: String, price: int, stamp: int) -> Dictionary:
	return {"provider":"NHPLUG","code":code,"market":"KRX","currency":"KRW",
		"price":price,"fetched_at":stamp}


func pause() -> void:
	await create_timer(0.45).timeout


func run() -> void:
	var now := int(Time.get_unix_time_from_system())
	var json_payload: Variant = JSON.parse_string(JSON.stringify(payload("005930", 231000, now)))
	check(Model.parse(json_payload, "005930", now).get("price") == 231000, "Godot JSON numeric quote crosses Python boundary")
	check(Model.parse_cached(payload("005930", 220000, now - 86400), "005930", now).get("price") == 220000, "Old valid quote may be restored")
	check(Model.parse_cached(payload("005930", 220000, now + 120), "005930", now).is_empty(), "Future cache timestamp rejected")

	var directory := OS.get_environment("TEMP").path_join("phalanx-nh-gateway-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()])
	var gateway: Node = Gateway.new()
	gateway.cache_dir = directory
	gateway.process = FakeProcess.new()
	root.add_child(gateway)
	await process_frame
	var fake: FakeProcess = gateway.process
	check(gateway.refresh(["005930", "000660", "005930", "BAD"]), "Mixed request starts")
	check(fake.requests.size() == 1 and fake.requests[0].code == "005930", "Deduplicated FIFO starts one process")
	check(not gateway.refresh(["005930"]), "Duplicate batch suppressed while busy")
	var first: Dictionary = fake.requests[0]
	fake.deliver(0, {"ok":true,"payload":json_payload})
	check(gateway.quote_for("005930").get("price") == 231000, "First public quote accepted")
	check(fake.requests.size() == 1, "Second request waits for 300 ms interval")
	await pause()
	check(fake.requests.size() == 2 and fake.requests[1].code == "000660", "Second unique code starts in FIFO order")
	if fake.requests.size() < 2:
		quit(1)
		return
	check(int(fake.requests[1].started) - int(first.started) >= 300, "Provider calls are at least 300 ms apart")
	fake.deliver(1, {"ok":false,"error":"NH_READ_FAILED"})
	check(not gateway.busy and gateway.row_fields("000660").quote_status == "조회 실패", "Failed code does not masquerade as priced")
	check(gateway.row_fields("BAD").quote_status == "미지원", "Unsupported code has explicit status")
	check(gateway.row_fields("005930").quote_time.length() == 19, "Display time is fixed KST date and time")
	check(gateway.row_fields("005930").quote_reason.contains("수신 시각"), "Receipt time is not labeled as exchange observation")

	check(gateway.refresh(["005930"]), "Manual retry starts")
	await pause()
	check(fake.requests.size() == 3, "Retry honors interval")
	fake.deliver(2, {"ok":false,"error":"NH_READ_FAILED"})
	check(gateway.row_fields("005930").price == 231000 and gateway.row_fields("005930").quote_status.contains("이전 시세"), "Failure retains prior price and receipt time")
	check(gateway.quote_for("005930").fetched_at == now, "Failed refresh does not advance receipt time")

	check(gateway.refresh(["005930", "000660"]), "Cancellable batch starts")
	await pause()
	check(fake.requests.size() == 4, "Active code starts before cancellation")
	gateway.cancel()
	fake.deliver(3, {"ok":true,"payload":payload("005930", 232000, int(Time.get_unix_time_from_system()))})
	check(not gateway.busy and fake.requests.size() == 4, "Cancel accepts active response and stops queued codes")
	check(gateway.quote_for("005930").price == 232000, "Active response is retained after cancel")

	check(gateway.refresh(["005930"]), "New batch starts after cancellation")
	await pause()
	check(fake.requests.size() == 5, "New batch waits for interval")
	var current_token: int = fake.requests[4].token
	fake.completed.emit("005930", first.token, {"ok":true,"payload":payload("005930", 1, now)})
	check(gateway.busy and gateway.quote_for("005930").price == 232000, "Late response from prior token is ignored")
	fake.completed.emit("005930", current_token, {"ok":false,"error":"NH_READ_FAILED"})
	check(not gateway.busy, "Current response finishes batch")

	gateway.queue_free()
	await process_frame
	var restored: Node = Gateway.new()
	restored.cache_dir = directory
	restored.process = FakeProcess.new()
	root.add_child(restored)
	await process_frame
	check(restored.quote_for("005930").price == 232000 and restored.row_fields("005930").quote_status == "저장된 시세", "Fresh gateway restores separate quote cache")
	restored.queue_free()
	await process_frame

	var invalid_directory := directory.path_join("corrupt")
	DirAccess.make_dir_recursive_absolute(invalid_directory)
	var file := FileAccess.open(invalid_directory.path_join("quotes.json"), FileAccess.WRITE)
	file.store_string("{broken")
	file.close()
	var invalid: Node = Gateway.new()
	invalid.cache_dir = invalid_directory
	invalid.process = FakeProcess.new()
	root.add_child(invalid)
	await process_frame
	check(invalid.quote_for("005930").is_empty() and invalid.summary.contains("읽지 못했습니다"), "Corrupt cache rejected without a price")
	invalid.queue_free()
	await process_frame
	var saved_directory := directory.path_join("old")
	DirAccess.make_dir_recursive_absolute(saved_directory)
	var saved_file := FileAccess.open(saved_directory.path_join("quotes.json"), FileAccess.WRITE)
	saved_file.store_string(JSON.stringify({"version":1,"quotes":[payload("005930", 220000, now - 86400)]}))
	saved_file.close()
	var old: Node = Gateway.new()
	old.cache_dir = saved_directory
	old.process = FakeProcess.new()
	root.add_child(old)
	await process_frame
	check(old.quote_for("005930").price == 220000 and old.row_fields("005930").quote_status == "오래된 시세", "Old cache restores with explicit age")
	old.queue_free()
	await process_frame
	var future_directory := directory.path_join("future")
	DirAccess.make_dir_recursive_absolute(future_directory)
	var future_file := FileAccess.open(future_directory.path_join("quotes.json"), FileAccess.WRITE)
	future_file.store_string(JSON.stringify({"version":1,"quotes":[payload("005930", 220000, now + 120)]}))
	future_file.close()
	var future: Node = Gateway.new()
	future.cache_dir = future_directory
	future.process = FakeProcess.new()
	root.add_child(future)
	await process_frame
	check(future.quote_for("005930").is_empty() and future.summary.contains("읽지 못했습니다"), "Future dated cache rejected at disk boundary")
	future.queue_free()
	await process_frame
	var capped: Node = Gateway.new()
	capped.cache_dir = directory.path_join("capped")
	capped.process = FakeProcess.new()
	root.add_child(capped)
	await process_frame
	var many: Array = []
	for index: int in 21:
		many.append("%06d" % (300000 + index))
	check(capped.refresh(many) and capped._queue.size() == 19, "Batch accepts only first 20 unique codes")
	capped.cancel()
	var capped_process: FakeProcess = capped.process
	capped_process.deliver(0, {"ok":false,"error":"NH_READ_FAILED"})
	check(capped.summary.contains("20개 초과 1개 제외") and capped_process.requests.size() == 1, "Excess code remains unrequested and is reported")
	capped.queue_free()
	await process_frame

	print("PHALANX_WATCHLIST_QUOTE_GATEWAY_TEST: %s (%d checks)" % ["PASS" if failures == 0 else "FAIL", checks])
	quit(0 if failures == 0 else 1)

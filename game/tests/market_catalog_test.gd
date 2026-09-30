extends SceneTree
const Catalog = preload("res://scripts/market_catalog.gd")
const CatalogProcess = preload("res://scripts/catalog_process.gd")

class FakeProcess extends Node:
	var active: Dictionary = {}
	var requests: Array = []
	func request(action: String) -> bool:
		if not active.is_empty():
			return false
		active = {"action":action}
		requests.append(action)
		return true

var checks := 0
var failures := 0

func _initialize() -> void:
	OS.set_environment("PHALANX_CATALOG_OFFLINE", "1")
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func row(code: String, name: String, kind := "보통주") -> Dictionary:
	return {"code":code,"name":name,"market":"KOSPI","kind":kind,"source":"fixture","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""}

func run() -> void:
	var valid_envelope := {"request_id":"request-1","ok":true,"payload":{"state":"empty","items":[]}}
	check(CatalogProcess._validated_envelope(valid_envelope,"request-1").ok == true, "Connector accepts matching request identity")
	check(CatalogProcess._validated_envelope(valid_envelope,"request-2").get("error") == "BRIDGE_FAILED", "Connector rejects another request's output")
	check(CatalogProcess._validated_envelope({"request_id":"request-1","ok":true,"payload":null},"request-1").get("error") == "BRIDGE_FAILED", "Connector rejects malformed success payload")
	check(CatalogProcess._validated_envelope({"request_id":"request-1","ok":false,"payload":{}},"request-1").get("error") == "BRIDGE_FAILED", "Connector rejects failure without an error code")
	var cache := OS.get_environment("TEMP").path_join("phalanx-catalog-test-"+str(OS.get_process_id())+".json")
	var model := Catalog.new()
	model.cache_path = cache
	root.add_child(model)
	check(model.state == "empty" and model.items.is_empty(), "First run has distinct no-data state")
	check(model.search("삼성").total == 0, "Search on empty cache is empty")
	model.refresh()
	check(model.state == "error" and model.items.is_empty(), "First refresh failure has no fake data")
	var payload := {"state":"ready","source":"fixture","collected_at":"2026-09-30T00:00:00+00:00","items":[row("005930","삼성전자"),row("069500","KODEX 200","ETF"),row("005935","삼성전자우","우선주"),row("US-ABC1","테스트 해외종목"),row("111111","충돌 A"),row("111111","충돌 B")],"collisions":[]}
	check(model.accept_snapshot(payload, true), "Valid snapshot accepted and cached")
	check(model.state == "ready" and model.items.size() == 6, "Catalogue includes ETF and preferred")
	check(model.search("삼성").total == 2 and model.search("005935").items[0].name == "삼성전자우", "Korean name and code search")
	check(model.search("ETF").total == 1 and model.search("zzzz").total == 0, "Kind search and genuine zero results")
	check(model.search("", 2).items.size() == 2 and model.search("", 2).truncated, "Visible results capped")
	check(Catalog.can_register(model.search("069500").items[0]), "ETF is registerable")
	check(Catalog.can_register(model.search("005935").items[0]), "Preferred is registerable")
	check(not Catalog.can_register(model.search("111111").items[0]) and model.search("111111").items[0].collision, "Duplicate identifier is blocked")
	check(model.collisions.size() == 1 and model.collisions[0].code == "111111", "Duplicate identifier is reported")
	check(not Catalog.can_register(model.search("US-ABC1").items[0]), "Unsupported identifier cannot be persisted")
	check(not Catalog.chart_support(model.search("US-ABC1").items[0]).supported, "Chart support range has a reason")
	var newer: Dictionary = payload.duplicate(true)
	newer.collected_at = "2026-10-01T00:00:00+00:00"
	check(model.accept_snapshot(newer, true), "New successful snapshot replaces cache")
	var old_stamp: String = model.collected_at
	var old_items := model.items.duplicate(true)
	var malformed: Dictionary = newer.duplicate(true)
	malformed.items[0].source = ""
	model._completed("refresh", {"ok":true,"payload":malformed})
	check(model.state == "stale" and model.collected_at == old_stamp and model.items == old_items, "Malformed success cannot replace a valid cached catalogue")
	model._completed("refresh", {"ok":false,"error":"REFRESH_FAILED","payload":{"state":"empty","items":[]}})
	check(model.state == "stale" and model.collected_at == old_stamp and model.items == old_items, "Failed refresh retains prior list and collection time")
	var older: Dictionary = payload.duplicate(true)
	older.collected_at = "2025-01-01T00:00:00+00:00"
	model._completed("refresh", {"ok":false,"error":"REFRESH_FAILED","payload":older})
	check(model.state == "stale" and model.collected_at == old_stamp and model.items == old_items, "Failed refresh cannot replace prior list with bridge fallback")
	var fallback_cache := cache + ".fallback"
	var fallback := Catalog.new()
	fallback.cache_path = fallback_cache
	root.add_child(fallback)
	fallback._completed("load", {"ok":false,"error":"BRIDGE_FAILED","payload":payload})
	check(fallback.state == "error" and fallback.items.is_empty(), "Untrusted failure envelope cannot install a snapshot")
	fallback._completed("load", {"ok":false,"error":"REFRESH_FAILED","payload":{"state":"empty","items":[]}})
	check(fallback.state == "error" and fallback.message.contains("최근 목록 갱신 실패") and fallback.message.contains("최초 정상 목록"), "Failed first collection is distinguished from a bridge read failure")
	fallback._completed("load", {"ok":false,"error":"REFRESH_FAILED","payload":payload})
	check(fallback.state == "stale" and fallback.items.size() == 6, "Previous Python snapshot survives its failed latest refresh")
	fallback.queue_free()
	var fake := FakeProcess.new()
	model.add_child(fake)
	model.process = fake
	OS.set_environment("PHALANX_CATALOG_OFFLINE", "0")
	fake.active = {"action":"load"}
	model.refresh()
	model.refresh()
	check(model._pending_refresh and fake.requests.is_empty(), "Refresh during load queues exactly one refresh")
	fake.active = {}
	model._completed("load", {"ok":true,"payload":newer})
	check(fake.requests == ["refresh"] and fake.active.action == "refresh" and not model._pending_refresh, "Queued refresh starts after load")
	model.refresh()
	check(fake.requests == ["refresh"] and not model._pending_refresh, "Duplicate refresh is coalesced while refresh is active")
	fake.active = {}
	model._completed("refresh", {"ok":false,"error":"BRIDGE_FAILED"})
	check(model.state == "stale" and not model._pending_refresh, "Failed in-flight refresh does not leave a pending request")
	OS.set_environment("PHALANX_CATALOG_OFFLINE", "1")
	var replay := Catalog.new()
	replay.cache_path = cache
	root.add_child(replay)
	check(replay.state == "ready" and replay.items.size() == 6 and replay.collected_at == old_stamp, "Separate model reloads cache")
	check(not Catalog.can_register(replay.search("111111").items[0]), "Collision block survives cache reload")
	replay.queue_free()
	model.queue_free()
	await process_frame
	if FileAccess.file_exists(cache):
		DirAccess.remove_absolute(cache)
	if FileAccess.file_exists(fallback_cache):
		DirAccess.remove_absolute(fallback_cache)
	print("MARKET_CATALOG_TEST ", checks, " checks, ", failures, " failures")
	quit(1 if failures else 0)

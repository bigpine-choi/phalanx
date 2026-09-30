extends SceneTree
## Opt-in integration check: stored POSIX discovery view via the Windows WSL connector.
const Catalog = preload("res://scripts/market_catalog.gd")

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	OS.set_environment("PHALANX_CATALOG_OFFLINE", "0")
	var cache := OS.get_environment("TEMP").path_join("phalanx-catalog-wsl-"+str(OS.get_process_id())+".json")
	var model := Catalog.new()
	model.cache_path = cache
	root.add_child(model)
	var deadline := Time.get_ticks_msec() + 30000
	while model.state == "loading" and Time.get_ticks_msec() < deadline:
		await process_frame
	var okay: bool = model.state == "ready" and model.items.size() > 1000 and not model.collected_at.is_empty() and model.search("ETF").total > 0 and model.search("우선주").total > 0
	if not okay:
		push_error("WSL stored catalogue load failed: " + model.state + " / " + model.message + " / items=" + str(model.items.size()))
	else:
		print("MARKET_CATALOG_WSL_TEST: PASS items=", model.items.size(), " ETF=", model.search("ETF").total, " preferred=", model.search("우선주").total, " collected_at=", model.collected_at)
	model.queue_free()
	await process_frame
	if FileAccess.file_exists(cache):
		DirAccess.remove_absolute(cache)
	quit(0 if okay else 1)

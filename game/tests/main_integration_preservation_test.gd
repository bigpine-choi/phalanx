extends "res://tests/research_data_test.gd"
## Integration must retain main's WSL conversion and bounded KIS cache.
const WslPath = preload("res://scripts/wsl_path.gd")

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-main-cache-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()]))
	call_deferred("run")

func run() -> void:
	check(WslPath.from_windows("C:\\Users\\review folder\\game\\tools\\nhplug_quote_bridge.py")=="/mnt/c/Users/review folder/game/tools/nhplug_quote_bridge.py","Windows backslash and spaces use the common WSL mapping")
	check(WslPath.from_windows("D:/review/data.json")=="/mnt/d/review/data.json","Forward-slash drive paths remain supported")
	check(WslPath.from_windows("relative.json").is_empty(),"Relative paths cannot become a WSL request")
	var gateway := Gateway.new()
	root.add_child(gateway)
	for index: int in 13:
		var code := "%06d" % (300000+index)
		var payload := sample()
		payload.code = code
		gateway.select_stock(code)
		gateway._kis_completed(code,gateway.generation,payload)
	check(gateway.memory_quotes.size()==12 and gateway.quote_cache_order.size()==12,"Thirteen successful histories retain the 12-security memory limit")
	check(not gateway.memory_quotes.has("300000") and gateway.memory_quotes.has("300012"),"Oldest memory history is evicted and newest remains")
	check(FileAccess.file_exists(gateway.cache_dir.path_join("kis_300000.json")),"Eviction preserves the disk history")
	gateway.select_stock("300000")
	check(gateway.quote.get("code")=="300000" and gateway.quote_state=="cached" and gateway.quote.candles.size()==2,"Evicted security restores from disk with its own identity")
	gateway.select_stock("300001")
	var payload := sample()
	payload.code = "300013"
	gateway.select_stock("300013")
	gateway._kis_completed("300013",gateway.generation,payload)
	check(gateway.memory_quotes.has("300001") and not gateway.memory_quotes.has("300002") and gateway.memory_quotes.size()==12,"Revisiting a cached security refreshes its recency before the next eviction")
	check(gateway.kis.pid<0,"Cache exercise does not launch a live KIS request")
	gateway.queue_free()
	await process_frame
	print("MAIN_INTEGRATION_PRESERVATION: %s (%d checks)" % ["PASS" if failures==0 else "FAIL",checks])
	quit(0 if failures==0 else 1)

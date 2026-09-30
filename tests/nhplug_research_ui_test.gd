extends SceneTree
## Shared NH gateway integration; synthetic prices and an isolated cache only.
const Research = preload("res://scripts/research_detail.gd")
const Quotes = preload("res://scripts/watchlist_quote_gateway.gd")
var failures := 0
var checks := 0

class FakeProcess extends Node:
	signal completed(code: String, token: int, envelope: Dictionary)
	var calls: Array = []
	func request(code: String, token: int) -> void:
		calls.append({"code":code,"token":token})
	func reply(price: int, ok := true) -> void:
		var call: Dictionary = calls[-1]
		var payload := {"provider":"NHPLUG","code":call.code,"market":"KRX","currency":"KRW","price":price,"fetched_at":int(Time.get_unix_time_from_system())}
		completed.emit(call.code,call.token,{"ok":true,"payload":payload} if ok else {"ok":false,"error":"NH_READ_FAILED"})

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	# NH transport is an injected in-memory fake; enable its queue, never WSL.
	OS.set_environment("PHALANX_NH_OFFLINE","0")
	var directory := OS.get_environment("TEMP").path_join("phalanx-nh-ui-%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	OS.set_environment("PHALANX_NH_QUOTE_CACHE",directory.path_join("nh"))
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func run() -> void:
	var runner := FakeProcess.new()
	var quotes := Quotes.new()
	quotes.process = runner
	var research := Research.new()
	research.nh_quotes = quotes
	root.add_child(research)
	research.select_security({"code":"005930","name":"삼성전자"})
	check(research.nh_button.text=="NH 현재가" and not research.nh_button.disabled,"Explicit NH action available")
	check(runner.calls.is_empty(),"Selection performs no NH request")
	research._fetch_nh()
	await create_timer(0.4).timeout
	check(runner.calls.size()==1 and research.nh_button.disabled,"Manual request uses shared gateway and blocks duplicates")
	research._fetch_nh()
	check(runner.calls.size()==1,"Repeated action cannot duplicate active request")
	research.select_security({"code":"000660","name":"SK하이닉스"})
	runner.reply(231000)
	await process_frame
	check("231,000" not in research.nh_status.text,"Late A response cannot paint selected B")
	check(quotes.quote_for("005930").get("price")==231000,"Late A response remains attached to A")
	research._fetch_nh()
	await create_timer(0.4).timeout
	runner.reply(410000)
	await process_frame
	check("410,000" in research.nh_status.text and "KIS 일봉과 별도" in research.nh_status.text,"Selected B quote names source and remains separate from KIS")
	var saved: Dictionary = quotes.quote_for("000660")
	research._fetch_nh()
	await create_timer(0.4).timeout
	runner.reply(0,false)
	await process_frame
	check(quotes.quote_for("000660")==saved and "410,000" in research.nh_status.text,"Failure preserves last successful B price and time")
	check("실패" in research.nh_status.text,"Failure remains visible next to retained quote")
	check(research.current_quote.is_empty(),"NH current price does not become KIS daily history")
	research.select_security({"code":"ABC123","name":"문자 코드"})
	check(research.nh_button.disabled,"Unsupported NH code is disabled")
	var before := runner.calls.size()
	research._fetch_nh()
	check(runner.calls.size()==before,"Unsupported direct action does not call NH")
	research.select_security({"code":"005930","name":"삼성전자","account_identity_conflict":"다른 이름"})
	research._fetch_nh()
	check(research.nh_button.disabled and "식별자" in research.nh_status.text and "231,000" not in research.nh_status.text,"Conflicting identity blocks lookup and cached quote display")
	check(runner.calls.size()==before,"Conflicting identity does not call NH")
	research.set_identity_conflict(true)
	check(research.gateway.quote_state=="unsupported" and research.chart.candles.is_empty(),"Identity conflict also clears and blocks KIS daily history")
	research.set_identity_conflict(false)
	check(research.gateway.unsupported_reason.is_empty(),"Resolved catalogue conflict restores the existing daily path")
	research.queue_free()
	await process_frame
	print("PHALANX_NHPLUG_UI_TEST: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

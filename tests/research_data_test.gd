extends SceneTree
const Model = preload("res://scripts/research_model.gd")
const Gateway = preload("res://scripts/research_gateway.gd")
var checks := 0
var failures := 0
var instant := 1790640000

func _initialize() -> void:
	OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	call_deferred("run")

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(label)

func sample() -> Dictionary:
	return {"provider":"KIS","code":"005930","currency":"KRW","market":"KRX","adjusted":true,"fetched_at":instant,"requested_start":"2026-09-01","requested_end":"2026-09-28","candles":[{"date":"2026-09-24","open":100.0,"high":110.0,"low":90.0,"close":105.0,"volume":123},{"date":"2026-09-25","open":105.0,"high":112.0,"low":102.0,"close":107.0,"volume":456}]}

func entry(id: String, name: String, sj: String, amount: String) -> Dictionary:
	return {"corp_code":"00126380","bsns_year":"2025","reprt_code":"11011","rcept_no":"20260310000001","currency":"KRW","account_id":id,"account_nm":name,"sj_div":sj,"thstrm_amount":amount}

func run() -> void:
	instant = Time.get_unix_time_from_datetime_string("2026-09-28T15:00:00")
	var valid := sample()
	var parsed := Model.parse_kis(valid,"005930",instant)
	check(parsed.get("candles",[]).size()==2,"Valid KIS OHLCV accepted")
	check(parsed.get("as_of")=="2026-09-25","Trading date preserved")
	check(parsed.get("source")=="한국투자증권 KIS","Provider retained")
	check(parsed.candles[1].volume==456,"Raw volume not pixel-scaled")
	for mutation: Array in [["provider","Yahoo"],["code","000660"],["currency","USD"],["market","NXT"],["adjusted",false],["fetched_at",instant+600],["requested_end","2026-09-29"],["requested_start","2026-10-01"]]:
		var bad := valid.duplicate(true)
		bad[mutation[0]] = mutation[1]
		check(Model.parse_kis(bad,"005930",instant).is_empty(),"Reject identity/basis/date mismatch: "+mutation[0])
	for mutation: Array in [["low",0],["high",89],["open",120],["close",80],["volume",-1],["volume",1.5],["close",null],["close","107"],["open",true],["date","2026-09-24"],["date","2026-10-01"],["date","2026-02-30"]]:
		var bad := valid.duplicate(true)
		bad.candles[1][mutation[0]] = mutation[1]
		check(Model.parse_kis(bad,"005930",instant).is_empty(),"Reject malformed OHLCV: "+str(mutation))
	check(Model.parse_kis(null,"005930",instant).is_empty(),"Null response is unavailable")
	check(Model.parse_kis(valid,"005380",instant).is_empty(),"Wrong selected security rejected")
	var bad := valid.duplicate(true)
	bad.candles = []
	check(Model.parse_kis(bad,"005930",instant).is_empty(),"Empty history is not synthesized")
	var statements := {"status":"000","list":[entry("ifrs-full_Revenue","매출액","IS","1,000"),entry("dart_OperatingIncomeLoss","영업이익","IS","(100)"),entry("ifrs-full_CashFlowsFromUsedInOperatingActivities","영업활동현금흐름","CF","200")]}
	var annual := Model.parse_dart(statements,"005930",2025)
	check(annual.revenue==1000 and annual.operating_profit==-100 and annual.operating_cash_flow==200,"Annual amounts and negative profit")
	check(Model.margin(annual)=="-10.0%","Margin uses same annual revenue")
	check(Model.trillion(null)=="자료 없음","Missing is not zero")
	check(Model.trillion(0)=="0.00조","Reported zero is zero")
	check(Model.margin({"revenue":0,"operating_profit":10})=="자료 없음","Zero revenue cannot divide")
	var missing := statements.duplicate(true)
	missing.list[1].thstrm_amount = "-"
	check(Model.parse_dart(missing,"005930",2025).operating_profit==null,"Unreported profit is null")
	for mutation: Array in [["bsns_year","2024"],["reprt_code","11012"],["corp_code","00164779"],["rcept_no","invalid"]]:
		var wrong := statements.duplicate(true)
		wrong.list[1][mutation[0]] = mutation[1]
		check(Model.parse_dart(wrong,"005930",2025).is_empty(),"Reject financial identity/period: "+mutation[0])
	check(Model.parse_dart({"status":"013"},"005930",2025).is_empty(),"No disclosure is unavailable")
	var ir := Model.official_snapshot("005930")
	check(ir.rows.size()==3 and ir.rows[0].year==2023 and ir.rows[2].year==2025,"Official annual coverage")
	check(ir.rows[2].revenue==333605938000000.0,"IR millions converted to won")
	check(ir.rows[2].operating_cash_flow==85315148000000.0,"Net operating cash flow used")
	check(ir.mode=="verified_snapshot","Fixed verified IR identified")
	check(Model.official_snapshot("000660").is_empty(),"No invented peer financials")
	var gateway := Gateway.new()
	gateway.cache_dir = OS.get_environment("TEMP").path_join("phalanx-data-test-"+str(OS.get_process_id()))
	root.add_child(gateway)
	gateway.select_stock("005930")
	check(gateway.quote.is_empty() and not gateway.financials.is_empty(),"First run separates no price from available IR")
	check(gateway._write_cache("kis_005930",{"code":"005930","fetched_at":instant,"payload":valid}),"Quote cache persisted")
	gateway.select_stock("000660")
	check(gateway.quote.is_empty() and gateway.financials.is_empty(),"Switch clears prior stock data")
	gateway.select_stock("005930")
	check(gateway.quote_state=="cached" and gateway.quote.candles.size()==2,"Same stock valid cache reload")
	gateway.refresh()
	check("오프라인" in gateway.quote_message and not gateway.quote.is_empty(),"Offline retains existing quote")
	gateway._quote_failed("연결 실패")
	check(gateway.quote_state=="stale" and gateway.quote.candles.size()==2,"Failure retains and labels old price")
	var token: int = gateway.generation
	gateway.quote_state = "loading"
	gateway.requested_codes["005930"] = true
	gateway.select_stock("000660")
	check(not gateway.requested_codes.has("005930"),"Interrupted stock remains eligible for automatic lookup on return")
	gateway._kis_completed("005930",token,valid)
	check(gateway.quote.is_empty() and gateway.code=="000660","Late reply never paints the next stock")
	gateway._quote_failed("실패")
	check(gateway.quote_state=="error" and gateway.quote.is_empty(),"First failure has no fake data")
	gateway._write_cache("kis_000660",{"code":"000660","fetched_at":instant,"payload":valid})
	check(gateway._read_quote_cache("000660").is_empty(),"Wrong stock inside cache rejected")
	gateway.select_stock("069500")
	check(gateway.financials.is_empty() and "ETF" in gateway.financial_message,"ETF financials not applicable")
	var blocker := gateway.cache_dir.path_join("blocker")
	var file := FileAccess.open(blocker,FileAccess.WRITE)
	file.store_string("test")
	file.close()
	gateway.cache_dir = blocker
	check(not gateway._write_cache("kis_005930",valid),"Cache failure reported")
	gateway.queue_free()
	await process_frame
	print("PHALANX_RESEARCH_DATA_TEST: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

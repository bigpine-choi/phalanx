extends SceneTree
## Prepare three public codes and synthetic daily bars for a normal F5 run.
## Does not make any network request; refuses to replace an existing profile.
const Store = preload("res://scripts/workspace_store.gd")
const Groups = preload("res://scripts/watchlist_groups.gd")
const Catalog = preload("res://scripts/market_catalog.gd")
const Research = preload("res://scripts/research_gateway.gd")
const Model = preload("res://scripts/research_model.gd")

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()!=1 or not args[0].is_absolute_path():
		quit(2)
		return
	var directory: String = args[0]
	var path := directory.path_join("profile.json")
	if FileAccess.file_exists(path):
		push_error("Use a new isolated directory; existing profiles are preserved")
		quit(2)
		return
	var codes: Array = ["005930","005935","069500"]
	var names := {"005930":"삼성전자","005935":"삼성전자우","069500":"KODEX 200"}
	var groups := Groups.new()
	var id := groups.create_group("NH 3종목 검증")
	var items: Array = []
	var now := int(Time.get_unix_time_from_system())
	var gateway := Research.new()
	gateway.cache_dir = directory.path_join("research")
	var success := true
	for code: String in codes:
		groups.add_code(id,code)
		items.append({"code":code,"name":names[code],"market":"KOSPI","kind":"ETF" if code=="069500" else ("우선주" if code=="005935" else "보통주"),"source":"격리 F5 검증 목록","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""})
		var candles: Array = []
		for index: int in 241:
			var date := Time.get_datetime_string_from_unix_time(now+9*3600-(242-index)*86400).left(10)
			var base := 80000.0+index*80.0+sin(index*0.12)*4000.0
			candles.append({"date":date,"open":base,"high":base+1000.0,"low":base-800.0,"close":base+sin(index)*650.0,"volume":100000+index*370})
		var payload := {"provider":"KIS","code":code,"currency":"KRW","market":"KRX","adjusted":true,"fetched_at":now,"requested_start":candles[0].date,"requested_end":candles[-1].date,"candles":candles}
		success = not Model.parse_kis(payload,code,now).is_empty() and success
		success = gateway._write_cache("kis_"+code,{"code":code,"fetched_at":now,"payload":payload}) and success
	groups.selected_group = id
	var store := Store.new(path)
	store.load_profile()
	success = store.save_profile(codes,{"005935":"격리 F5 검증 노트 · 합성 일봉"},{"security_names":names,"watchlist_view":groups.export_state()}) and success
	var catalog := Catalog.new()
	catalog.cache_path = directory.path_join("catalog.json")
	success = catalog.accept_snapshot({"state":"ready","source":"격리 F5 검증 목록","collected_at":"2026-09-30T00:00:00+00:00","items":items,"collisions":[]},true) and success
	catalog.free()
	gateway.free()
	print("F5_FIXTURE: ", "PASS" if success else "FAIL", "; exactly 3 codes; synthetic daily bars; NH cache empty; no network")
	quit(0 if success else 1)

extends SceneTree
## Native window review with synthetic metadata and an isolated persistent profile.
const Store = preload("res://scripts/workspace_store.gd")
const Groups = preload("res://scripts/watchlist_groups.gd")
const Data = preload("res://scripts/market_data.gd")

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()<2 or not args[1] in ["1280","1440"]:
		push_error("Expected an isolated absolute review directory and width 1280 or 1440")
		quit(1)
		return
	var directory: String = args[0]
	if not directory.is_absolute_path() or DirAccess.make_dir_recursive_absolute(directory)!=OK:
		push_error("Review directory must be an accessible absolute path")
		quit(1)
		return
	for key: String in ["PHALANX_ACCOUNT_OFFLINE","PHALANX_RESEARCH_OFFLINE","PHALANX_ADVISOR_OFFLINE","PHALANX_CATALOG_OFFLINE"]:
		OS.set_environment(key,"1")
	OS.set_environment("PHALANX_WORKSPACE_PATH",directory.path_join("review-profile.json"))
	OS.set_environment("PHALANX_CATALOG_CACHE",directory.path_join("review-catalog.json"))
	OS.set_environment("PHALANX_RESEARCH_CACHE",directory.path_join("research"))
	call_deferred("run",directory,args[1])

func fixture() -> Dictionary:
	var rows: Array = []
	for stock: Dictionary in Data.STOCKS:
		rows.append({"code":stock.code,"name":stock.name,"market":"KOSPI","kind":"ETF" if stock.code=="069500" else "보통주",
			"source":"격리 UI 검증","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""})
	for index: int in 55:
		var kind := "ETF" if index%9==0 else ("우선주" if index%7==0 else "보통주")
		rows.append({"code":"%06d" % (300000+index),"name":"검증 종목 %02d" % index,"market":"KOSDAQ" if index%2 else "KOSPI",
			"kind":kind,"source":"격리 UI 검증","collected_at":"2026-09-30T00:00:00+00:00","collision":false,"registration_supported":true,"reason":""})
	return {"state":"ready","source":"격리 UI 검증","collected_at":"2026-09-30T00:00:00+00:00","items":rows,"collisions":[]}

func seed_profile(path: String, items: Array) -> bool:
	if FileAccess.file_exists(path):
		return true
	var watched: Array = []
	var names := {}
	for security: Dictionary in items:
		watched.append(security.code)
		names[security.code] = security.name
	var groups := Groups.new()
	var growth: String = groups.create_group("기술 관찰")
	var income: String = groups.create_group("ETF · 우선주")
	for code: String in ["005930","000660","300001","300002"]:
		groups.add_code(growth,code)
	for code: String in ["069500","300000","300007","300009"]:
		groups.add_code(income,code)
	var store := Store.new(path)
	store.load_profile()
	return store.save_profile(watched,{}, {"security_names":names,"watchlist_view":groups.export_state()})

func run(directory: String, width: String) -> void:
	root.size = Vector2i(1280,720) if width=="1280" else Vector2i(1440,960)
	for index: int in 2:
		await process_frame
	var data: Dictionary = fixture()
	var profile_path := directory.path_join("review-profile.json")
	if not seed_profile(profile_path,data.items):
		push_error("Could not seed isolated review profile")
		quit(1)
		return
	var view: Control = load("res://scenes/headquarters.tscn").instantiate()
	view.embedded_in_camp = true
	root.add_child(view)
	for index: int in 8:
		await process_frame
	if not FileAccess.file_exists(directory.path_join("review-catalog.json")):
		if not view.catalog.accept_snapshot(data,true):
			push_error("Could not seed isolated review catalogue")
			quit(1)
			return
	view._open_watch_table()
	for index: int in 2:
		await process_frame
	if view.watch_table == null or not view.watch_table.is_inside_tree() or not view.watch_table.visible or view.watch_table.source_rows.size()!=60:
		push_error("Review table did not load all 60 fixture rows")
		quit(1)
		return
	if root.size.x != int(width):
		push_error("Review window width differs from requested width: "+str(root.size))
		quit(1)
		return
	print("WATCHLIST_GROUPS_REVIEW_READY: 60 synthetic rows; profile="+profile_path+"; resolution="+str(root.size))

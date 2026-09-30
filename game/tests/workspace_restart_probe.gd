extends SceneTree
## Independent-process shutdown/restart evidence. Requires isolated profile path.
const NOTE := "투자 가설: 수요 회복을 확인한다.\n반대 근거: 재고 증가와 가격 하락.\n다음 확인: 분기별 현금흐름 · 2026 검수용 노트"
var dashboard: Control

func _initialize() -> void:
	if not OS.get_cmdline_user_args().has("live"):
		OS.set_environment("PHALANX_RESEARCH_OFFLINE","1")
	OS.set_environment("PHALANX_RESEARCH_CACHE",OS.get_environment("TEMP").path_join("phalanx-research-test-%s" % OS.get_process_id()))
	call_deferred("run")

func run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()<2:
		push_error("Expected write/read and an isolated absolute profile path")
		quit(1)
		return
	root.size = Vector2i(1280,720)
	dashboard = load("res://scenes/headquarters.tscn").instantiate()
	dashboard.storage_path = args[1]
	dashboard.embedded_in_camp = true
	root.add_child(dashboard)
	for index: int in 6:
		await process_frame
	if args[0]=="write":
		dashboard._select_stock(0)
		dashboard._toggle_favorite()
		dashboard._select_stock(4)
		dashboard._toggle_favorite()
		dashboard._select_stock(1)
		dashboard.note_editor.text = NOTE
		dashboard._note_changed()
		# Deliberately quit before the debounce timeout; shutdown must flush.
		print("PHALANX_RESTART_WRITE: normal process exit with pending note")
		quit()
		return
	dashboard._select_stock(1)
	dashboard._select_workspace("research")
	var valid: bool = dashboard.note_editor.text==NOTE and dashboard.watchlist_codes.size()==3 and not "005930" in dashboard.watchlist_codes and not "069500" in dashboard.watchlist_codes
	if valid and args.size()>2 and DisplayServer.get_name()!="headless":
		for index: int in 8:
			await process_frame
		await RenderingServer.frame_post_draw
		DirAccess.make_dir_recursive_absolute(args[2])
		root.get_texture().get_image().save_png(args[2].path_join("research-restored-1280x720.png"))
		dashboard._select_workspace("market")
		for index: int in 8:
			await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png(args[2].path_join("watchlist-restored-1280x720.png"))
	print("PHALANX_RESTART_READ: %s (new process; note and 3 favorites restored)" % ["PASS" if valid else "FAIL"])
	quit(0 if valid else 1)

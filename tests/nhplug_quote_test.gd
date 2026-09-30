extends SceneTree
const Model = preload("res://scripts/nhplug_quote_model.gd")
var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("run")

func check(ok: bool, name: String) -> void:
	checks += 1
	if not ok:
		failures += 1
		push_error(name)

func run() -> void:
	var now := 1790640000
	var good := {"provider":"NHPLUG","code":"005930","market":"KRX","currency":"KRW","price":231000,"fetched_at":now}
	var parsed := Model.parse(good,"005930",now)
	check(parsed.get("price")==231000 and parsed.get("source")=="NH투자증권 NHPLUG","Public quote accepted")
	for mutation: Array in [["provider","KIS"],["code","000660"],["market","UNT"],["currency","USD"],["price",0],["price","231000"],["fetched_at",now+120]]:
		var bad := good.duplicate(true)
		bad[mutation[0]] = mutation[1]
		check(Model.parse(bad,"005930",now).is_empty(),"Reject mismatched or invalid quote: "+mutation[0])
	check(Model.parse(good,"000660",now).is_empty(),"Never paint another stock")
	print("PHALANX_NHPLUG_QUOTE_TEST: ","PASS" if failures==0 else "FAIL"," (",checks," checks)")
	quit(0 if failures==0 else 1)

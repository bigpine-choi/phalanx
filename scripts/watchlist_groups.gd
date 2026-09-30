extends RefCounted
## Saved watchlist grouping and deterministic table ordering, independent of UI.
signal changed

const Data = preload("res://scripts/market_data.gd")
const MAX_GROUPS := 32
const MAX_MEMBERS := 1000
const MAX_NAME_LENGTH := 40
const SORT_COLUMNS := ["name", "code", "market", "kind", "held", "status", "price", "quote_source", "quote_time", "quote_status"]

var groups: Array = []
var selected_group := "all"
var sort_column := "name"
var sort_ascending := true
var message := ""

static func defaults() -> Dictionary:
	return {"groups":[],"selected_group":"all","sort":{"column":"name","ascending":true}}

static func validate_state(value: Variant) -> bool:
	if not value is Dictionary or not value.get("groups") is Array or not value.get("selected_group") is String or not value.get("sort") is Dictionary:
		return false
	if value.groups.size() > MAX_GROUPS:
		return false
	var sort: Dictionary = value.sort
	if sort.get("column") not in SORT_COLUMNS or not sort.get("ascending") is bool:
		return false
	var ids := {}
	var names := {}
	for raw: Variant in value.groups:
		if not raw is Dictionary or not _valid_id(raw.get("id")) or not _valid_name(raw.get("name")) or not raw.get("codes") is Array:
			return false
		if ids.has(raw.id) or names.has(raw.name.to_lower()) or raw.codes.size() > MAX_MEMBERS:
			return false
		ids[raw.id] = true
		names[raw.name.to_lower()] = true
		var codes := {}
		for code: Variant in raw.codes:
			if not Data.valid_code(code) or codes.has(code):
				return false
			codes[code] = true
	return value.selected_group in ["all", "holdings"] or ids.has(value.selected_group)

static func _valid_id(value: Variant) -> bool:
	if not value is String or value.length() != 32:
		return false
	for character: String in value:
		if character not in "0123456789abcdef":
			return false
	return true

static func _valid_name(value: Variant) -> bool:
	return value is String and value.length() >= 1 and value.length() <= MAX_NAME_LENGTH and value == value.strip_edges() and not value.contains("\n") and not value.contains("\r") and not value.contains("\t")

func load_state(value: Variant) -> bool:
	if not validate_state(value):
		message = "관심그룹 저장 형식을 확인할 수 없습니다."
		return false
	groups = value.groups.duplicate(true)
	selected_group = value.selected_group
	sort_column = value.sort.column
	sort_ascending = value.sort.ascending
	message = ""
	changed.emit()
	return true

func export_state() -> Dictionary:
	return {"groups":groups.duplicate(true),"selected_group":selected_group,"sort":{"column":sort_column,"ascending":sort_ascending}}

func get_group(id: String) -> Dictionary:
	for group: Dictionary in groups:
		if group.id == id:
			return group.duplicate(true)
	return {}

func has_group(id: String) -> bool:
	return not get_group(id).is_empty()

func _name_available(name: String, except_id := "") -> bool:
	for group: Dictionary in groups:
		if group.id != except_id and group.name.to_lower() == name.to_lower():
			return false
	return true

func create_group(name: String) -> String:
	var normalized := name.strip_edges()
	if not _valid_name(normalized):
		message = "그룹 이름은 1~40자로 입력해 주세요."
		return ""
	if groups.size() >= MAX_GROUPS:
		message = "관심그룹은 최대 32개까지 만들 수 있습니다."
		return ""
	if not _name_available(normalized):
		message = "같은 이름의 관심그룹이 이미 있습니다."
		return ""
	for attempt: int in 16:
		var id := Crypto.new().generate_random_bytes(16).hex_encode()
		if has_group(id):
			continue
		groups.append({"id":id,"name":normalized,"codes":[]})
		message = ""
		changed.emit()
		return id
	message = "그룹 식별자를 만들지 못했습니다. 다시 시도해 주세요."
	return ""

func rename_group(id: String, name: String) -> bool:
	var normalized := name.strip_edges()
	if not _valid_name(normalized) or not _name_available(normalized, id):
		message = "그룹 이름을 확인해 주세요. 1~40자이며 중복할 수 없습니다."
		return false
	for index: int in groups.size():
		if groups[index].id == id:
			if groups[index].name == normalized:
				message = ""
				return true
			var updated: Dictionary = groups[index].duplicate(true)
			updated.name = normalized
			groups[index] = updated
			message = ""
			changed.emit()
			return true
	message = "관심그룹을 찾을 수 없습니다."
	return false

func delete_group(id: String) -> bool:
	for index: int in groups.size():
		if groups[index].id == id:
			groups.remove_at(index)
			if selected_group == id:
				selected_group = "all"
			message = ""
			changed.emit()
			return true
	message = "관심그룹을 찾을 수 없습니다."
	return false

func add_code(id: String, code: String) -> bool:
	if not Data.valid_code(code):
		message = "관심그룹에는 6자리 종목코드만 담을 수 있습니다."
		return false
	for index: int in groups.size():
		if groups[index].id == id:
			var codes: Array = groups[index].codes
			if code in codes:
				message = "이미 이 관심그룹에 있습니다."
				return false
			if codes.size() >= MAX_MEMBERS:
				message = "관심그룹에는 최대 1,000개 종목을 담을 수 있습니다."
				return false
			var updated: Dictionary = groups[index].duplicate(true)
			updated.codes.append(code)
			groups[index] = updated
			message = ""
			changed.emit()
			return true
	message = "관심그룹을 찾을 수 없습니다."
	return false

func remove_code(id: String, code: String) -> bool:
	for index: int in groups.size():
		if groups[index].id == id:
			if code not in groups[index].codes:
				message = "이 그룹에 없는 종목입니다."
				return false
			var updated: Dictionary = groups[index].duplicate(true)
			updated.codes.erase(code)
			groups[index] = updated
			message = ""
			changed.emit()
			return true
	message = "관심그룹을 찾을 수 없습니다."
	return false

func remove_code_everywhere(code: String) -> void:
	var removed := false
	for index: int in groups.size():
		if code in groups[index].codes:
			var updated: Dictionary = groups[index].duplicate(true)
			updated.codes.erase(code)
			groups[index] = updated
			removed = true
	if removed:
		message = ""
		changed.emit()

func select_group(id: String) -> bool:
	if id not in ["all", "holdings"] and not has_group(id):
		message = "관심그룹을 찾을 수 없습니다."
		return false
	if selected_group != id:
		selected_group = id
		message = ""
		changed.emit()
	return true

func set_sort(column: String, ascending: bool) -> void:
	if column not in SORT_COLUMNS:
		message = "지원하지 않는 정렬 기준입니다."
		return
	if sort_column != column or sort_ascending != ascending:
		sort_column = column
		sort_ascending = ascending
		message = ""
		changed.emit()

func rows_for(rows: Array, watchlist: Array) -> Array:
	var included := {}
	if selected_group == "all":
		for code: Variant in watchlist:
			included[code] = true
	elif selected_group != "holdings":
		var group := get_group(selected_group)
		for code: Variant in group.get("codes", []):
			included[code] = true
	var ordered: Array = []
	for index: int in rows.size():
		var row: Variant = rows[index]
		if not row is Dictionary or not row.get("code") is String:
			continue
		if selected_group == "holdings":
			# An account identity conflict must remain visible for resolution,
			# while its `held` value remains false for valuation and actions.
			if row.get("held") != true and row.get("account_present") != true:
				continue
		elif not included.has(row.code):
			continue
		ordered.append({"row":row,"index":index})
	ordered.sort_custom(_row_less)
	var result: Array = []
	for decorated: Dictionary in ordered:
		result.append(decorated.row)
	return result

func _row_less(left: Dictionary, right: Dictionary) -> bool:
	var a: Dictionary = left.row
	var b: Dictionary = right.row
	var a_value: Variant = a.get(sort_column)
	var b_value: Variant = b.get(sort_column)
	var a_unknown := _sort_unknown(a_value)
	var b_unknown := _sort_unknown(b_value)
	if a_unknown != b_unknown:
		return not a_unknown
	if not a_unknown:
		if sort_column == "held":
			if a_value != b_value:
				return (not a_value and b_value) if sort_ascending else (a_value and not b_value)
		elif sort_column == "price":
			if a_value != b_value:
				return float(a_value) < float(b_value) if sort_ascending else float(a_value) > float(b_value)
		else:
			var a_text := str(a_value).to_lower()
			var b_text := str(b_value).to_lower()
			if a_text != b_text:
				return a_text < b_text if sort_ascending else a_text > b_text
	var a_code: String = a.get("code", "")
	var b_code: String = b.get("code", "")
	if a_code != b_code:
		return a_code < b_code
	return int(left.index) < int(right.index)

static func _unknown(value: Variant) -> bool:
	return value == null or (value is String and value.strip_edges() in ["", "—"])

func _sort_unknown(value: Variant) -> bool:
	if sort_column == "price":
		return not (value is int or value is float) or float(value) <= 0.0
	return _unknown(value)

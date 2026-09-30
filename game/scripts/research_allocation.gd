extends VBoxContainer
## Read-only view of a saved research allocation result. It never talks to an account.
signal loaded(success: bool)

const T = preload("res://scripts/terminal_theme.gd")
const RESULT_LIMIT := 512 * 1024
const SOURCE_LIMIT := 32 * 1024 * 1024
const TIMEOUT_MS := 40000
const SCENARIO_KINDS := [
	"long_run_ledoit_wolf", "fast_iewma", "slow_iewma", "downside_stress_ledoit_wolf"
]

var busy := false
var payload: Dictionary = {}
var selected_scenario := 0
var scenario_buttons: Array[Button] = []
var status_label: Label
var file_dialog: FileDialog
var open_button: Button
var metadata_label: Label
var provenance_label: Label
var scenario_heading: Label
var scenario_note: Label
var holdings: VBoxContainer
var _pid := -1
var _deadline := 0
var _request_id := ""
var _result_path := ""

func _label(value: String, font_size := 14, color := T.TEXT) -> Label:
	var result := Label.new()
	result.text = value
	result.add_theme_font_size_override("font_size", font_size)
	result.add_theme_color_override("font_color", color)
	result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return result

func _panel(parent: Node) -> VBoxContainer:
	var frame := PanelContainer.new()
	frame.add_theme_stylebox_override("panel", T.panel_style(16))
	frame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	frame.add_child(box)
	return box

func _ready() -> void:
	name = "ResearchAllocationView"
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_theme_constant_override("separation", 12)
	var header := HBoxContainer.new()
	add_child(header)
	var title := VBoxContainer.new()
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	title.add_child(_label("RESEARCH  /  SAVED ALLOCATION", 10, T.GOLD))
	title.add_child(_label("연구 배분 · 저장 결과", 26))
	open_button = Button.new()
	open_button.name = "OpenAllocationFile"
	open_button.text = "배분 결과 JSON 열기"
	open_button.custom_minimum_size.y = 38
	open_button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	open_button.pressed.connect(_choose_file)
	header.add_child(open_button)
	add_child(_label("위험자산 내부 연구용 구성입니다. 실계좌 목표·추천·주문에 적용되지 않습니다.", 14, T.GOLD))
	add_child(_label("저장된 파일의 표시 관계만 검사합니다. 여기서 가격 DB·영수증·리플레이를 다시 검증하거나 계산하지 않습니다.", 12, T.MUTED))
	var overview := _panel(self)
	overview.add_child(_label("결과 파일", 17, T.GOLD))
	metadata_label = _label("파일을 열면 선정일, 계산일과 전체 상태를 표시합니다.", 13)
	metadata_label.name = "AllocationMetadata"
	overview.add_child(metadata_label)
	provenance_label = _label("재실행 근거: 파일을 열어 확인", 12, T.MUTED)
	provenance_label.name = "AllocationProvenance"
	overview.add_child(provenance_label)
	var tabs := HFlowContainer.new()
	tabs.add_theme_constant_override("h_separation", 8)
	tabs.add_theme_constant_override("v_separation", 8)
	add_child(tabs)
	for index: int in 4:
		var button := Button.new()
		button.name = "Scenario_%d" % index
		button.text = ["장기 균형", "빠른 적응", "느린 적응", "하방 스트레스"][index]
		button.toggle_mode = true
		button.disabled = true
		button.custom_minimum_size = Vector2(145, 38)
		button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
		button.pressed.connect(_select_scenario.bind(index))
		tabs.add_child(button)
		scenario_buttons.append(button)
	var detail := _panel(self)
	scenario_heading = _label("시나리오 비교", 18, T.GOLD)
	scenario_heading.name = "ScenarioHeading"
	detail.add_child(scenario_heading)
	scenario_note = _label("저장된 배분 결과를 선택하세요. 네 시나리오 중 자동 추천은 없습니다.", 13, T.MUTED)
	scenario_note.name = "ScenarioNotice"
	detail.add_child(scenario_note)
	holdings = VBoxContainer.new()
	holdings.name = "AllocationHoldings"
	holdings.add_theme_constant_override("separation", 6)
	detail.add_child(holdings)
	status_label = _label("결과 파일을 기다리는 중", 12, T.MUTED)
	status_label.name = "ResearchAllocationStatus"
	add_child(status_label)
	file_dialog = FileDialog.new()
	file_dialog.name = "TargetsFileDialog"
	file_dialog.access = FileDialog.ACCESS_FILESYSTEM
	file_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	file_dialog.filters = PackedStringArray(["*.json ; 배분 결과 JSON"])
	file_dialog.file_selected.connect(load)
	add_child(file_dialog)

func _choose_file() -> void:
	file_dialog.popup_centered_ratio(0.75)

func load(path: String) -> bool:
	"""Start a bounded local projection. `loaded` fires after the worker completes."""
	_cancel_request()
	_clear_result()
	if not path.is_absolute_path() or not FileAccess.file_exists(path):
		_fail("파일을 읽을 수 없습니다.")
		return false
	var source := FileAccess.open(path, FileAccess.READ)
	if source == null:
		_fail("파일을 읽을 수 없습니다.")
		return false
	var source_size := source.get_length()
	source.close()
	if source_size <= 0 or source_size > SOURCE_LIMIT:
		_fail("결과 파일은 32 MiB 이하의 JSON이어야 합니다.")
		return false
	var python := OS.get_environment("PHALANX_RESEARCH_PYTHON")
	if python.is_empty():
		python = OS.get_environment("PHALANX_ADVISOR_PYTHON")
	if python.is_empty():
		python = OS.get_environment("USERPROFILE").path_join("dev/phalanx/.venv/Scripts/python.exe")
	if not FileAccess.file_exists(python):
		_fail("Phalanx Python 실행 환경을 찾지 못했습니다.")
		return false
	var directory := OS.get_environment("PHALANX_ALLOCATION_REQUESTS")
	if directory.is_empty():
		directory = ProjectSettings.globalize_path("user://allocation_requests")
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		_fail("임시 결과 폴더를 만들 수 없습니다.")
		return false
	_request_id = "%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()]
	_result_path = directory.path_join(_request_id + ".json")
	var script := ProjectSettings.globalize_path("res://tools/allocation_projection_bridge.py")
	_pid = OS.create_process(python, PackedStringArray([script, path, _result_path, _request_id]), false)
	if _pid < 0:
		_cancel_request()
		_fail("연구 결과 읽기를 시작하지 못했습니다.")
		return false
	busy = true
	_deadline = Time.get_ticks_msec() + TIMEOUT_MS
	open_button.disabled = true
	status_label.text = "저장 결과를 읽고 표시 관계를 검사 중…"
	return true

func _process(_delta: float) -> void:
	if not busy:
		return
	if OS.is_process_running(_pid):
		if Time.get_ticks_msec() < _deadline:
			return
		OS.kill(_pid)
		_cancel_request()
		_fail("결과 파일 읽기 시간이 초과됐습니다.")
		return
	var expected_id := _request_id
	var result_path := _result_path
	_pid = -1
	var result: Variant = null
	var file := FileAccess.open(result_path, FileAccess.READ)
	if file != null:
		if file.get_length() <= RESULT_LIMIT:
			var parser := JSON.new()
			if parser.parse(file.get_as_text()) == OK:
				result = parser.data
		file.close()
	_cancel_request()
	if not result is Dictionary or result.get("request_id") != expected_id or not result.get("ok") is bool:
		_fail("결과를 읽지 못했습니다. Python 환경을 확인해주세요.")
		return
	if result.ok != true:
		_fail(_error_message(str(result.get("error", ""))))
		return
	if not _valid_projection(result.get("payload")):
		_fail("결과 화면 데이터가 올바르지 않습니다.")
		return
	payload = result.payload
	busy = false
	open_button.disabled = false
	selected_scenario = 0
	_render()
	loaded.emit(true)

func _valid_projection(value: Variant) -> bool:
	if not value is Dictionary or value.get("schema") != "phalanx.game_research_allocation_projection.v1" or value.get("source_semantics") != "saved_file_unverified":
		return false
	if not value.get("scenarios") is Array or value.scenarios.size() != 4:
		return false
	if not value.get("selected_codes") is Array or not value.get("source_name") is String:
		return false
	if not value.get("source_sha256") is String or not value.get("selection_as_of") is String or not value.get("status") is String:
		return false
	# Godot's JSON parser represents JSON integer tokens as floating-point values.
	if not _json_count(value.get("succeeded_count")) or not _json_count(value.get("observation_count")):
		return false
	if value.get("reference_price_date") != null and not value.get("reference_price_date") is String:
		return false
	if value.get("calculation_date") != null and not value.get("calculation_date") is String:
		return false
	if value.get("replay_provenance") != null and not value.get("replay_provenance") is Dictionary:
		return false
	for index: int in 4:
		var scenario: Variant = value.scenarios[index]
		if not scenario is Dictionary or scenario.get("kind") != SCENARIO_KINDS[index]:
			return false
		if not scenario.get("label") is String or not scenario.get("status") in ["succeeded", "failed", "not_run"] or not scenario.get("holdings") is Array:
			return false
		if scenario.status == "succeeded" and scenario.holdings.size() != value.selected_codes.size():
			return false
		if scenario.status != "succeeded" and not scenario.holdings.is_empty():
			return false
		for holding: Variant in scenario.holdings:
			if not holding is Dictionary or not holding.get("code") is String or not holding.get("weight_display") is String:
				return false
	return true

func _json_count(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value)) and float(value) >= 0.0 and float(value) == floorf(float(value))

func _render() -> void:
	var source_name: String = str(payload.get("source_name", ""))
	var source_sha: String = str(payload.get("source_sha256", ""))
	var reference := _date_text(payload.get("reference_price_date"))
	var calculated := _date_text(payload.get("calculation_date"))
	metadata_label.text = "%s\n선정일 %s  ·  참조 가격일 %s  ·  계산일 %s\n상태 %s  ·  선정 %d종목  ·  수익률 %d건  ·  성공 %d/4" % [
		source_name, str(payload.selection_as_of), reference, calculated,
		_status_name(str(payload.status)), payload.selected_codes.size(), int(payload.get("observation_count", 0)), int(payload.get("succeeded_count", 0))
	]
	var provenance: Variant = payload.get("replay_provenance")
	if provenance is Dictionary:
		provenance_label.text = "파일에 기록된 재실행 근거 · %s\n읽기 완료 %s  ·  판단 %s  ·  재실행 %s\n영수증 SHA-256 %s\n재실행 파일 SHA-256 %s\n결과 파일 SHA-256 %s" % [
			str(provenance.get("evidence_kind", "—")), str(provenance.get("read_completed_at", "—")),
			str(provenance.get("decision_at", "—")), str(provenance.get("replayed_at", "—")),
			str(provenance.get("read_receipt_file_sha256", "—")), str(provenance.get("replay_file_sha256", "—")), source_sha
		]
	else:
		provenance_label.text = "이 저장 결과에는 재실행 영수증 근거가 없습니다.\n결과 파일 SHA-256 %s (파일 식별용이며 진위 인증이 아닙니다)" % source_sha
	for button: Button in scenario_buttons:
		button.disabled = false
	_select_scenario(0)
	status_label.text = "저장 결과 표시 완료 · 원천 데이터와 영수증은 이 화면에서 재검증하지 않았습니다."

func _select_scenario(index: int) -> void:
	if payload.is_empty() or index < 0 or index >= scenario_buttons.size():
		return
	selected_scenario = index
	for i: int in scenario_buttons.size():
		scenario_buttons[i].set_pressed_no_signal(i == index)
	for child: Node in holdings.get_children():
		holdings.remove_child(child)
		child.queue_free()
	var scenario: Dictionary = payload.scenarios[index]
	scenario_heading.text = "%s · %s" % [str(scenario.label), _scenario_status(str(scenario.status))]
	if scenario.status != "succeeded":
		var failure: Variant = scenario.get("failure")
		scenario_note.text = str(failure.get("message", "계산된 목표 비중이 없습니다.")) if failure is Dictionary else "계산된 목표 비중이 없습니다."
		return
	scenario_note.text = "선정 순서의 위험자산 내부 비중 · 네 시나리오 중 자동 추천 없음"
	for item: Variant in scenario.holdings:
		var row := HBoxContainer.new()
		holdings.add_child(row)
		var code := _label(str(item.code), 14)
		row.add_child(code)
		var weight := _label(str(item.weight_display), 16, T.GOLD)
		weight.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		weight.custom_minimum_size.x = 115
		row.add_child(weight)

func _date_text(value: Variant) -> String:
	return "미산출" if value == null else str(value)

func _status_name(value: String) -> String:
	return {"input_unavailable":"입력 준비 불가", "common_failure":"공통 계산 실패", "succeeded":"네 시나리오 산출 완료", "partial":"일부 시나리오 산출", "failed":"모든 시나리오 계산 실패"}.get(value, value)

func _scenario_status(value: String) -> String:
	return "산출 완료" if value == "succeeded" else "미산출"

func _error_message(code: String) -> String:
	return {"INVALID_TARGETS":"배분 결과 형식이나 표시 근거가 올바르지 않습니다.", "INPUT_UNAVAILABLE":"결과 파일을 읽지 못했습니다.", "PROJECTION_TOO_LARGE":"결과 화면 데이터가 너무 큽니다.", "PROJECTION_FAILED":"결과 화면을 만들지 못했습니다."}.get(code, "결과 파일을 읽지 못했습니다.")

func _clear_result() -> void:
	payload.clear()
	selected_scenario = 0
	metadata_label.text = "파일을 열면 선정일, 계산일과 전체 상태를 표시합니다."
	provenance_label.text = "재실행 근거: 파일을 열어 확인"
	scenario_heading.text = "시나리오 비교"
	scenario_note.text = "저장된 배분 결과를 선택하세요. 네 시나리오 중 자동 추천은 없습니다."
	for button: Button in scenario_buttons:
		button.disabled = true
		button.set_pressed_no_signal(false)
	for child: Node in holdings.get_children():
		holdings.remove_child(child)
		child.queue_free()

func _fail(message: String) -> void:
	busy = false
	open_button.disabled = false
	status_label.text = message
	loaded.emit(false)

func _cancel_request() -> void:
	if _pid > 0 and OS.is_process_running(_pid):
		OS.kill(_pid)
	_pid = -1
	if not _result_path.is_empty() and FileAccess.file_exists(_result_path):
		DirAccess.remove_absolute(_result_path)
	if not _result_path.is_empty() and FileAccess.file_exists(_result_path + ".pending"):
		DirAccess.remove_absolute(_result_path + ".pending")
	_result_path = ""
	_request_id = ""
	busy = false
	if open_button != null:
		open_button.disabled = false

func _exit_tree() -> void:
	_cancel_request()

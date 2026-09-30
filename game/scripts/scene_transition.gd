extends CanvasLayer
## One input gate owns the complete departure, hidden handoff and arrival.
signal finished
const T := preload("res://scripts/terminal_theme.gd")
var busy := false
var curtain: Control
var progress := 0.0
var destination := ""
var subtitle := ""
var _handoff: Callable
var _motion: Callable
var _switched := false
var _tween: Tween
var _label_font: Font = T.font()
var _seal_font: Font = T.title_font()

func _ready() -> void:
	layer = 40
	curtain = Control.new()
	curtain.name = "LocationTransition"
	curtain.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	curtain.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(curtain)
	curtain.draw.connect(_draw_curtain)
	curtain.resized.connect(curtain.queue_redraw)
	curtain.hide()

func play(title: String, caption: String, handoff: Callable, motion: Callable) -> void:
	if busy:
		return
	busy = true
	destination = title
	subtitle = caption
	_handoff = handoff
	_motion = motion
	_switched = false
	curtain.show()
	_set_progress(0.0)
	_tween = create_tween()
	_tween.tween_method(_set_progress, 0.0, 1.0, 1.28)
	_tween.tween_callback(func() -> void:
		curtain.hide()
		busy = false
		finished.emit())

func _set_progress(value: float) -> void:
	progress = value
	if progress >= 0.44 and not _switched:
		_switched = true
		_handoff.call()
	_motion.call(progress, _switched)
	curtain.queue_redraw()

func _draw_curtain() -> void:
	var factor := maxf(1.0, minf(curtain.size.x / 1440.0, curtain.size.y / 960.0))
	curtain.draw_set_transform(Vector2.ZERO,0.0,Vector2.ONE*factor)
	var s := curtain.size / factor
	var fade := smoothstep(0.0, 0.28, progress) * (1.0 - smoothstep(0.57, 1.0, progress))
	curtain.draw_rect(Rect2(Vector2.ZERO, s), Color(0.035, 0.028, 0.020, fade))
	var bars := sin(progress * PI)
	curtain.draw_rect(Rect2(0, 0, s.x, 48 * bars), Color(0.035, 0.028, 0.020, bars))
	curtain.draw_rect(Rect2(0, s.y - 48 * bars, s.x, 48 * bars), Color(0.035, 0.028, 0.020, bars))
	var ink := smoothstep(0.12, 0.32, progress) * (1.0 - smoothstep(0.64, 0.86, progress))
	var center := s * 0.5 + Vector2(0, lerpf(12, -8, progress))
	var gold := Color(T.GOLD, ink)
	curtain.draw_arc(center + Vector2(0, -65), 27, 0, TAU, 64, gold, 1.2, true)
	curtain.draw_arc(center + Vector2(0, -65), 32, -PI * 0.85, PI * 0.85, 64, Color(T.GOLD, ink * 0.35), 1, true)
	curtain.draw_string(_seal_font, center + Vector2(-12, -54), "Φ", HORIZONTAL_ALIGNMENT_LEFT, -1, 31, gold)
	var font := _label_font
	var width := font.get_string_size(destination, HORIZONTAL_ALIGNMENT_LEFT, -1, 30).x
	curtain.draw_string(font, center + Vector2(-width * 0.5, 7), destination, HORIZONTAL_ALIGNMENT_LEFT, -1, 30, Color(T.TEXT, ink))
	width = font.get_string_size(subtitle, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x
	curtain.draw_string(font, center + Vector2(-width * 0.5, 40), subtitle, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(T.MUTED, ink))
	for direction: float in [-1.0, 1.0]:
		curtain.draw_line(center + Vector2(direction * 135, -5), center + Vector2(direction * 240, -5), Color(T.GOLD, ink * 0.5), 1, true)
		var tip := center + Vector2(direction * 125, -5)
		curtain.draw_colored_polygon(PackedVector2Array([tip + Vector2(0,-3), tip + Vector2(3,0), tip + Vector2(0,3), tip + Vector2(-3,0)]), gold)
	curtain.draw_set_transform(Vector2.ZERO)

func _input(_event: InputEvent) -> void:
	if busy:
		get_viewport().set_input_as_handled()

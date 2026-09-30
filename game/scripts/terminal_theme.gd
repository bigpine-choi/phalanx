extends RefCounted
## Shared terminal palette, type and states. All controls keep visible keyboard focus.
const BG := Color("17130f")
const PANEL := Color("262019")
const INSET := Color("1b1813")
const BORDER := Color("655039")
const TEXT := Color("f0e3c9")
const MUTED := Color("b5a68b")
const ACCENT := Color("afc19a")
const GOLD := Color("d4ad65")
const RED := Color("df9a83")
const SELECTED := Color("473b25")

static func style(color: Color, border := Color.TRANSPARENT, radius := 2, padding := 12) -> StyleBoxFlat:
	var result := StyleBoxFlat.new()
	result.bg_color = color
	result.border_color = border
	result.set_border_width_all(1)
	result.set_corner_radius_all(mini(radius, 2))
	result.content_margin_left = padding
	result.content_margin_right = padding
	result.content_margin_top = padding
	result.content_margin_bottom = padding
	return result

static func title_font() -> SystemFont:
	var result := SystemFont.new()
	result.font_names = PackedStringArray(["Georgia", "Batang", "Noto Serif CJK KR"])
	return result

static func panel_style(padding := 14) -> StyleBoxFlat:
	var result := style(PANEL, BORDER, 2, padding)
	result.border_width_bottom = 2
	result.shadow_color = Color(0, 0, 0, 0.25)
	result.shadow_size = 4
	result.shadow_offset = Vector2(0,2)
	return result

static func font(mono := false) -> SystemFont:
	var result := SystemFont.new()
	result.font_names = PackedStringArray(["Consolas", "Malgun Gothic"]) if mono else PackedStringArray(["Segoe UI", "Malgun Gothic", "Noto Sans CJK KR"])
	return result

static func create() -> Theme:
	var result := Theme.new()
	result.default_font = font()
	result.default_font_size = 14
	for type_name: String in ["Label", "Button", "LineEdit", "TextEdit", "CheckButton"]:
		result.set_color("font_color",type_name,TEXT)
	result.set_color("font_hover_color","Button",Color.WHITE)
	result.set_color("font_pressed_color","Button",GOLD)
	result.set_color("font_disabled_color","Button",Color("807564"))
	result.set_stylebox("normal","Button",style(INSET,BORDER,5,8))
	result.set_stylebox("hover","Button",style(Color("3b3124"),GOLD,2,8))
	var pressed := style(SELECTED,GOLD,2,8)
	pressed.border_width_left = 3
	result.set_stylebox("pressed","Button",pressed)
	result.set_stylebox("disabled","Button",style(INSET,BORDER,5,8))
	var focus := style(Color.TRANSPARENT,GOLD,5,0)
	focus.set_border_width_all(2)
	result.set_stylebox("focus","Button",focus)
	for type_name: String in ["LineEdit", "TextEdit"]:
		result.set_stylebox("normal",type_name,style(INSET,BORDER,5,10))
		result.set_stylebox("focus",type_name,style(INSET,ACCENT,5,10))
		result.set_color("font_placeholder_color",type_name,MUTED)
		result.set_color("caret_color",type_name,ACCENT)
		result.set_color("selection_color",type_name,Color("5c4d31"))
	result.set_stylebox("background","ProgressBar",style(INSET,BORDER,2,0))
	result.set_stylebox("fill","ProgressBar",style(GOLD,Color.TRANSPARENT,2,0))
	result.set_stylebox("panel","TooltipPanel",style(PANEL,GOLD,2,10))
	result.set_color("font_color","TooltipLabel",TEXT)
	result.set_stylebox("panel","AcceptDialog",style(PANEL,BORDER,8,18))
	result.set_color("font_color","RichTextLabel",TEXT)
	for type_name: String in ["HScrollBar", "VScrollBar"]:
		result.set_stylebox("scroll",type_name,style(INSET,Color.TRANSPARENT,2,4))
		result.set_stylebox("grabber",type_name,style(Color("766044"),Color.TRANSPARENT,2,4))
		result.set_stylebox("grabber_highlight",type_name,style(GOLD,Color.TRANSPARENT,2,4))
		result.set_stylebox("grabber_pressed",type_name,style(GOLD,Color.TRANSPARENT,2,4))
	result.set_icon("checked","CheckButton",toggle_icon(true))
	result.set_icon("unchecked","CheckButton",toggle_icon(false))
	return result

static func toggle_icon(enabled: bool) -> Texture2D:
	var svg := '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="16"><rect x="1" y="1" width="28" height="14" rx="7" fill="#211a13" stroke="#94774b"/><circle cx="%s" cy="8" r="5" fill="%s"/></svg>' % ["22" if enabled else "8", "#d4ad65" if enabled else "#807564"]
	var image := Image.new()
	image.load_svg_from_string(svg)
	return ImageTexture.create_from_image(image)

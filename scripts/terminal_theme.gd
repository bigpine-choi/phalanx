extends RefCounted
## Shared terminal palette, type and states. All controls keep visible keyboard focus.
const BG := Color("0c1118")
const PANEL := Color("131b25")
const INSET := Color("0f1720")
const BORDER := Color("273341")
const TEXT := Color("e8edf3")
const MUTED := Color("91a2b6")
const ACCENT := Color("5ed6ba")
const GOLD := Color("d8b77a")
const RED := Color("f28c9b")

static func style(color: Color, border := Color.TRANSPARENT, radius := 6, padding := 12) -> StyleBoxFlat:
	var result := StyleBoxFlat.new()
	result.bg_color = color
	result.border_color = border
	result.set_border_width_all(1)
	result.set_corner_radius_all(radius)
	result.content_margin_left = padding
	result.content_margin_right = padding
	result.content_margin_top = padding
	result.content_margin_bottom = padding
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
	result.set_color("font_pressed_color","Button",ACCENT)
	result.set_color("font_disabled_color","Button",Color("617084"))
	result.set_stylebox("normal","Button",style(INSET,BORDER,5,8))
	result.set_stylebox("hover","Button",style(Color("202f3d"),Color("445970"),5,8))
	result.set_stylebox("pressed","Button",style(Color("16352f"),Color("367665"),5,8))
	result.set_stylebox("disabled","Button",style(INSET,BORDER,5,8))
	var focus := style(Color.TRANSPARENT,GOLD,5,0)
	focus.set_border_width_all(2)
	result.set_stylebox("focus","Button",focus)
	for type_name: String in ["LineEdit", "TextEdit"]:
		result.set_stylebox("normal",type_name,style(INSET,BORDER,5,10))
		result.set_stylebox("focus",type_name,style(INSET,ACCENT,5,10))
		result.set_color("font_placeholder_color",type_name,MUTED)
		result.set_color("caret_color",type_name,ACCENT)
		result.set_color("selection_color",type_name,Color("2e5b58"))
	result.set_stylebox("background","ProgressBar",style(Color("273744"),Color.TRANSPARENT,2,0))
	result.set_stylebox("fill","ProgressBar",style(ACCENT,Color.TRANSPARENT,2,0))
	result.set_stylebox("panel","TooltipPanel",style(Color("243244"),BORDER,5,10))
	result.set_color("font_color","TooltipLabel",TEXT)
	result.set_stylebox("panel","AcceptDialog",style(PANEL,BORDER,8,18))
	result.set_color("font_color","RichTextLabel",TEXT)
	return result

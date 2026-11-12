--!nonstrict
-- The bar button: a camera that opens the screenshot menu (menu.luau).

barWidget.setGlyph("camera")
barWidget.setTooltip("Screenshot")

function onClick()
  noctalia.togglePanel("omega/magpie-shot:menu")
end

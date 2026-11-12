--!nonstrict
-- The screenshot menu. One row per kind, its shortcut on the right.
--
-- Choosing one closes the menu FIRST and only then takes the shot, after a
-- short wait: the screenshot is of the screen as it is when the key goes down,
-- and a menu still fading out would be in it. The shot itself is the same
-- thing the keys do (~/.config/hypr/screenshot.sh -> magpie over D-Bus).

-- How long the menu needs to be gone. The panel closes without a long
-- animation; this leaves several frames of margin on top of it.
local WAIT = "0.5"

local KINDS = {
  { mode = "region",  glyph = "crop",           label = "Region",        keys = "Ctrl + Print",
    note = "Drag an area, or click a window" },
  { mode = "monitor", glyph = "device-desktop", label = "This screen",   keys = "Super + Print",
    note = "The monitor you are on" },
  { mode = "all",     glyph = "screen-share",   label = "All screens",   keys = "Alt + Print",
    note = "Every monitor, side by side" },
}

local function take(mode)
  panel.close()
  noctalia.runAsync({ "sh", "-c", "sleep " .. WAIT .. "; exec \"$HOME/.config/hypr/screenshot.sh\" " .. mode })
end

function onRegion() take("region") end
function onMonitor() take("monitor") end
function onAll() take("all") end

local handlers = { region = "onRegion", monitor = "onMonitor", all = "onAll" }

local function row(kind)
  return ui.row({
    key = kind.mode, onClick = handlers[kind.mode], align = "center", gap = 12,
    paddingH = 12, paddingV = 9, radius = 12, fill = "surface_variant/0.45",
  }, {
    ui.glyph({ name = kind.glyph, size = 20, color = "primary" }),
    ui.column({ gap = 1, align = "start", flexGrow = 1 }, {
      ui.label({ text = kind.label, fontWeight = "medium", color = "on_surface" }),
      ui.label({ text = kind.note, fontSize = 11, color = "on_surface_variant" }),
    }),
    ui.label({ text = kind.keys, fontSize = 11, color = "on_surface_variant" }),
  })
end

function onOpen(_context)
  local rows = {}
  for _, kind in ipairs(KINDS) do
    table.insert(rows, row(kind))
  end
  panel.render(ui.column({ gap = 8 }, {
    ui.label({ text = "Screenshot", fontSize = 15, fontWeight = "bold", color = "on_surface" }),
    ui.column({ gap = 6 }, rows),
  }))
end

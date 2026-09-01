#!/usr/bin/env python3
# ============================================================================
# generate_matrix_preview.py — build theme/preview.png for the theme
# selector (SUPER + something / `omarchy theme set` menu, via
# omarchy-theme-switcher, which looks for preview.png/.jpg/... at the top of
# a theme directory before falling back to the first background image).
#
# STATUS: DONE — replaces the earlier version of this file, which just
# cropped the wallpaper poster (no icons/code/system-monitor colors visible,
# didn't actually show what the theme looks like in use).
#
# Every stock theme's preview.png (checked: hackerman, gruvbox, ...) is a
# REAL desktop screenshot of one fixed scene — Neovim+Neo-tree w/ 2 tabs,
# a terminal running `ls`, btop, and Nautilus Files at Home, tiled in a
# 2x2-ish grid — just recolored per theme. This script only does the last
# step (crop/scale/quantize an already-captured screenshot to the standard
# 1800x1012). It does NOT set up the desktop scene itself — that part was
# done interactively via hyprctl (see recipe below) because it involves
# positioning windows exactly, waiting for content (btop stats) to
# populate, and eyeballing the result before committing to a screenshot.
#
# RECIPE for producing --source (re-run if colors.toml or icons change):
#   1. Make sure the target theme is actually applied
#      (`omarchy theme set matrix` or equivalent) so Neovim colorscheme,
#      GTK icon theme, and terminal colors all reflect it.
#   2. Set the monitor to 1920x1080 if it isn't already (matches the
#      1800x1012 output aspect ratio almost exactly, so the final crop is
#      minimal): hyprctl eval 'hl.monitor({ output = "<name>", mode =
#      "1920x1080@60", position = "0x0", scale = 1 })'
#   3. Open 4 floating windows and position them (all via
#      `hyprctl eval 'hl.dispatch(hl.dsp.window.<action>({...}))'` —
#      float({}) then resize({x=W,y=H}) then move({x=X,y=Y}), acting on
#      whichever window is currently focused, so float/resize/move each
#      spawned window immediately after launching it):
#        - top-left   (8,42)     992x818  — foot running nvim, e.g.:
#          nvim -c "<line>" -c "normal! zz" -c "Neotree toggle"
#               -c "tabnew <file2>" -c "tabfirst" <file1>
#          (jump to a line with real code BEFORE toggling Neotree — Neotree
#          steals window focus, so a later line-jump lands in the tree
#          pane instead of the buffer and silently does nothing)
#        - bottom-left (8,868)   992x204  — foot running `ls -la; exec $SHELL`
#        - top-right  (1008,42)  904x658  — foot running btop (give it a
#          couple seconds after launch for CPU/net graphs to populate)
#        - bottom-right (1008,708) 904x364 — `nautilus --new-window "$HOME"`
#      Target a specific window (not just "whatever's focused") via
#      hl.dsp.focus({window = "class:^(app-id)$"}) first, using unique
#      --app-id values on each `foot` invocation.
#   4. Move the cursor somewhere over flat background before capturing —
#      hyprctl eval 'hl.dispatch(hl.dsp.cursor.move({x=X,y=Y}))' — grim
#      captures the real cursor and the stock previews don't show one.
#   5. grim <source.png>
#
# Quantizes the crop to an 8-bit palette afterward, same as the stock
# previews — cuts the file to a few hundred KB, in line with stock sizes.
# ============================================================================
import argparse
from pathlib import Path

from PIL import Image

TARGET_W, TARGET_H = 1800, 1012


def build_preview(source_path, out_path):
    src = Image.open(source_path).convert("RGB")
    sw, sh = src.size
    scale = max(TARGET_W / sw, TARGET_H / sh)
    new_w, new_h = round(sw * scale), round(sh * scale)
    resized = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - TARGET_W) // 2
    top = (new_h - TARGET_H) // 2
    cropped = resized.crop((left, top, left + TARGET_W, top + TARGET_H))
    quant = cropped.quantize(colors=256, method=Image.Quantize.MAXCOVERAGE)
    quant.save(out_path, optimize=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--source",
        required=True,
        help="Raw desktop screenshot to crop/scale/quantize (see recipe in this file's header)",
    )
    p.add_argument(
        "--out",
        default=str(Path.home() / ".config/omarchy/themes/matrix/preview.png"),
    )
    args = p.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Source screenshot not found: {source}")

    build_preview(source, args.out)
    print(f"Wrote {args.out} ({TARGET_W}x{TARGET_H})")


if __name__ == "__main__":
    main()

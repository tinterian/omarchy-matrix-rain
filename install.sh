#!/bin/bash
# ============================================================================
# install.sh — install the animated Matrix digital-rain wallpaper into an
# existing Omarchy setup.
#
# What this does, in order:
#   1. Check dependencies (python3, Pillow, ffmpeg, mpvpaper, inotify-tools).
#   2. Create ~/.config/omarchy/themes/matrix/ if it doesn't exist yet, and
#      install theme/{colors.toml,icons.theme,neovim.lua,vscode.json,
#      unlock.png} into it (each file individually skipped if already
#      present — never overwrites an existing customization).
#   2b. If an AUR helper is available (yay/paru), offer to install the
#      `beautyline` outline icon pack and generate "BeautyLine-Matrix"
#      (see generate_matrix_icons.py) into ~/.local/share/icons/ — covers
#      every icon a file manager can show: the default folders (full
#      dark-green-to-black recolor), plus every other place/device/file-
#      type icon (original colors kept, black-fade overlay only). Skipped
#      non-fatally with a note if no AUR helper is found — icons.theme
#      already points at BeautyLine-Matrix, so icons just won't be themed
#      until you install it yourself.
#   3. Detect your screen resolution (via hyprctl) and render 4 text-size
#      variants (small/medium/large/xlarge) locally with matrix_rain.py.
#      This is the slow part — expect ~15-25 minutes total, one-time.
#   4. Install the rendered variants + poster stills into the theme's
#      backgrounds/ folder, install matrix-wallpaper to ~/.local/bin/ and
#      matrix-wallpaper.service to ~/.config/systemd/user/, enable it.
#   5. Generate theme/preview.png (see generate_matrix_preview.py) from the
#      freshly-rendered medium poster, for the Omarchy theme switcher's
#      selector grid — regenerated every run, same as the variants
#      themselves, so it always matches your actual resolution.
#
# Safe to re-run: existing colors.toml is left alone, variants are
# overwritten (regenerated) if you run it again.
#
# See README.md for what to do manually if you'd rather not run this
# script, and matrix_rain.py's own header comment for how to add more
# variants or change these later without re-breaking things that took a
# few rounds to get right the first time.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THEME_DIR="$HOME/.config/omarchy/themes/matrix"
BACKGROUNDS_DIR="$THEME_DIR/backgrounds"

echo "== Matrix digital-rain wallpaper installer =="
echo

# --- 1. Dependency check -----------------------------------------------
missing=()
command -v python3 >/dev/null || missing+=(python)
python3 -c "import PIL" 2>/dev/null || missing+=(python-pillow)
command -v ffmpeg >/dev/null || missing+=(ffmpeg)
command -v mpvpaper >/dev/null || missing+=(mpvpaper)
command -v inotifywait >/dev/null || missing+=(inotify-tools)
command -v hyprctl >/dev/null || missing+=(hyprland)
command -v jq >/dev/null || missing+=(jq)

# The authentic look depends on a font with half-width katakana glyphs, not
# just any monospace font -- matrix_rain.py silently falls back to plain
# digits/letters otherwise (with a warning), which looks nothing like
# Matrix rain. Check this the same way matrix_rain.py itself does, so we
# only ask for the font package if it's actually needed (not everyone's
# system font stack is the same).
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
import matrix_rain as m
sys.exit(0 if m.font_supports_katakana(m.find_font(16)) else 1)
" 2>/dev/null || missing+=(noto-fonts-cjk)

if (( ${#missing[@]} > 0 )); then
  echo "Missing dependencies: ${missing[*]}"
  read -r -p "Install with 'sudo pacman -S --needed ${missing[*]}'? [y/N] " reply
  if [[ $reply =~ ^[Yy]$ ]]; then
    sudo pacman -S --needed "${missing[@]}"
  else
    echo "Install the packages above yourself, then re-run this script." >&2
    exit 1
  fi
fi
echo "Dependencies OK."
echo

# --- 2. Theme colors + per-app integration files -------------------------
mkdir -p "$BACKGROUNDS_DIR"
for f in colors.toml icons.theme neovim.lua vscode.json unlock.png; do
  if [[ -f "$THEME_DIR/$f" ]]; then
    echo "Existing $THEME_DIR/$f found — leaving it as-is."
  else
    cp "$SCRIPT_DIR/theme/$f" "$THEME_DIR/$f"
    echo "Installed theme/$f -> $THEME_DIR/$f"
  fi
done
echo

# --- 2b. Outline folder icons (optional, needs an AUR helper) ------------
AUR_HELPER=""
command -v yay >/dev/null && AUR_HELPER=yay
[[ -z $AUR_HELPER ]] && command -v paru >/dev/null && AUR_HELPER=paru

if [[ -d /usr/share/icons/BeautyLine ]]; then
  python3 "$SCRIPT_DIR/generate_matrix_icons.py" --theme-name matrix
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/BeautyLine-Matrix" >/dev/null 2>&1 || true
  echo "Generated BeautyLine-Matrix folder icons."
elif [[ -n $AUR_HELPER ]]; then
  read -r -p "Install the 'beautyline' outline icon pack from the AUR with $AUR_HELPER for themed folder icons? [y/N] " reply
  if [[ $reply =~ ^[Yy]$ ]]; then
    "$AUR_HELPER" -S --needed beautyline
    python3 "$SCRIPT_DIR/generate_matrix_icons.py" --theme-name matrix
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/BeautyLine-Matrix" >/dev/null 2>&1 || true
    echo "Generated BeautyLine-Matrix folder icons."
  else
    echo "Skipping folder icons — run 'python3 $SCRIPT_DIR/generate_matrix_icons.py' after installing beautyline yourself."
  fi
else
  echo "No AUR helper (yay/paru) found — skipping folder icons."
  echo "Install 'beautyline' from the AUR yourself, then run:"
  echo "  python3 $SCRIPT_DIR/generate_matrix_icons.py --theme-name matrix"
fi
echo

# --- 3. Detect resolution -------------------------------------------------
read -r WIDTH HEIGHT < <(
  hyprctl monitors -j | jq -r '
    (map(select(.focused)) + .)[0] | "\(.width) \(.height)"
  '
)
if [[ -z ${WIDTH:-} || -z ${HEIGHT:-} ]]; then
  echo "Could not detect monitor resolution via hyprctl, defaulting to 1920x1080."
  WIDTH=1920
  HEIGHT=1080
fi
echo "Rendering at ${WIDTH}x${HEIGHT}."
echo

# --- 4. Render variants ---------------------------------------------------
# name:font-size pairs. font-size is chosen relative to a 1360x702 reference
# (what this was designed/tuned on) so text reads at roughly the same
# physical size regardless of your actual resolution.
REF_HEIGHT=702
declare -A SIZES=( [1-digital-rain-small]=7 [2-digital-rain-medium]=11 [3-digital-rain-large]=16 [4-digital-rain-xlarge]=28 )

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

for name in "${!SIZES[@]}"; do
  ref_font=${SIZES[$name]}
  font_size=$(( ref_font * HEIGHT / REF_HEIGHT ))
  (( font_size < 4 )) && font_size=4
  echo "-- Rendering $name (font-size $font_size) --"
  python3 "$SCRIPT_DIR/matrix_rain.py" \
    --width "$WIDTH" --height "$HEIGHT" --font-size "$font_size" \
    --use-omarchy-theme --theme-name matrix \
    --frames 720 --out "$TMP_DIR/$name.mp4"

  ffmpeg -y -hide_banner -loglevel error \
    -i "$TMP_DIR/$name.mp4" -vf "select=eq(n\,0)" -vframes 1 "$TMP_DIR/$name.png"

  cp "$TMP_DIR/$name.mp4" "$BACKGROUNDS_DIR/$name.mp4"
  cp "$TMP_DIR/$name.png" "$BACKGROUNDS_DIR/$name.png"
done
echo
echo "Installed 4 variants into $BACKGROUNDS_DIR"
echo

# --- 4b. Theme-switcher preview image --------------------------------------
python3 "$SCRIPT_DIR/generate_matrix_preview.py" \
  --poster "$BACKGROUNDS_DIR/2-digital-rain-medium.png" \
  --out "$THEME_DIR/preview.png"
echo

# --- 5. Install the wallpaper launcher + service --------------------------
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user"
cp "$SCRIPT_DIR/matrix-wallpaper" "$HOME/.local/bin/matrix-wallpaper"
chmod +x "$HOME/.local/bin/matrix-wallpaper"
cp "$SCRIPT_DIR/matrix-wallpaper.service" "$HOME/.config/systemd/user/matrix-wallpaper.service"

systemctl --user daemon-reload
systemctl --user enable --now matrix-wallpaper.service
echo "Installed and started matrix-wallpaper.service."
echo

# --- 6. Refresh + point the picker at the medium variant if Matrix is active
if omarchy-theme-refresh >/dev/null 2>&1; then
  current_theme=$(cat "$HOME/.local/state/omarchy/current/theme.name" 2>/dev/null || true)
  if [[ $current_theme == matrix ]]; then
    poster="$HOME/.local/state/omarchy/current/theme/backgrounds/2-digital-rain-medium.png"
    [[ -f $poster ]] && omarchy-theme-bg-set "$poster" 2>/dev/null || true
  fi
fi

cat <<'EOF'
== Done ==

If the Matrix theme isn't already selected:
    omarchy-theme-set matrix
  or pick "Matrix" from the Omarchy theme menu.

Once it's active, the animated rain plays automatically. Flip between the
4 text-size variants with the standard Omarchy background switcher:
    SUPER CTRL + SPACE
or:
    omarchy-theme-bg-next

See README.md for troubleshooting and matrix_rain.py's header comment if
you want to change font sizes, add another variant, or regenerate.
EOF

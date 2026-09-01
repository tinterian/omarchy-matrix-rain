#!/bin/bash
# ============================================================================
# install.sh — install the animated Matrix digital-rain wallpaper into an
# existing Omarchy setup.
#
# What this does, in order:
#   1. Check dependencies (python3, Pillow, ffmpeg, mpvpaper, inotify-tools).
#   2. Create ~/.config/omarchy/themes/matrix/ if it doesn't exist yet, and
#      install theme/colors.toml into it (skipped if a colors.toml is
#      already there — never overwrites an existing customization).
#   3. Detect your screen resolution (via hyprctl) and render 4 text-size
#      variants (small/medium/large/xlarge) locally with matrix_rain.py.
#      This is the slow part — expect ~15-25 minutes total, one-time.
#   4. Install the rendered variants + poster stills into the theme's
#      backgrounds/ folder, install matrix-wallpaper to ~/.local/bin/ and
#      matrix-wallpaper.service to ~/.config/systemd/user/, enable it.
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

# --- 2. Theme colors -----------------------------------------------------
mkdir -p "$BACKGROUNDS_DIR"
if [[ -f "$THEME_DIR/colors.toml" ]]; then
  echo "Existing $THEME_DIR/colors.toml found — leaving it as-is."
else
  cp "$SCRIPT_DIR/theme/colors.toml" "$THEME_DIR/colors.toml"
  echo "Installed theme/colors.toml -> $THEME_DIR/colors.toml"
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

#!/bin/bash
# Removes what install.sh added: the systemd service, the launcher script,
# and the 4 generated background variants. Leaves the rest of the theme
# alone — colors.toml, icons.theme, neovim.lua, vscode.json, unlock.png,
# preview.png (delete ~/.config/omarchy/themes/matrix yourself if you want
# the whole theme gone, or ~/.local/share/icons/BeautyLine-Matrix too if you
# installed the icon pack).
set -euo pipefail

systemctl --user disable --now matrix-wallpaper.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/matrix-wallpaper.service"
systemctl --user daemon-reload

rm -f "$HOME/.local/bin/matrix-wallpaper"

BACKGROUNDS_DIR="$HOME/.config/omarchy/themes/matrix/backgrounds"
rm -f "$BACKGROUNDS_DIR"/1-digital-rain-small.{mp4,png}
rm -f "$BACKGROUNDS_DIR"/2-digital-rain-medium.{mp4,png}
rm -f "$BACKGROUNDS_DIR"/3-digital-rain-large.{mp4,png}
rm -f "$BACKGROUNDS_DIR"/4-digital-rain-xlarge.{mp4,png}

echo "Removed matrix-wallpaper service, launcher, and generated backgrounds."
echo "theme/colors.toml at ~/.config/omarchy/themes/matrix/colors.toml was left in place."

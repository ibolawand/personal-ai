#!/usr/bin/env bash
# One-time setup: Mint menu entry, start on login, and the Ctrl+Alt+Space hotkey.
# Run again after moving the project folder.  Undo with: ./install_desktop.sh --remove
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APPS="$HOME/.local/share/applications"
AUTO="$HOME/.config/autostart"
KB_SCHEMA="org.cinnamon.desktop.keybindings"
KB_ID="aria"
KB_PATH="/org/cinnamon/desktop/keybindings/custom-keybindings/$KB_ID/"
HOTKEY="${ARIA_HOTKEY:-<Primary><Alt>space}"

if [ "$1" = "--remove" ]; then
  rm -f "$APPS/aria.desktop" "$AUTO/aria.desktop"
  list="$(gsettings get $KB_SCHEMA custom-list | sed "s/'$KB_ID'//; s/, ,/,/; s/\[, /[/; s/, \]/]/")"
  gsettings set $KB_SCHEMA custom-list "$list"
  dconf reset -f "$KB_PATH"
  echo "Removed menu entry, autostart and hotkey."
  exit 0
fi

mkdir -p "$APPS" "$AUTO"
entry() {
cat <<DESK
[Desktop Entry]
Type=Application
Name=Aria
Comment=Local desk assistant
Exec=$DIR/aria.sh
Icon=$DIR/ui/aria.png
Terminal=false
Categories=Utility;
StartupNotify=false
DESK
}
entry > "$APPS/aria.desktop"
{ entry; echo "X-GNOME-Autostart-Delay=8"; } > "$AUTO/aria.desktop"

# Cinnamon custom shortcut → aria.sh --toggle
current="$(gsettings get $KB_SCHEMA custom-list)"
if ! grep -q "'$KB_ID'" <<<"$current"; then
  if [ "$current" = "@as []" ] || [ "$current" = "[]" ]; then new="['$KB_ID']"
  else new="${current%]}, '$KB_ID']"; fi
  gsettings set $KB_SCHEMA custom-list "$new"
fi
gsettings set $KB_SCHEMA.custom-keybinding:$KB_PATH name "Aria"
gsettings set $KB_SCHEMA.custom-keybinding:$KB_PATH command "$DIR/aria.sh --toggle"
gsettings set $KB_SCHEMA.custom-keybinding:$KB_PATH binding "['$HOTKEY']"

echo "Installed:"
echo "  menu entry  $APPS/aria.desktop"
echo "  autostart   $AUTO/aria.desktop  (starts 8 s after login)"
echo "  hotkey      $HOTKEY → $DIR/aria.sh --toggle"
echo "Log file: ~/.cache/aria/aria.log"

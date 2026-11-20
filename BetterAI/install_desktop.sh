#!/usr/bin/env bash
# One-time setup: Mint menu entry, start on login, the Super+Space hotkey and Ctrl+Alt+N quick capture.
# (Not Ctrl+Alt+Space: the Claude desktop app opens on that one, so both came up at once.)
# Run again after moving the project folder.  Undo with: ./install_desktop.sh --remove
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APPS="$HOME/.local/share/applications"
AUTO="$HOME/.config/autostart"
KB_SCHEMA="org.cinnamon.desktop.keybindings"
KB_ROOT="/org/cinnamon/desktop/keybindings/custom-keybindings"
HOTKEY="${ARIA_HOTKEY:-<Super>space}"
CAPTURE_HOTKEY="${ARIA_CAPTURE_HOTKEY:-<Primary><Alt>n}"

remove_binding() {   # id
  list="$(gsettings get $KB_SCHEMA custom-list | sed "s/'$1'//; s/, ,/,/; s/\[, /[/; s/, \]/]/")"
  gsettings set $KB_SCHEMA custom-list "$list"
  dconf reset -f "$KB_ROOT/$1/"
}

add_binding() {      # id name command hotkey
  current="$(gsettings get $KB_SCHEMA custom-list)"
  if ! grep -q "'$1'" <<<"$current"; then
    if [ "$current" = "@as []" ] || [ "$current" = "[]" ]; then new="['$1']"
    else new="${current%]}, '$1']"; fi
    gsettings set $KB_SCHEMA custom-list "$new"
  fi
  gsettings set $KB_SCHEMA.custom-keybinding:$KB_ROOT/$1/ name "$2"
  gsettings set $KB_SCHEMA.custom-keybinding:$KB_ROOT/$1/ command "$3"
  gsettings set $KB_SCHEMA.custom-keybinding:$KB_ROOT/$1/ binding "['$4']"
}

free_key() {         # hotkey: Cinnamon switches the keyboard layout on Super+Space and would swallow it
  local key="org.cinnamon.desktop.keybindings.wm switch-input-source"
  local now; now="$(gsettings get $key 2>/dev/null)" || return 0
  grep -q "'$1'" <<<"$now" || return 0
  gsettings set $key "$(sed "s/'$1', //; s/, '$1'//; s/'$1'//; s/^\[\]$/@as []/" <<<"$now")"
  echo "  (took $1 away from switching the keyboard layout)"
}

if [ "$1" = "--remove" ]; then
  rm -f "$APPS/aria.desktop" "$AUTO/aria.desktop"
  remove_binding aria
  remove_binding aria-capture
  echo "Removed menu entry, autostart and hotkeys."
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

# Cinnamon custom shortcuts
free_key "$HOTKEY"
add_binding aria "Aria" "$DIR/aria.sh --toggle" "$HOTKEY"
add_binding aria-capture "Aria quick capture" "$DIR/aria.sh --capture" "$CAPTURE_HOTKEY"

echo "Installed:"
echo "  menu entry  $APPS/aria.desktop"
echo "  autostart   $AUTO/aria.desktop  (starts 8 s after login)"
echo "  hotkey      $HOTKEY → $DIR/aria.sh --toggle"
echo "  capture     $CAPTURE_HOTKEY → $DIR/aria.sh --capture"
echo "Log file: ~/.cache/aria/aria.log"

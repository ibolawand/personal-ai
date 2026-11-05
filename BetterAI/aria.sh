#!/usr/bin/env bash
# Start Aria, or send a command to the one that's already running.
#   aria.sh            start (or open the text box if she's running)
#   aria.sh --toggle   show/hide the text box (the Ctrl+Alt+Space hotkey), starts Aria if needed
#   aria.sh --quit     shut Aria down
#   aria.sh --chat     make Aria start a conversation now (also --review, --event) — to try it out
# Extra flags for main.py (e.g. --voice) go in Engines/.env as:  ARIA_ARGS=--voice
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="$DIR/.venv/bin/python"
cd "$DIR" || exit 1
LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/aria"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/aria.log"
echo "[$(date '+%F %T')] aria.sh ${1:-start}" >> "$LOG"   # shows whether the hotkey/menu fired at all

case "$1" in
  --toggle|--show) "$PY" -m ui.instance "${1#--}" && exit 0 ;;   # running → done; else start below
  --quit)          "$PY" -m ui.instance quit; exit 0 ;;
  --chat|--review|--event)
                   "$PY" -m ui.instance "${1#--}" || echo "Aria isn't running."; exit 0 ;;
esac

ARGS="$(grep -E '^ARIA_ARGS=' Engines/.env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"')"
# keep the log from growing forever
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5000000 ] && mv "$LOG" "$LOG.old"
echo "=== Aria started $(date '+%F %T') args: $ARGS ===" >> "$LOG"
exec "$PY" -u main.py $ARGS >> "$LOG" 2>&1

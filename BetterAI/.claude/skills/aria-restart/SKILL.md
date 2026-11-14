---
name: aria-restart
description: Use when Aria's code changed and the user wants to try it, when Aria seems stuck, or when asked whether she runs the new code. Restarts Aria correctly and verifies from the log and process start time.
---

# Restart and verify Aria

Aria is one single instance (Unix socket). `./aria.sh` on a running Aria only opens her text box; it does NOT reload code.

```bash
./aria.sh --quit
./aria.sh            # or ./aria.sh --hidden (no orb, as MyNotion's Start button does)
```

## Verify, don't assume
- `ps -o pid,lstart,cmd -p $(pgrep -f "main.py")` and compare the start time with the mtime of the edited files (`stat -c '%y %n' Engines/*.py main.py`). Process older than the edit = old code.
- `tail -n 30 ~/.cache/aria/aria.log`: look for `[App] MyNotion can reach me`, `[Big model]`, tracebacks, tools that failed to register (`_try` logs the label of an engine that couldn't start).
- Speed and problems: `./aria.sh --report` (last 7 days) or `--report 30`.
- Big-model calls: `tail ~/.cache/aria/big_model.log`.

## Notes
- The user often runs commands in their own terminal pane; if you started it from here use `run_in_background`, never a blocking foreground run.
- Settings come from `Engines/.env` (not the root `.env`); changing it also needs a restart.
- Wake-word lines like `0.63 but there's no voice in it: not waking` are normal noise, not errors.

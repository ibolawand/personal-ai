"""
The connection MyNotion's Aria panel uses to talk to Aria.

A second private Unix socket next to the hotkey one (ui/instance.py). That one takes a single word and
closes; this one is a conversation: one JSON object per line, in both directions.

    MyNotion → Aria   {"id": "7", "type": "chat", "text": "what's due this week?"}
                      {"id": "8", "type": "status"}
    Aria → MyNotion   {"id": "7", "type": "text", "delta": "Two "}            the reply, as it's written
                      {"id": "7", "type": "done", "reply": "…", "tools": ["get_due"], "confirm": null}
                      {"id": "8", "type": "status", "ready": true}
                      {"id": "7", "type": "error", "message": "…"}

"done" carries the final reply (it replaces what was streamed) and, in "confirm", a yes/no question that is
waiting for an answer. This module knows nothing about Aria: start() gets the function that runs a turn.
"""

import json
import os
import socket
import threading

SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"aria-{os.getuid()}-app.sock")
MAX_TEXT = 4000         # characters in one message
MAX_LINE = 65536        # bytes in one request line; a longer one closes the connection
SORRY = "Something went wrong on my side."


def _handle(line: bytes, answer, send):
    """One request line → its events."""
    try:
        req = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return send({"id": None, "type": "error", "message": "That wasn't a valid request."})
    if not isinstance(req, dict):
        return send({"id": None, "type": "error", "message": "That wasn't a valid request."})
    rid = req.get("id") if isinstance(req.get("id"), str) else None
    kind = req.get("type")
    if kind == "status":
        return send({"id": rid, "type": "status", "ready": True})
    if kind != "chat":
        return send({"id": rid, "type": "error", "message": "I don't know that kind of request."})
    text = req.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return send({"id": rid, "type": "error", "message": "There was no message."})
    if len(text) > MAX_TEXT:
        return send({"id": rid, "type": "error", "message": f"That message is too long (over {MAX_TEXT} characters)."})
    try:
        reply, tools, confirm = answer(text, lambda delta: delta and send({"id": rid, "type": "text", "delta": delta}))
    except Exception as e:
        print(f"[App] turn failed: {type(e).__name__}: {e}")
        return send({"id": rid, "type": "error", "message": SORRY})
    send({"id": rid, "type": "done", "reply": reply, "tools": list(tools), "confirm": confirm})


def _serve(conn, answer):
    lock = threading.Lock()

    def send(obj):
        try:
            with lock:
                conn.sendall(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        except OSError:
            pass                    # MyNotion closed or went away mid-answer: the turn still finishes

    buf = b""
    with conn:
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if len(line) > MAX_LINE:
                    return
                if line.strip():
                    _handle(line, answer, send)
            if len(buf) > MAX_LINE:
                return


def start(answer, path: str = SOCKET_PATH):
    """Listen in a daemon thread. answer(text, on_text) -> (reply, tool names, pending question or None)."""
    if os.path.exists(path):
        os.unlink(path)             # left over from a crash; a running Aria was ruled out before we got here
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)     # private from the moment it exists (matters if it ever lands in /tmp)
    try:
        server.bind(path)
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)
    server.listen(4)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=_serve, args=(conn, answer), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server

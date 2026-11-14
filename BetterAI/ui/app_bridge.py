"""
The connection MyNotion's Aria panel uses to talk to Aria.

A second private Unix socket next to the hotkey one (ui/instance.py). That one takes a single word and
closes; this one is a conversation: one JSON object per line, in both directions.

    MyNotion → Aria   {"id": "7", "type": "chat", "text": "what's due this week?"}
                      (add "tools": false for an answer only, e.g. "Explain" for selected text)
                      {"id": "8", "type": "status"}
    Aria → MyNotion   {"id": "7", "type": "text", "delta": "Two "}            the reply, as it's written
                      {"id": "7", "type": "done", "reply": "…", "tools": ["get_due"], "confirm": null, "quiz": false}
                      {"id": "8", "type": "status", "ready": true}
                      {"id": "7", "type": "error", "message": "…"}

    "Select text, ask Aria" (she changes nothing herself; MyNotion puts her version in if it's accepted):
    MyNotion → Aria   {"id": "9", "type": "edit", "action": "rewrite|shorter|spelling|table|custom",
                       "html": "<the selection>", "instruction": "", "title": "", "context": "", "previous": ""}
    Aria → MyNotion   {"id": "9", "type": "proposal", "html": "<her version>"}   or an "error" saying why not

    The panel's study buttons, on the note open in MyNotion (answered with "text" … "done", like chat):
    MyNotion → Aria   {"id": "12", "type": "study", "action": "quiz|explain|prep"}

    The cards for upcoming tests, and a quiz for one of them:
    MyNotion → Aria   {"id": "20", "type": "tests"}
                      {"id": "21", "type": "tests", "map": {"subject": "DBI", "notebook": 12}}   (saves the notebook first)
    Aria → MyNotion   {"id": "20", "type": "tests", "cards": [...], "notebooks": [{"id": 12, "name": "Databases"}]}
    MyNotion → Aria   {"id": "22", "type": "study", "action": "test", "test": "20261117-DBI-0800"}

"done" carries the final reply (it replaces what was streamed) and, in "confirm", a yes/no question that is
waiting for an answer, and in "quiz" whether a quiz is running now (the panel then shows Hint, Skip and
Stop). This module knows nothing about Aria: start() gets the function that runs a turn.
"""

import json
import os
import socket
import threading

SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"aria-{os.getuid()}-app.sock")
MAX_TEXT = 4000         # characters in one message
MAX_LINE = 65536        # bytes in one request line; a longer one closes the connection
SORRY = "Something went wrong on my side."
EDIT_ACTIONS = ("rewrite", "shorter", "spelling", "table", "custom")
STUDY_ACTIONS = ("quiz", "explain", "prep", "test")
MAX_SUBJECT = 40        # characters in a subject name
MAX_TEST_ID = 60        # characters in a test id
MAX_HTML = 40000        # characters of selected HTML (and of her previous version, for "Try again")
EDIT_TEXTS = {"instruction": 500, "title": 200, "context": 2000, "previous": MAX_HTML}


def _done(rid, reply, tools, confirm, quiz_active):
    try:
        quiz = bool(quiz_active()) if quiz_active else False
    except Exception as e:
        print(f"[App] couldn't tell whether a quiz is running: {type(e).__name__}: {e}")
        quiz = False
    return {"id": rid, "type": "done", "reply": reply, "tools": list(tools), "confirm": confirm, "quiz": quiz}


def _handle(line: bytes, answer, send, edit=None, study=None, quiz_active=None, tests=None):
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
    if kind == "edit":
        return _handle_edit(rid, req, edit, send)
    if kind == "tests":
        return _handle_tests(rid, req, tests, send)
    if kind == "study":
        return _handle_study(rid, req, study, send, quiz_active)
    if kind != "chat":
        return send({"id": rid, "type": "error", "message": "I don't know that kind of request."})
    text = req.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return send({"id": rid, "type": "error", "message": "There was no message."})
    if len(text) > MAX_TEXT:
        return send({"id": rid, "type": "error", "message": f"That message is too long (over {MAX_TEXT} characters)."})
    try:
        on_text = lambda delta: delta and send({"id": rid, "type": "text", "delta": delta})
        # "tools": false asks for an answer only: she can't change or do anything for this message
        reply, tools, confirm = answer(text, on_text, tools=False) if req.get("tools") is False else answer(text, on_text)
    except Exception as e:
        print(f"[App] turn failed: {type(e).__name__}: {e}")
        return send({"id": rid, "type": "error", "message": SORRY})
    send(_done(rid, reply, tools, confirm, quiz_active))


def _handle_study(rid, req, study, send, quiz_active):
    """A study button: the action in, her answer streamed out like a chat reply."""
    if study is None:
        return send({"id": rid, "type": "error", "message": "I can't help you study right now."})
    action = req.get("action")
    if action not in STUDY_ACTIONS:
        return send({"id": rid, "type": "error", "message": "I don't know that study action."})
    test = req.get("test")
    if action == "test" and not (isinstance(test, str) and 0 < len(test) <= MAX_TEST_ID):
        return send({"id": rid, "type": "error", "message": "I don't know which test you mean."})
    try:
        on_text = lambda delta: delta and send({"id": rid, "type": "text", "delta": delta})
        reply, tools, confirm = study(action, on_text, test=test) if action == "test" else study(action, on_text)
    except Exception as e:
        print(f"[App] study turn failed: {type(e).__name__}: {e}")
        return send({"id": rid, "type": "error", "message": SORRY})
    send(_done(rid, reply, tools, confirm, quiz_active))


def _handle_tests(rid, req, tests, send):
    """The test cards, after saving a subject's notebook if the request carries one."""
    def refuse(message):
        send({"id": rid, "type": "error", "message": message})
    if tests is None:
        return send({"id": rid, "type": "tests", "cards": [], "notebooks": []})
    mapping = None
    if "map" in req:
        m = req["map"]
        if not (isinstance(m, dict) and isinstance(m.get("subject"), str) and 0 < len(m["subject"]) <= MAX_SUBJECT
                and isinstance(m.get("notebook"), int) and not isinstance(m["notebook"], bool)):
            return refuse("That wasn't a valid notebook choice.")
        mapping = (m["subject"], m["notebook"])
    try:
        result = tests(mapping)
    except LookupError:
        return refuse("I couldn't find that notebook.")
    except Exception as e:
        print(f"[App] tests failed: {type(e).__name__}")
        return refuse(SORRY)
    send({"id": rid, "type": "tests", "cards": result["cards"], "notebooks": result["notebooks"]})


def _handle_edit(rid, req, edit, send):
    """"Select text, ask Aria": the selection in, her version of it (or why there is none) out."""
    def refuse(message):
        send({"id": rid, "type": "error", "message": message})
    if edit is None:
        return refuse("I can't change notes right now.")
    action, html = req.get("action"), req.get("html")
    if action not in EDIT_ACTIONS:
        return refuse("I don't know that kind of change.")
    if not isinstance(html, str) or not html.strip():
        return refuse("There was nothing selected.")
    if len(html) > MAX_HTML:
        return refuse("That's too much at once. Select a smaller part.")
    fields = {}
    for name, limit in EDIT_TEXTS.items():
        value = req.get(name, "")
        if not isinstance(value, str) or len(value) > limit:
            return refuse(f"That request wasn't valid ({name}).")
        fields[name] = value
    if action == "custom" and not fields["instruction"].strip():
        return refuse("How should I change it?")
    try:
        new_html, why = edit(action=action, html=html, **fields)
    except Exception as e:
        print(f"[App] edit failed: {type(e).__name__}: {e}")
        return refuse(SORRY)
    if not new_html:
        return refuse(why or SORRY)
    send({"id": rid, "type": "proposal", "html": new_html})


def _serve(conn, answer, edit=None, study=None, quiz_active=None, tests=None):
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
                    _handle(line, answer, send, edit, study, quiz_active, tests)
            if len(buf) > MAX_LINE:
                return


def start(answer, path: str = SOCKET_PATH, edit=None, study=None, quiz_active=None, tests=None):
    """Listen in a daemon thread. answer(text, on_text) -> (reply, tool names, pending question or None);
    edit(action=, html=, instruction=, title=, context=, previous=) -> (new html or None, why not);
    study(action, on_text) -> like answer (for "test": study("test", on_text, test=<id>));
    tests(None, or (subject, notebook id) to save first) -> {"cards": [...], "notebooks": [...]}, LookupError if the
    notebook doesn't exist; quiz_active() -> whether a quiz is running (for "done")."""
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
            threading.Thread(target=_serve, args=(conn, answer, edit, study, quiz_active, tests), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server

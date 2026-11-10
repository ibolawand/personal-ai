"""
The socket MyNotion's Aria panel talks to (ui/app_bridge.py), and Aria.answer_app behind it.
The bridge runs on a temporary socket with a stand-in for Aria; nothing real is started.
"""
import json
import os
import socket
import stat
import threading
import types
import time

import pytest

from ui import app_bridge


def client(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(path)
    return s


def read_events(sock):
    """Lines until the request is over (done / status / error)."""
    events, buf = [], b""
    while True:
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return events
            buf += chunk
        line, buf = buf.split(b"\n", 1)
        events.append(json.loads(line.decode()))
        if events[-1]["type"] in ("done", "status", "error"):
            return events


def ask(sock, obj):
    sock.sendall(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
    return read_events(sock)


@pytest.fixture
def serve(tmp_path):
    """serve(answer) → socket path of a running bridge."""
    servers = []

    def start(answer):
        path = str(tmp_path / f"a{len(servers)}.sock")
        servers.append(app_bridge.start(answer, path))
        return path
    yield start
    for s in servers:
        s.close()


def hi_there(text, on_text):
    on_text("Hi ")
    on_text("there")
    return "Hi there", ["add_note"], None


def test_chat_streams_text_then_done(serve):
    sock = client(serve(hi_there))
    events = ask(sock, {"id": "1", "type": "chat", "text": "hello"})
    assert [e["type"] for e in events] == ["text", "text", "done"]
    assert [e["delta"] for e in events[:2]] == ["Hi ", "there"]
    assert events[-1] == {"id": "1", "type": "done", "reply": "Hi there", "tools": ["add_note"], "confirm": None,
                          "quiz": False}


def test_done_carries_pending_question(serve):
    sock = client(serve(lambda text, on_text: ("Should I?", [], "delete the team meeting")))
    assert ask(sock, {"id": "1", "type": "chat", "text": "delete it"})[-1]["confirm"] == "delete the team meeting"


def test_status(serve):
    sock = client(serve(hi_there))
    assert ask(sock, {"id": "s", "type": "status"}) == [{"id": "s", "type": "status", "ready": True}]


def test_text_is_trimmed_before_it_reaches_aria(serve):
    got = []
    sock = client(serve(lambda text, on_text: (got.append(text), ("ok", [], None))[1]))
    ask(sock, {"id": "1", "type": "chat", "text": "  hello \n"})
    assert got == ["hello"]


@pytest.mark.parametrize("line", [
    "not json",
    '{"id":"1","type":"dance"}',
    '{"id":"1","type":"chat","text":"   "}',
    '{"id":"1","type":"chat","text":"' + "x" * 4001 + '"}',
    '{"id":"1","type":"chat"}',
    '{"id":"1","type":"chat","text":5}',
    "[1,2]",
])
def test_bad_request_gets_error_and_connection_survives(serve, line):
    called = []
    sock = client(serve(lambda text, on_text: (called.append(text), ("ok", [], None))[1]))
    sock.sendall(line.encode() + b"\n")
    events = read_events(sock)
    assert [e["type"] for e in events] == ["error"] and events[0]["message"]
    assert called == []
    assert ask(sock, {"id": "s", "type": "status"})[-1]["ready"] is True


def test_longest_allowed_text_is_accepted(serve):
    sock = client(serve(lambda text, on_text: (str(len(text)), [], None)))
    assert ask(sock, {"id": "1", "type": "chat", "text": "x" * 4000})[-1]["reply"] == "4000"


def test_oversized_line_closes_connection(serve):
    sock = client(serve(hi_there))
    try:
        sock.sendall(b"x" * 70_000)
        assert sock.recv(4096) == b""
    except (BrokenPipeError, ConnectionResetError):
        pass                                    # closed while we were still sending: also fine


def test_answer_raising_gives_error(serve):
    def boom(text, on_text):
        raise RuntimeError("model fell over")
    sock = client(serve(boom))
    events = ask(sock, {"id": "1", "type": "chat", "text": "hello"})
    assert events == [{"id": "1", "type": "error", "message": "Something went wrong on my side."}]
    assert ask(sock, {"id": "s", "type": "status"})[-1]["ready"] is True


def test_client_leaving_mid_turn_does_not_break_server(serve):
    release = threading.Event()

    def slow(text, on_text):
        release.wait(5)
        on_text("too late")
        return "too late", [], None
    path = serve(slow)
    sock = client(path)
    sock.sendall(b'{"id":"1","type":"chat","text":"hello"}\n')
    time.sleep(0.1)
    sock.close()
    release.set()
    time.sleep(0.1)
    assert ask(client(path), {"id": "s", "type": "status"})[-1]["ready"] is True


def test_umlauts_roundtrip(serve):
    got = []

    def answer(text, on_text):
        got.append(text)
        on_text("Schön 😀")
        return "Schön 😀", [], None
    sock = client(serve(answer))
    events = ask(sock, {"id": "1", "type": "chat", "text": "Größe 😀"})
    assert got == ["Größe 😀"]
    assert events[0]["delta"] == "Schön 😀" and events[-1]["reply"] == "Schön 😀"


def test_request_split_across_packets(serve):
    sock = client(serve(hi_there))
    raw = '{"id":"1","type":"chat","text":"Größe"}\n'.encode()
    cut = raw.index("ö".encode()) + 1            # inside the two-byte ö
    sock.sendall(raw[:cut])
    time.sleep(0.05)
    sock.sendall(raw[cut:])
    assert read_events(sock)[-1]["reply"] == "Hi there"


def test_socket_is_private(serve):
    path = serve(hi_there)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_start_replaces_a_leftover_socket_file(serve, tmp_path):
    path = str(tmp_path / "a0.sock")
    old = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old.bind(path)
    old.close()                                  # Aria crashed: the file is still there, nobody listens
    assert serve(hi_there) == path
    assert ask(client(path), {"id": "s", "type": "status"})[-1]["ready"] is True


# ── Aria.answer_app: the turn behind a panel message ──────────────────────────

import main  # noqa: E402,F401  (imported here, before the tests replace subprocess.Popen: see test_model.py)
from conftest import FakeLLM  # noqa: E402


def test_answer_app_runs_a_turn_without_voice(aria):
    aria.llm = FakeLLM(replies=[("Sure thing.", [("add_note", "Added.")])])
    spoken, states = [], []
    aria.speak = lambda t: spoken.append(t)
    aria.ui.set_state = states.append
    pieces = []
    reply, tools, confirm = aria.answer_app("note that I called the bank", pieces.append)
    assert (reply, tools, confirm) == ("Sure thing.", ["add_note"], None)
    assert "".join(pieces) == "Sure thing."
    assert spoken == [] and aria.awake is False
    assert states[0] == "thinking" and states[-1] == "sleeping"


def test_answer_app_leaves_an_awake_aria_listening(aria):
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    aria.awake = True
    states = []
    aria.ui.set_state = states.append
    aria.answer_app("hi")
    assert states[-1] == "listening" and aria.awake is True


def test_answer_app_reports_pending_question_and_yes_resolves_it(aria):
    class Asking(FakeLLM):
        def chat_with_tools(self, *a, **k):
            aria.confirm.request("delete the team meeting", lambda: "Deleted.")
            return super().chat_with_tools(*a, **k)
    aria.llm = Asking(replies=[("Should I delete the team meeting?", [("delete_event", "NEEDS CONFIRMATION")])])
    reply, tools, confirm = aria.answer_app("delete the team meeting")
    assert reply == "Should I delete the team meeting?"          # the question itself is never cut as an "offer"
    assert confirm == "delete the team meeting"
    assert aria.answer_app("yes") == ("Deleted.", ["confirmation"], None)


def test_answer_app_waits_for_a_running_turn(aria):
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    holding, release, result = threading.Event(), threading.Event(), {}

    def other_turn():
        with aria._turn_lock():
            holding.set()
            release.wait(5)
    threading.Thread(target=other_turn, daemon=True).start()
    holding.wait(5)
    worker = threading.Thread(target=lambda: result.update(r=aria.answer_app("hi")), daemon=True)
    worker.start()
    worker.join(0.2)
    assert worker.is_alive() and not result          # still waiting for the other turn
    release.set()
    worker.join(5)
    assert result["r"][0] == "Hey."


def test_answer_app_offers_all_tools(aria):
    aria.llm = FakeLLM(replies=[("Hey.", [])])

    def phone():
        raise AssertionError("the panel must not be limited to the phone's tools")
    aria.tools.phone = phone
    assert aria.answer_app("hi")[0] == "Hey."


def test_bridge_and_answer_app_together(aria, serve):
    aria.llm = FakeLLM(replies=[("On it.", [("add_to_list", "Added milk.")])])
    events = ask(client(serve(aria.answer_app)), {"id": "9", "type": "chat", "text": "add milk to my shopping list"})
    assert events[-1] == {"id": "9", "type": "done", "reply": "On it.", "tools": ["add_to_list"], "confirm": None,
                          "quiz": False}
    assert "".join(e["delta"] for e in events[:-1]) == "On it."


# ── the open note goes along with a panel message (the small model doesn't reliably read it by itself) ──

@pytest.fixture
def open_note(aria, notion, monkeypatch):
    """open_note(title, html) → that note is the one open in MyNotion."""
    import Engines.NotionEngine as N
    monkeypatch.setattr(N, "mynotion_running", lambda: True)

    def make(title, html):
        note_id = notion._create_note(title, html)
        notion._set_state("open_note", str(note_id))
        return note_id
    return make


def test_panel_message_carries_the_open_note(aria, open_note):
    open_note("Schularbeiten stoff", "<h2>Mathe</h2><p>Matrizen bis Seite 40, Größe der Determinante</p>")
    aria.llm = FakeLLM(replies=[("It's your exam topics.", [])])
    aria.answer_app("what is this note about?")
    prompt = aria.llm.prompts[0]
    assert prompt.startswith("what is this note about?")
    assert '"Schularbeiten stoff"' in prompt and "Matrizen bis Seite 40, Größe der Determinante" in prompt
    assert "<p>" not in prompt                                   # as text, not MyNotion's HTML


def test_the_note_text_is_not_kept_in_the_conversation(aria, open_note):
    open_note("Biology", "<p>Mitochondria make ATP</p>")
    aria.llm = FakeLLM(replies=[("Sure.", [])])
    saved = []
    aria.memory.save_message = lambda role, content: saved.append((role, content))
    aria.answer_app("summarise this note")
    assert aria._recent[-1][0] == {"role": "user", "content": "summarise this note"}
    assert ("user", "summarise this note") in saved
    assert not any("Mitochondria" in content for _, content in saved)


def test_no_open_note_adds_nothing(aria):
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    aria.answer_app("hi")
    assert "MyNotion" not in aria.llm.prompts[0]


def test_a_long_open_note_is_cut_and_says_so(aria, open_note):
    open_note("Matrizen", "".join(f"<p>Zeile {i} mit etwas Text darin</p>" for i in range(400)))
    aria.llm = FakeLLM(replies=[("Okay.", [])])
    aria.answer_app("what is this note about?")
    prompt = aria.llm.prompts[0]
    assert "Zeile 0 " in prompt and "Zeile 399 " not in prompt
    assert len(prompt) < 3200
    assert "read_note" in prompt                                 # how to get the rest


def test_the_orb_does_not_get_the_note_text(aria, open_note):
    open_note("Biology", "<p>Mitochondria make ATP</p>")
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    aria.handle_turn("hi", check_state=False)
    assert "Mitochondria" not in aria.llm.prompts[0]


def test_a_broken_notes_database_does_not_stop_the_answer(aria, open_note):
    open_note("Biology", "<p>x</p>")
    aria.notion.open_note = lambda: (_ for _ in ()).throw(RuntimeError("database is locked"))
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    assert aria.answer_app("hi")[0] == "Hey."


# ── small things found in review ──────────────────────────────────────────────

def test_a_panel_message_is_not_written_into_a_dictation(aria):
    from Engines.Dictation import Dictation
    saved = []
    aria.dictation = Dictation(save=lambda text, title: saved.append(text) or "Saved.")
    aria.dictation.start("ideas")
    aria.llm = FakeLLM(replies=[("should never be asked", [])])
    reply, tools, confirm = aria.answer_app("what's due this week?")
    assert "dictat" in reply.lower() and tools == [] and confirm is None
    assert aria.dictation.active and "due this week" not in aria.dictation.text_so_far()
    assert aria.llm.prompts == []


def test_the_orb_goes_back_to_what_it_showed(aria):
    states = []
    aria.ui.set_state = states.append
    aria._track_ui_state()
    aria.ui.set_state("speaking")                 # she is still saying her last voice reply
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    aria.answer_app("hi")
    assert states == ["speaking", "thinking", "speaking"]


def test_the_orb_is_left_alone_if_it_changed_meanwhile(aria):
    states = []
    aria.ui.set_state = states.append
    aria._track_ui_state()
    aria.ui.set_state("speaking")

    class Meanwhile(FakeLLM):
        def chat_with_tools(self, *a, **k):
            aria.ui.set_state("listening")        # the voice reply ended during the panel turn
            return super().chat_with_tools(*a, **k)
    aria.llm = Meanwhile(replies=[("Hey.", [])])
    aria.answer_app("hi")
    assert states[-1] == "listening" and states.count("speaking") == 1


def test_flashes_are_not_remembered_as_the_orbs_state(aria):
    states = []
    aria.ui.set_state = states.append
    aria._track_ui_state()
    aria.ui.set_state("sleeping")
    aria.ui.set_state("alert")                    # a flash, not a state
    aria.llm = FakeLLM(replies=[("Hey.", [])])
    aria.answer_app("hi")
    assert states[-1] == "sleeping"


def test_every_thread_gets_the_same_turn_lock(aria):
    locks = []
    start = threading.Barrier(8)

    def grab():
        start.wait()
        locks.append(aria._turn_lock())
    threads = [threading.Thread(target=grab) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({id(lock) for lock in locks}) == 1


def test_the_socket_is_never_open_to_others(serve, tmp_path, monkeypatch):
    """Private from the moment it exists, not only after the chmod."""
    seen = []
    real_bind = socket.socket.bind

    class Watching(socket.socket):
        def bind(self, path):
            real_bind(self, path)
            seen.append(stat.S_IMODE(os.stat(path).st_mode))
    monkeypatch.setattr(app_bridge.socket, "socket", Watching)
    old = os.umask(0o022)
    try:
        serve(hi_there)
        assert os.umask(0o022) == 0o022           # and the process's own umask is put back
    finally:
        os.umask(old)
    assert seen == [0o600]


# ── "Select text, ask Aria": the edit request ─────────────────────────────────

@pytest.fixture
def serve_edit(tmp_path):
    servers = []

    def start(edit):
        path = str(tmp_path / f"e{len(servers)}.sock")
        servers.append(app_bridge.start(hi_there, path, edit=edit))
        return path
    yield start
    for s in servers:
        s.close()


def test_edit_request_returns_a_proposal(serve_edit):
    got = []

    def edit(**kw):
        got.append(kw)
        return "<p>Kürzer.</p>", ""
    sock = client(serve_edit(edit))
    events = ask_edit(sock, {"id": "e1", "type": "edit", "action": "shorter", "html": "<p>Ein langer Satz.</p>",
                             "title": "Bio", "context": "davor danach", "previous": "<p>alt</p>", "instruction": "kurz"})
    assert events == [{"id": "e1", "type": "proposal", "html": "<p>Kürzer.</p>"}]
    assert got == [{"action": "shorter", "html": "<p>Ein langer Satz.</p>", "instruction": "kurz", "title": "Bio",
                    "context": "davor danach", "previous": "<p>alt</p>"}]


def ask_edit(sock, obj):
    sock.sendall(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
    events, buf = [], b""
    while True:
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                return events
            buf += chunk
        line, buf = buf.split(b"\n", 1)
        events.append(json.loads(line.decode()))
        if events[-1]["type"] in ("proposal", "error"):
            return events


def test_edit_without_a_proposal_gives_the_reason(serve_edit):
    sock = client(serve_edit(lambda **kw: (None, "I found no mistakes in that part.")))
    events = ask_edit(sock, {"id": "e1", "type": "edit", "action": "spelling", "html": "<p>Alles gut.</p>"})
    assert events == [{"id": "e1", "type": "error", "message": "I found no mistakes in that part."}]


@pytest.mark.parametrize("req", [
    {"action": "dance", "html": "<p>x</p>"},
    {"action": "shorter"},
    {"action": "shorter", "html": "   "},
    {"action": "shorter", "html": 5},
    {"action": "shorter", "html": "x" * 40001},
    {"action": "custom", "html": "<p>x</p>"},                          # an own instruction, but none given
    {"action": "custom", "html": "<p>x</p>", "instruction": "y" * 501},
    {"action": "shorter", "html": "<p>x</p>", "title": 7},
    {"action": "shorter", "html": "<p>x</p>", "previous": "x" * 40001},
])
def test_bad_edit_request_is_refused_before_aria_sees_it(serve_edit, req):
    called = []
    sock = client(serve_edit(lambda **kw: (called.append(kw), ("<p>y</p>", ""))[1]))
    events = ask_edit(sock, {"id": "e1", "type": "edit", **req})
    assert [e["type"] for e in events] == ["error"] and events[0]["message"] and called == []
    assert ask(sock, {"id": "s", "type": "status"})[-1]["ready"] is True


def test_edit_that_raises_gives_a_plain_error(serve_edit):
    def boom(**kw):
        raise RuntimeError("model fell over")
    sock = client(serve_edit(boom))
    events = ask_edit(sock, {"id": "e1", "type": "edit", "action": "shorter", "html": "<p>x</p>"})
    assert events == [{"id": "e1", "type": "error", "message": "Something went wrong on my side."}]


def test_edit_on_an_aria_that_cannot_edit(serve):
    sock = client(serve(hi_there))                                    # started without an edit function
    events = ask_edit(sock, {"id": "e1", "type": "edit", "action": "shorter", "html": "<p>x</p>"})
    assert [e["type"] for e in events] == ["error"]


class Writer:
    def __init__(self, result=("<p>Kurz.</p>", "")):
        self.result, self.calls = result, []

    def rework(self, html, action, instruction="", title="", context="", previous=""):
        self.calls.append((html, action, instruction, title, context, previous))
        return self.result


def test_edit_app_asks_the_writer_and_is_not_a_conversation(aria):
    aria.writer = Writer()
    saved, states = [], []
    aria.memory.save_message = lambda role, content: saved.append((role, content))
    aria.ui.set_state = states.append
    aria.speak = lambda t: saved.append(("spoken", t))
    out = aria.edit_app(action="shorter", html="<p>Lang.</p>", instruction="", title="Bio", context="c", previous="")
    assert out == ("<p>Kurz.</p>", "")
    assert aria.writer.calls == [("<p>Lang.</p>", "shorter", "", "Bio", "c", "")]
    assert saved == [] and list(aria._recent) == [] and aria.llm.prompts == []
    assert states[0] == "thinking" and states[-1] == "sleeping"


def test_edit_app_waits_for_a_running_turn(aria):
    aria.writer = Writer()
    holding, release, result = threading.Event(), threading.Event(), {}

    def other_turn():
        with aria._turn_lock():
            holding.set()
            release.wait(5)
    threading.Thread(target=other_turn, daemon=True).start()
    holding.wait(5)
    worker = threading.Thread(target=lambda: result.update(r=aria.edit_app(action="shorter", html="<p>x</p>")),
                              daemon=True)
    worker.start()
    worker.join(0.2)
    assert worker.is_alive() and aria.writer.calls == []
    release.set()
    worker.join(5)
    assert result["r"][0] == "<p>Kurz.</p>"


def test_edit_app_without_notes_says_so(aria):
    aria.writer = None
    html, why = aria.edit_app(action="shorter", html="<p>x</p>")
    assert html is None and why


def test_edit_app_puts_the_orb_back(aria):
    aria.writer = Writer()
    states = []
    aria.ui.set_state = states.append
    aria._track_ui_state()
    aria.ui.set_state("speaking")
    aria.edit_app(action="shorter", html="<p>x</p>")
    assert states == ["speaking", "thinking", "speaking"]


def test_bridge_and_edit_app_together(aria, tmp_path):
    aria.writer = Writer(("<p>Größe 😀</p>", ""))
    path = str(tmp_path / "both.sock")
    server = app_bridge.start(aria.answer_app, path, edit=aria.edit_app)
    try:
        events = ask_edit(client(path), {"id": "e9", "type": "edit", "action": "rewrite", "html": "<p>Grösse</p>"})
    finally:
        server.close()
    assert events == [{"id": "e9", "type": "proposal", "html": "<p>Größe 😀</p>"}]


# ── "Explain" for selected text: an answer only, never a tool (the model once translated the whole note) ──

class Recording(FakeLLM):
    def chat_with_tools(self, prompt, history, system_prompt, tools, execute, on_text=None, **k):
        self.offered = getattr(self, "offered", []) + [list(tools)]
        return super().chat_with_tools(prompt, history, system_prompt, tools, execute, on_text=on_text, **k)


def test_a_message_without_tools_offers_the_model_none(aria):
    aria.tools = types.SimpleNamespace(schemas=["edit_note", "play_song"], execute=lambda n, a: "",
                                       schemas_for=lambda text, recent=(): ["edit_note"])
    aria.llm = Recording(replies=[("It means the cell's power plant.", [])])
    reply, tools, _ = aria.answer_app("Explain this part of my note simply:\npowerhouse of the cell", tools=False)
    assert reply == "It means the cell's power plant." and tools == []
    assert aria.llm.offered == [[]]


def test_a_message_without_tools_is_never_retried_with_tools(aria):
    aria.tools = types.SimpleNamespace(schemas=["edit_note", "play_song"], execute=lambda n, a: "",
                                       schemas_for=lambda text, recent=(): ["edit_note"])
    # "I can't" normally means a missing tool (retry with all of them); "I'll translate it" claims an action
    aria.llm = Recording(replies=[("I can't do that, sorry.", []), ("never asked", [])])
    aria.answer_app("translate and explain this part of my note", tools=False)
    aria.llm.replies = [("I'll translate it now.", []), ("never asked", [])]
    aria.answer_app("translate this part of my note", tools=False)
    assert aria.llm.offered == [[], []]


def test_a_normal_panel_message_still_gets_tools(aria):
    aria.tools = types.SimpleNamespace(schemas=["edit_note", "play_song"], execute=lambda n, a: "",
                                       schemas_for=lambda text, recent=(): ["edit_note"])
    aria.llm = Recording(replies=[("Sure.", [])])
    aria.answer_app("hi")
    assert aria.llm.offered == [["edit_note"]]


def test_the_bridge_passes_no_tools_on(serve):
    got = []

    def answer(text, on_text, tools=True):
        got.append(tools)
        return "ok", [], None
    sock = client(serve(answer))
    ask(sock, {"id": "1", "type": "chat", "text": "explain", "tools": False})
    ask(sock, {"id": "2", "type": "chat", "text": "hello"})
    ask(sock, {"id": "3", "type": "chat", "text": "hello", "tools": "no"})      # only a real false switches them off
    assert got == [False, True, True]


# ── the panel's study buttons: the study request, and the quiz flag on every reply ──

@pytest.fixture
def serve_study(tmp_path):
    """serve_study(study, quiz_active=None) → socket path of a bridge that can study."""
    servers = []

    def start(study, quiz_active=None):
        path = str(tmp_path / f"s{len(servers)}.sock")
        servers.append(app_bridge.start(hi_there, path, study=study, quiz_active=quiz_active))
        return path
    yield start
    for s in servers:
        s.close()


def prep(action, on_text):
    on_text("Point one. ")
    return "Point one. Point two.", [], None


def test_study_request_streams_and_finishes(serve_study):
    events = ask(client(serve_study(prep, lambda: False)), {"id": "s1", "type": "study", "action": "prep"})
    assert events[0] == {"id": "s1", "type": "text", "delta": "Point one. "}
    assert events[-1] == {"id": "s1", "type": "done", "reply": "Point one. Point two.", "tools": [],
                          "confirm": None, "quiz": False}


def test_study_passes_the_action(serve_study):
    got = []
    path = serve_study(lambda action, on_text: got.append(action) or ("Quiz on X.", ["start_quiz"], None),
                       lambda: True)
    events = ask(client(path), {"id": "s2", "type": "study", "action": "quiz"})
    assert got == ["quiz"]
    assert events[-1]["quiz"] is True and events[-1]["tools"] == ["start_quiz"]


@pytest.mark.parametrize("action", ["summarise", None, 3])
def test_unknown_study_action_is_refused(serve_study, action):
    got = []
    sock = client(serve_study(lambda a, on_text: got.append(a) or ("x", [], None)))
    events = ask(sock, {"id": "s3", "type": "study", "action": action})
    assert events == [{"id": "s3", "type": "error", "message": "I don't know that study action."}]
    assert got == []


def test_study_on_an_aria_that_cannot_study(serve):
    events = ask(client(serve(hi_there)), {"id": "s4", "type": "study", "action": "explain"})
    assert [e["type"] for e in events] == ["error"]


def test_study_that_raises_gives_a_plain_error(serve_study):
    def broken(action, on_text):
        raise RuntimeError("boom")
    events = ask(client(serve_study(broken)), {"id": "s5", "type": "study", "action": "explain"})
    assert events == [{"id": "s5", "type": "error", "message": app_bridge.SORRY}]


def test_done_reports_quiz_state_after_a_chat(serve_study):
    events = ask(client(serve_study(prep, lambda: True)), {"id": "c1", "type": "chat", "text": "skip"})
    assert events[-1]["type"] == "done" and events[-1]["quiz"] is True


def test_quiz_flag_is_false_when_the_check_fails(serve_study):
    def broken():
        raise RuntimeError("boom")
    events = ask(client(serve_study(prep, broken)), {"id": "c2", "type": "chat", "text": "hi"})
    assert events[-1]["type"] == "done" and events[-1]["quiz"] is False


def test_aria_wires_study_and_the_quiz_flag(aria, monkeypatch):
    seen = {}
    monkeypatch.setattr(app_bridge, "start", lambda answer, path=None, **kw: seen.update(kw))
    aria.notion = None
    aria._start_app_bridge()
    assert seen["study"] == aria._app_study
    assert seen["quiz_active"]() is False
    aria.quiz = types.SimpleNamespace(active={"i": 0})
    assert seen["quiz_active"]() is True


# ── a panel turn's cards don't pop up a hidden orb ──

class QuietUI(main.NullUI):
    def __init__(self):
        self.quiet = 0
        self.seen = []

    def panel_turn(self):
        import contextlib
        ui = self

        @contextlib.contextmanager
        def turn():
            ui.quiet += 1
            try:
                yield
            finally:
                ui.quiet -= 1
        return turn()


class CardLLM(FakeLLM):
    def __init__(self, ui, **k):
        super().__init__(**k)
        self.ui = ui

    def chat_with_tools(self, *a, **k):
        self.ui.seen.append(self.ui.quiet)
        return super().chat_with_tools(*a, **k)


@pytest.mark.parametrize("call", [lambda a: a.answer_app("add eggs"), lambda a: a.study_app("explain")])
def test_panel_turns_are_quiet_for_cards(aria, open_note, call):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.ui = QuietUI()
    aria.llm = CardLLM(aria.ui, replies=[("Done.", [])])
    call(aria)
    assert aria.ui.seen and set(aria.ui.seen) == {1} and aria.ui.quiet == 0   # a retry is quiet too


def test_a_ui_without_panel_turns_still_works(aria):
    aria.llm = FakeLLM(replies=[("Hi.", [])])
    assert aria.answer_app("hi")[0] == "Hi."

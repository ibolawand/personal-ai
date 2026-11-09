"""
The socket MyNotion's Aria panel talks to (ui/app_bridge.py), and Aria.answer_app behind it.
The bridge runs on a temporary socket with a stand-in for Aria; nothing real is started.
"""
import json
import os
import socket
import stat
import threading
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
    assert events[-1] == {"id": "1", "type": "done", "reply": "Hi there", "tools": ["add_note"], "confirm": None}


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
    assert events[-1] == {"id": "9", "type": "done", "reply": "On it.", "tools": ["add_to_list"], "confirm": None}
    assert "".join(e["delta"] for e in events[:-1]) == "On it."

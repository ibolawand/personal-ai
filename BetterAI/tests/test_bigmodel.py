"""Heavy text work goes to Claude through the claude program (Engines/BigModel.py). Nothing is really started here."""

import json
import subprocess
import types

from main import tidy_reply
from Engines.BigModel import MARK, BigModel, wanted


class Claude:
    """Stands in for subprocess.run: records what was started and answers like `claude -p --output-format json`."""
    def __init__(self, *answers):
        self.answers, self.started = list(answers), []

    def __call__(self, args, **kw):
        self.started.append((args, kw))
        answer = self.answers.pop(0) if self.answers else "ok"
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict):
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(answer), stderr="")
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"is_error": False, "result": answer}), stderr="")


def big(*answers, **kw):
    run = Claude(*answers)
    return BigModel(command="/opt/claude", run=run, enabled=True, **kw), run


# ── the call ──

def test_claude_gets_the_text_and_nothing_else(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-would-cost-money")
    model, run = big("  Tidy text. ")
    assert model.ask("Tidy this: a  b", "note") == "Tidy text."
    args, kw = run.started[0]
    assert kw["input"] == "Tidy this: a  b"                       # the text goes in on stdin, not on the command line
    assert args[args.index("--tools") + 1] == ""                  # no tools: it can't read or change a file
    assert "--strict-mcp-config" in args and args[args.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in args
    assert "ANTHROPIC_API_KEY" not in kw["env"]                   # the subscription, never a paid API key
    assert kw["cwd"].endswith("big_model_cwd")                    # an empty folder, not the project
    assert model.calls == 1


def test_no_answer_means_none_and_the_local_model_takes_over_for_a_while():
    for failure in (subprocess.TimeoutExpired("claude", 120), OSError("no network"),
                    {"is_error": True, "result": "Usage limit reached"}, ""):
        model, run = big(failure, "would work now")
        assert model.ask("hello") is None
        assert model.calls == 0
        assert not model.available and model.ask("again") is None     # not tried again right away
        assert len(run.started) == 1


def test_off_or_not_installed_starts_nothing(monkeypatch):
    run = Claude()
    assert BigModel(command="/opt/claude", run=run, enabled=False).ask("hello") is None
    monkeypatch.setenv("ARIA_BIG_MODEL", "0")
    assert BigModel(command="/opt/claude", run=run).ask("hello") is None
    monkeypatch.setenv("ARIA_BIG_MODEL", "1")
    monkeypatch.setenv("ARIA_BIG_CMD", "/nowhere/claude")
    assert BigModel(run=run).ask("hello") is None
    assert run.started == []


def test_each_call_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    model, _ = big("done")
    model.ask("Organise this note:\nline one", "note")
    log = (tmp_path / "aria" / "big_model.log").read_text()
    assert "note" in log and "chars sent" in log and "ok" in log and "Organise this note: line one" in log


def test_asking_for_it_by_name():
    assert wanted("ask the big model why the sky is blue") == "why the sky is blue"
    assert wanted("Frag die große KI, was eine Differentialgleichung ist") == "was eine Differentialgleichung ist"
    assert wanted("aria, frag mal claude: wie geht partielle Integration?") == "wie geht partielle Integration?"
    for text in ("ask Sara if she's coming", "what is a big model?", "frag mich was", "ask the big model"):
        assert wanted(text) is None, text


# ── where Aria uses it ──

def test_the_note_writer_asks_claude_first_and_the_local_model_when_it_fails():
    model, run = big("from claude", OSError("offline"))
    local = lambda prompt, history=(), temperature=0.3: "from the laptop"
    ask = model.or_local(local)
    history = [{"role": "user", "content": "Organise it"}, {"role": "assistant", "content": "first try"}]
    assert ask("That lost a formula. Again.", history=history) == "from claude"
    sent = run.started[0][1]["input"]
    assert "Organise it" in sent and "first try" in sent and sent.endswith("That lost a formula. Again.")
    assert ask("once more") == "from the laptop"


def test_a_note_made_from_her_last_answer_stays_on_the_laptop(notion):
    from Engines.NoteWriter import NoteWriter
    model, run = big("claude's note")
    writer = NoteWriter(notion, ask=lambda prompt, history=(), temperature=0.3: "The **local** note.")
    writer.local, writer.ask = writer.ask, model.or_local(writer.ask)
    notion.last_reply = lambda: "Mr Huber wrote: the test moves to Friday."       # could be mail
    writer.write_note("Test date", "", from_last_answer=True)
    assert run.started == []
    writer.write_note("Photosynthesis", "how plants make sugar")
    assert len(run.started) == 1


def test_ask_the_big_model_is_answered_by_claude_and_marked(aria):
    aria.big, run = big("Because of Rayleigh scattering.")
    reply, used = aria.handle_turn("ask the big model why the sky is blue", check_state=False)
    assert reply == f"Because of Rayleigh scattering.\n\n{MARK}"
    assert used[0][0] == "big_model" and aria.llm.prompts == []           # the local model wasn't asked
    assert run.started[0][1]["input"] == "why the sky is blue"            # only the question went out
    assert aria._recent[-1][-1]["content"] == "Because of Rayleigh scattering."     # the mark isn't remembered
    assert tidy_reply(reply) == reply


def test_the_open_note_goes_along_only_when_the_question_is_about_it(aria):
    aria.big, run = big("a", "b")
    note = "\n[The note open in MyNotion right now …secret plans…]"
    aria.handle_turn("ask the big model what 7 times 8 is", check_state=False, extra=note)
    aria.handle_turn("frag die große KI was diese Notiz bedeutet", check_state=False, extra=note)
    assert "secret plans" not in run.started[0][1]["input"]
    assert "secret plans" in run.started[1][1]["input"]


def test_when_claude_cant_be_reached_she_says_so(aria):
    aria.big, _ = big(OSError("offline"))
    reply, _ = aria.handle_turn("ask the big model why the sky is blue", check_state=False)
    assert "couldn't reach the big model" in reply and MARK not in reply


def test_explain_goes_to_claude_and_falls_back_to_the_local_model(aria):
    aria.big, run = big("Simply put: slopes.", OSError("offline"))
    reply, _ = aria.handle_turn("Explain this note simply", check_state=False, extra="\n[The note: y' = 2x]",
                                use_tools=False)
    assert reply.startswith("Simply put: slopes.") and reply.endswith(MARK)
    assert "y' = 2x" in run.started[0][1]["input"]
    aria.llm.replies = [("It is about slopes.", [])]
    reply, _ = aria.handle_turn("Explain this note simply", check_state=False, extra="\n[The note: y' = 2x]",
                                use_tools=False)
    assert reply == "It is about slopes."                                  # local, and not marked


def test_an_ordinary_message_never_leaves_the_laptop(aria):
    aria.big, run = big("should not be used")
    aria.llm.replies = [("Hey you.", [])]
    reply, _ = aria.handle_turn("hi aria, read my last email", check_state=False)
    assert run.started == [] and MARK not in reply


def test_a_tool_that_used_claude_marks_the_reply(aria):
    aria.big, _ = big("tidied")
    aria.tools.execute = lambda name, args: aria.big.ask("the note", "note") and "Organised 'Maths'."

    def chat_with_tools(prompt, history, system_prompt, tools, execute, on_text=None, **_):
        aria.llm.last_trace = []
        return execute("organize_note", {}), [("organize_note", "Organised 'Maths'.")]
    aria.llm.chat_with_tools = chat_with_tools
    reply, _ = aria.handle_turn("organise my maths note", check_state=False)
    assert reply == f"Organised 'Maths'.\n\n{MARK}"


def test_quiz_questions_come_from_claude_when_it_answers():
    from Engines.Quiz import Quiz
    quiz = Quiz.__new__(Quiz)
    quiz.model = "none"
    quiz.big, _ = big('Here you go:\n```json\n{"questions": [{"q": "What is the derivative of x squared", "a": "two x"}]}\n```')
    assert quiz.make_questions("Maths", "The derivative of x squared is two x.", 1) == \
        [{"q": "What is the derivative of x squared?", "a": "two x"}]

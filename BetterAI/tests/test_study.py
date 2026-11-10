"""The study buttons in MyNotion's Aria panel: Quiz me, Explain simply and Test prep, all on the open note
(Aria.study_app). The model is faked."""
import json

import pytest

import Engines.Quiz as Q
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)
from conftest import FakeLLM

NOTE = ("<h2>Normal forms</h2><p>First normal form means every column holds one value. Second normal form removes "
        "partial dependencies on a composite key. Third normal form removes transitive dependencies, so every "
        "non-key column depends on the key, the whole key and nothing but the key. A join combines rows from two "
        "tables using a related column.</p>")
QUESTIONS = [{"q": "What does third normal form remove?", "a": "transitive dependencies"},
             {"q": "What combines rows from two tables?", "a": "a join"}]


class Recording(FakeLLM):
    def chat_with_tools(self, prompt, history, system_prompt, tools, execute, on_text=None, **k):
        self.offered = getattr(self, "offered", []) + [list(tools)]
        return super().chat_with_tools(prompt, history, system_prompt, tools, execute, on_text=on_text, **k)


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


@pytest.fixture
def study_quiz(aria, notion, monkeypatch, tmp_path):
    """A real Quiz on Aria, with the model's questions and judgements faked."""
    monkeypatch.setattr(Q, "STATE_FILE", str(tmp_path / "quiz.json"))

    def fake_chat(model, messages, **kw):
        if "quiz questions" in messages[0]["content"]:
            return {"message": {"content": json.dumps({"questions": QUESTIONS})}}
        return {"message": {"content": json.dumps({"correct": False})}}
    monkeypatch.setattr(Q.ollama, "chat", fake_chat)
    aria.quiz = Q.Quiz(notion)
    return aria.quiz


def test_no_open_note(aria):
    assert aria.study_app("explain") == ("Open a note first, then I can help you study it.", [], None)


def test_empty_note(aria, open_note):
    open_note("Leer", "<p> </p>")
    assert aria.study_app("prep") == ("This note is empty, there's nothing to study yet.", [], None)


def test_refused_while_dictating(aria, open_note):
    from Engines.Dictation import Dictation
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.dictation = Dictation(save=lambda text, title: "Saved.")
    aria.dictation.start("ideas")
    aria.llm = FakeLLM(replies=[("should never be asked", [])])
    reply, tools, confirm = aria.study_app("quiz")
    assert "dictating" in reply and tools == [] and confirm is None
    assert aria.llm.prompts == []


def test_explain_gets_the_note_and_no_tools(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.llm = Recording(replies=[("They're the cell's power plants.", [])])
    reply, tools, _ = aria.study_app("explain")
    assert reply == "They're the cell's power plants." and tools == []
    assert aria.llm.offered == [[]]
    assert aria.llm.prompts[0].startswith("Explain this note simply")
    assert "Mitochondria make ATP" in aria.llm.prompts[0] and "plain, simple language" in aria.llm.prompts[0]
    assert not any("Mitochondria" in m["content"] for turn in aria._recent for m in turn)


def test_prep_uses_its_own_instruction(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.llm = Recording(replies=[("1. ATP.", [])])
    aria.study_app("prep")
    assert aria.llm.prompts[0].startswith("Test prep for this note")
    assert "3 questions a teacher" in aria.llm.prompts[0]
    assert aria.llm.offered == [[]]


def test_a_long_note_is_cut_and_the_reply_says_so(aria, open_note):
    open_note("Lang", "".join(f"<p>Zeile {i} mit etwas Text darin</p>" for i in range(1000)))
    aria.llm = FakeLLM(replies=[("Main ideas.", [])])
    reply, _, _ = aria.study_app("explain")
    assert reply.endswith("(I only covered the first part of this note, it's long.)")
    assert "Zeile 0 " in aria.llm.prompts[0] and "Zeile 999 " not in aria.llm.prompts[0]


def test_a_short_note_is_not_said_to_be_cut(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.llm = FakeLLM(replies=[("Main ideas.", [])])
    assert aria.study_app("explain")[0] == "Main ideas."


def test_quiz_starts_on_the_open_note(aria, open_note, study_quiz):
    open_note("Kapitel 3", NOTE)
    reply, tools, confirm = aria.study_app("quiz")
    assert reply.startswith("Quiz on Kapitel 3") and tools == ["start_quiz"] and confirm is None
    assert study_quiz.active["title"] == "Kapitel 3"
    assert aria._recent[-1][0] == {"role": "user", "content": "Quiz me on this note"}


def test_quiz_buttons_are_answered_in_code(aria, open_note, study_quiz):
    open_note("Kapitel 3", NOTE)
    aria.study_app("quiz")
    aria.llm = FakeLLM(replies=[("should never be asked", [])])
    assert aria.answer_app("hint")[0].startswith("It starts with")
    assert aria.answer_app("skip")[0].startswith(("No worries", "It's", "The answer"))
    aria.answer_app("stop")
    assert study_quiz.active is None
    assert aria.llm.prompts == []


def test_study_buttons_are_not_taken_as_quiz_answers(aria, open_note, study_quiz):
    open_note("Kapitel 3", NOTE)
    aria.study_app("quiz")
    aria.llm = FakeLLM(replies=[("Simple version.", [])])
    assert aria.study_app("explain")[0] == "Simple version."
    assert study_quiz.active is None


def test_quiz_again_starts_a_fresh_quiz(aria, open_note, study_quiz):
    open_note("Kapitel 3", NOTE)
    aria.study_app("quiz")
    aria.answer_app("skip")
    assert aria.study_app("quiz")[0].startswith("Quiz on Kapitel 3")
    assert study_quiz.active["i"] == 0


def test_quiz_on_a_tiny_note_says_so(aria, open_note, study_quiz):
    open_note("Stub", "<h1>Title</h1>")
    assert "doesn't have enough in it" in aria.study_app("quiz")[0]


def test_study_leaves_a_pending_question_alone(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.confirm.request("delete the event Test", lambda: "Deleted.")
    aria.llm = FakeLLM(replies=[("Explained.", [])])
    aria.study_app("explain")
    assert aria.confirm.pending

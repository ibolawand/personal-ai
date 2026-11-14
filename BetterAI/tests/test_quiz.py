"""Quiz me: finding the material, and answers handled in code (the model is faked)."""
import json

import pytest

import Engines.Quiz as Q
from Engines.NotionEngine import html_to_text
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

NOTE = ("<h2>Normal forms</h2><p>First normal form means every column holds one value. Second normal form removes "
        "partial dependencies on a composite key. Third normal form removes transitive dependencies, so every "
        "non-key column depends on the key, the whole key and nothing but the key. A join combines rows from two "
        "tables using a related column.</p>")
QUESTIONS = [{"q": "What does third normal form remove?", "a": "transitive dependencies"},
             {"q": "What combines rows from two tables?", "a": "a join"},
             {"q": "What does first normal form require of each column", "a": "one value"}]


@pytest.fixture
def quiz(notion, monkeypatch, tmp_path):
    monkeypatch.setattr(Q, "STATE_FILE", str(tmp_path / "quiz.json"))
    notion._create_note("Databases", NOTE)
    notion._create_note("Shopping list", "<p>eggs</p>")
    calls = []

    def fake_chat(model, messages, **kw):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if "quiz questions" in prompt:
            return {"message": {"content": json.dumps({"questions": QUESTIONS})}}
        return {"message": {"content": json.dumps({"correct": "3NF" in prompt.split("Student said:")[1]})}}
    monkeypatch.setattr(Q.ollama, "chat", fake_chat)
    qz = Q.Quiz(notion)
    qz.calls = calls
    return qz


def test_start_finds_the_note_and_asks_the_first_question(quiz):
    out = quiz.start("databases", 3)
    assert out.startswith(Q.FINAL_PREFIX + "Quiz on Databases, 3 questions.")
    assert out.endswith("First one: What does third normal form remove?")
    assert "transitive dependencies" in quiz.calls[0]          # the note text went to the model
    assert quiz.active["questions"][2]["q"].endswith("?")       # missing question mark added


def test_a_full_round_right_wrong_skip(quiz):
    quiz.start("databases", 3)
    r1 = quiz.answer("um, it removes transitive dependencies")
    assert r1.split()[0] in ("Yes!", "Correct.", "Exactly.", "That's", "Nice,") and "Next: What combines" in r1
    assert len(quiz.calls) == 1                                 # checked in code, no model call
    r2 = quiz.answer("a foreign key")
    assert "it's a join" in r2 and "Last one: What does first normal form" in r2
    r3 = quiz.answer("i don't know")
    assert "one value" in r3 and "You got 1 out of 3." in r3 and "quiz me on my mistakes" in r3
    assert quiz.active is None


def test_the_model_judges_answers_in_other_words(quiz):
    quiz.start("databases", 3)
    quiz.active["questions"][0] = {"q": "Which normal form removes transitive dependencies?", "a": "third normal form"}
    reply = quiz.answer("3NF")
    assert reply.startswith(("Yes!", "Correct.", "Exactly.", "That's it.", "Nice, right."))
    assert "(third normal form)" in reply                      # says the full answer when it was worded differently
    assert len(quiz.calls) == 2                                 # this one needed the model


def test_repeat_hint_and_stop(quiz):
    quiz.start("databases", 3)
    assert quiz.answer("what was the question") == "What does third normal form remove?"
    assert quiz.answer("hint").startswith("It starts with 'T', 2 words.")
    assert quiz.active["i"] == 0                                # neither counts as an answer
    assert quiz.answer("stop the quiz") == "Okay, quiz stopped."
    assert quiz.active is None


def test_mistakes_are_kept_and_can_be_retried(quiz):
    quiz.start("databases", 3)
    quiz.answer("transitive dependencies")
    quiz.answer("skip")
    quiz.answer("skip")
    retry = quiz.start("my mistakes")
    assert "2 questions from your mistakes" in retry
    first, second = quiz.active["questions"]
    quiz.answer(first["a"])                                     # got it right this time
    quiz.answer("stop")
    assert [m["q"] for m in quiz._load()["misses"]] == [second["q"]]


def test_a_retried_mistake_keeps_the_note_it_came_from(quiz):
    quiz._save_misses("Whatever", [{"q": "Q1?", "a": "a1", "source": "Databases"}])
    data = quiz._load()
    data["misses"].append({"q": "Q2?", "a": "a2", "at": 1})          # an old miss that has no source
    with open(Q.STATE_FILE, "w") as f:
        json.dump(data, f)
    quiz.start("my mistakes")
    quiz.answer("skip")
    quiz.answer("skip")
    assert {m["q"]: m["source"] for m in quiz._load()["misses"]} == {"Q1?": "Databases", "Q2?": "your mistakes"}


def test_nothing_found_and_too_short(quiz, notion):
    assert quiz.start("astrophysics") == "I couldn't find a note or document about 'astrophysics'."
    assert "doesn't have enough" in quiz.start("shopping list")
    assert quiz.start("my mistakes") == "You haven't missed anything yet, there's nothing to retry."


def test_documents_are_used_for_pdfs(quiz, tmp_path):
    from pathlib import Path
    doc = tmp_path / "gear_trains.pdf"
    doc.write_text("x")

    class Files:
        last_results = []

        def search_contents(self, q):
            self.last_results = [doc]
            return "Found 1"

        def _extract(self, p):
            return "A gear train is a set of gears that transmit torque. " * 10
    quiz.files = Files()
    src = quiz.find_source("the gear trains pdf")
    assert src[0] == "gear trains" and "transmit torque" in src[1]


def test_long_texts_are_cut_at_paragraphs():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 200 for i in range(40))
    chunk = Q.Quiz.pick_chunk(text)
    assert len(chunk) <= Q.CHUNK_CHARS and chunk.startswith("Paragraph")


def test_quiz_answers_bypass_the_model_in_handle_turn(aria, quiz):
    aria.quiz = quiz
    quiz.start("databases", 3)
    reply, used = aria.handle_turn("transitive dependencies", check_state=False)
    assert used[0][0] == "quiz" and "Next:" in reply and aria.llm.prompts == []


@pytest.mark.parametrize("answer,ok", [("transitive dependencies", True), ("C#", True), ("ATP and NADPH", True),
                                       ("RuBisCO.", True), ("?Invoke", False), ("?.Invoke operator", False),
                                       ("(object sender, EventArgs e)", False), ("x => x * 2", False),
                                       ("Func<T, TResult>", False), ("one two three four five six seven", False)])
def test_only_speakable_answers(answer, ok):
    assert Q.speakable(answer) is ok


NOTE_TEXT = html_to_text(NOTE)


def test_start_on_uses_the_given_text_without_searching(quiz):
    out = quiz.start_on("Kapitel 3 (untitled-ish)", NOTE_TEXT, 3)   # a title the search would never match
    assert out.startswith(Q.FINAL_PREFIX + "Quiz on Kapitel 3 (untitled-ish), 3 questions.")
    assert quiz.active["title"] == "Kapitel 3 (untitled-ish)"
    assert "transitive dependencies" in quiz.calls[0]


def test_start_on_a_tiny_text_says_so(quiz):
    assert quiz.start_on("Stub", "just a heading") == "'Stub' doesn't have enough in it to quiz you on yet."
    assert quiz.active is None


OLD = [{"q": "What is a primary key?", "a": "a unique identifier", "source": "Keys"}]


def state():
    return json.load(open(Q.STATE_FILE)).get("misses", [])


def test_mixed_asks_old_questions_first_and_says_the_split(quiz):
    said = quiz.start_mixed("DBI test", OLD, [("Databases", html_to_text(NOTE), 2)])
    assert said.startswith(Q.FINAL_PREFIX + "Quiz for your DBI test, ")
    assert "1 you missed before, then " in said and said.endswith("First one: What is a primary key?")
    assert [q.get("source") for q in quiz.active["questions"]][:2] == ["Keys", "Databases"]


def test_mixed_without_old_questions_has_the_plain_opening(quiz):
    said = quiz.start_mixed("DBI test", [], [("Databases", html_to_text(NOTE), 3)])
    assert "Quiz for your DBI test, 3 questions. Say skip" in said and "missed before" not in said


def test_mixed_saves_a_miss_under_its_note_and_drops_a_fixed_old_one(quiz):
    quiz._save_misses("Keys", OLD)
    quiz.start_mixed("DBI test", OLD, [("Databases", html_to_text(NOTE), 1)])
    quiz.answer("a unique identifier")          # the old one, right
    quiz.answer("skip")                         # the new one, missed
    assert [(m["q"], m["source"]) for m in state()] == [(QUESTIONS[0]["q"], "Databases")]


def test_mixed_drops_a_new_question_that_repeats_an_old_one(quiz):
    old = [dict(QUESTIONS[0], source="Databases")]
    quiz.start_mixed("DBI test", old, [("Databases", html_to_text(NOTE), 3)])
    assert [q["q"] for q in quiz.active["questions"]].count(QUESTIONS[0]["q"]) == 1


def test_mixed_with_nothing_to_ask(quiz):
    assert quiz.start_mixed("DBI test", [], []) == "I couldn't come up with questions for that, try again in a moment."
    assert quiz.active is None


def test_an_ordinary_quiz_still_saves_misses_under_its_title(quiz):
    quiz.start("databases")
    quiz.answer("skip"); quiz.answer("stop")
    assert state()[0]["source"] == "Databases"

"""Aria writing and reworking MyNotion notes (Engines/NoteWriter.py), with a scripted model instead of Ollama."""

import pytest

import Engines.NotionEngine as NE
from Engines.NoteWriter import NoteWriter, facts, html_to_md, md_to_html, missing, nothing_missing, small_changes
from Engines.NotionEngine import card_items, html_to_text

RICH = (
    '<h2>Matrizen</h2><p>Zeilen <strong>zuerst</strong>, Spalten <em>später</em>: <span data-latex="A_{2x3}" '
    'data-type="inline-math"></span> und 2$ Taschengeld</p>'
    '<div data-latex="\\det(A) = ad - bc" data-type="block-math"></div>'
    '<ul data-type="taskList"><li data-checked="true" data-type="taskItem"><label><input type="checkbox" '
    'checked="checked"><span></span></label><div><p>5.3 rechnen</p></div></li><li data-checked="false" '
    'data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>5.4 lernen</p></div></li></ul>'
    '<table class="note-table"><tbody><tr><th><p>a</p></th><th><p>b</p></th></tr><tr><td><p>1</p></td>'
    '<td><p>2</p></td></tr></tbody></table>'
    '<div data-type="callout" data-kind="tip"><p>Erst Spalten zählen</p></div>'
    '<details class="toggle"><summary>Was ist eine Matrix?</summary><div data-type="detailsContent">'
    '<p>Ein Zahlenschema</p></div></details>'
    '<p>Das ist <mark data-color="#bbf7d0">wichtig</mark> und m<sup>2</sup></p>'
    '<img src="mynotion-image://image/1" data-align="left">'
    '<p>2)</p><ol><li><p>eins</p></li><li><p>zwei</p></li></ol>'
    '<pre><code class="language-python">print("a * b")</code></pre>'
    '<p><a href="mynotion://note/3">C# Notiz</a></p>'
)


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.during = []          # the editing lock while the model was asked
        self.notion = None

    def __call__(self, prompt, history=(), temperature=0.3):
        self.prompts.append(prompt)
        if self.notion:
            self.during.append(self.notion._state("aria_editing"))
        return self.replies.pop(0) if self.replies else ""


@pytest.fixture
def writer(notion, monkeypatch):
    monkeypatch.setattr(NE, "mynotion_running", lambda: True)
    monkeypatch.setattr(NE, "EDIT_SETTLE_S", 0)
    model = FakeModel()
    model.notion = notion
    w = NoteWriter(notion, ask=model)
    w.model_fake = model
    return w


def say(writer, *replies):
    writer.model_fake.replies = list(replies)
    return writer.model_fake


def open_in_mynotion(notion, note_id):
    notion._set_state("open_note", str(note_id))


# ── Markdown both ways ──

def test_a_rich_note_comes_back_the_same():
    md, keep = html_to_md(RICH)
    back = md_to_html(md, keep)
    assert "".join(html_to_text(back).split()) == "".join(html_to_text(RICH).split())
    assert html_to_md(back) == (md, keep)                       # stable: doing it again changes nothing
    for part in ('data-type="block-math"', 'data-type="taskItem"', 'data-checked="true"', "<table",
                 'data-kind="tip"', "<details", '<mark data-color="#bbf7d0">wichtig</mark>', "<sup>2</sup>",
                 'src="mynotion-image://image/1"', 'href="mynotion://note/3"', 'class="language-python"'):
        assert part in back, part


def test_the_model_sees_readable_markdown():
    md, keep = html_to_md(RICH)
    assert "## Matrizen" in md
    assert "$A_{2x3}$" in md and "$$\\det(A) = ad - bc$$" in md
    assert "- [x] 5.3 rechnen" in md and "- [ ] 5.4 lernen" in md
    assert "| a | b |" in md
    assert "::: tip\nErst Spalten zählen\n:::" in md
    assert "::: toggle Was ist eine Matrix?" in md
    assert "{{0}}wichtig{{/0}}" in md                           # highlighted words stay readable
    assert "2\\$ Taschengeld" in md                             # money isn't a formula
    assert "2\\)" in md                                         # "2)" isn't a numbered list


def test_markdown_from_the_model_becomes_mynotion_blocks():
    html_ = md_to_html("## Kreis\n\n> [!TIP]\n> Radius zuerst\n\n- [ ] Aufgabe 1\n- [x] Aufgabe 2\n\n"
                       "Fläche: $A = \\pi r^2$\n\n$$U = 2 \\pi r$$\n\n::: toggle Wie groß ist U?\n$2\\pi r$\n:::")
    assert "<h2>Kreis</h2>" in html_
    assert '<div data-type="callout" data-kind="tip"><p>Radius zuerst</p></div>' in html_
    assert [i["checked"] for i in card_items(html_)] == [False, True]
    assert '<span data-type="inline-math" data-latex="A = \\pi r^2"></span>' in html_
    assert '<div data-type="block-math" data-latex="U = 2 \\pi r"></div>' in html_
    assert '<details class="toggle"><summary>Wie groß ist U?</summary><div data-type="detailsContent">' in html_


def test_raw_html_from_the_model_is_only_text():
    assert "<script" not in md_to_html("hi <script>alert(1)</script>")


def test_missing_words_formulas_and_markers_are_found():
    old = "Zeilen zuerst $a_1$ {{0}}x{{/0}}"
    assert nothing_missing(missing(old, "## Neu\n\n- Zeilen zuerst\n- $a_1$ {{0}}x{{/0}}"))
    gap = missing(old, "Zeilen $a_2$")
    assert gap == {"words": ["x", "zuerst"], "formulas": ["a_1"], "marks": ["/0", "0", "{{0}}x"], "boxes": []}


def test_spelling_fixes_must_be_small():
    ok, n = small_changes("Das ist ein Tset mit $x$ und viel mehr Text hier drin", "Das ist ein Test mit $x$ und viel mehr Text hier drin")
    assert ok and n == 1
    assert not small_changes("Das ist ein Test mit $x$", "Völlig anderer Satz ohne Formel")[0]


# ── organise ──

def test_organise_the_open_note(writer, notion):
    nid = notion._create_note("Bio", "<p>Mitose Zellteilung</p><p>Kaufen Hefte</p><p>Meiose Keimzellen</p><p>Lernen bis Montag</p>")
    open_in_mynotion(notion, nid)
    model = say(writer, "## Zellteilung\n\n- Mitose Zellteilung\n- Meiose Keimzellen\n\n## To-do\n\n- [ ] Kaufen Hefte\n- [ ] Lernen bis Montag")
    msg = writer.organize_note("this note")
    assert msg.startswith("Organised 'Bio'.")
    content = notion._note_by_id(nid)["content"]
    assert "<h2>Zellteilung</h2>" in content and 'data-type="taskList"' in content
    assert model.during == [str(nid)]                       # MyNotion was told Aria is editing
    assert notion._state("aria_editing") is None            # …and that she's done


def test_organise_gives_one_more_try_then_leaves_the_note(writer, notion):
    nid = notion._create_note("Bio", "<p>Mitose ist Zellteilung und Meiose macht Keimzellen für später</p>")
    model = say(writer, "Mitose ist Zellteilung", "Mitose ist Zellteilung und Meiose")
    msg = writer.organize_note("Bio")
    assert "left it as it was" in msg
    assert "left out these words" in model.prompts[1] and "keimzellen" in model.prompts[1]
    assert notion._note_by_id(nid)["content"] == "<p>Mitose ist Zellteilung und Meiose macht Keimzellen für später</p>"


def test_organise_keeps_pictures_and_formulas(writer, notion):
    nid = notion._create_note("Mathe", '<p>eins zwei drei vier fünf sechs sieben acht</p><p><span data-latex="x^2" '
                                       'data-type="inline-math"></span></p><img src="mynotion-image://image/4">')
    say(writer, "## Zahlen\n\neins zwei drei vier fünf sechs sieben acht\n\n{{0}}",       # formula dropped
        "## Zahlen\n\neins zwei drei vier fünf sechs sieben acht\n\n$x^2$\n\n{{0}}")
    assert writer.organize_note("Mathe").startswith("Organised")
    content = notion._note_by_id(nid)["content"]
    assert 'data-latex="x^2"' in content and 'src="mynotion-image://image/4"' in content


def test_a_note_changed_meanwhile_is_not_overwritten(writer, notion):
    nid = notion._create_note("Bio", "<p>eins zwei drei vier fünf sechs sieben acht neun</p>")

    def model(prompt, history=(), temperature=0.3):
        notion._set_content(nid, "<p>Lala typed this</p>")          # someone types while the model works
        return "## X\n\neins zwei drei vier fünf sechs sieben acht neun"
    writer.ask = model
    assert "changed in MyNotion while I was working" in writer.organize_note("Bio")
    assert notion._note_by_id(nid)["content"] == "<p>Lala typed this</p>"


def test_no_open_note(writer, notion):
    assert "can't see one open" in writer.organize_note("this")


def test_organising_can_be_undone(writer, notion):
    from Engines.Tool_Engine import ToolEngine
    from Engines.Undo import Undo
    tools = ToolEngine(notion=notion, writer=writer, undo=Undo(notion))
    nid = notion._create_note("Bio", "<p>eins zwei drei vier fünf sechs sieben acht neun</p>")
    say(writer, "## Zahlen\n\n- eins zwei drei\n- vier fünf sechs sieben acht neun")
    assert tools.execute("organize_note", {"title": "Bio"}).startswith("Organised")
    assert tools.execute("undo_last", {}).startswith("Undone")
    assert notion._note_by_id(nid)["content"] == "<p>eins zwei drei vier fünf sechs sieben acht neun</p>"


# ── write ──

def test_write_a_new_note(writer, notion):
    model = say(writer, "```markdown\n# Kreis\n\n## Formeln\n\n$$A = \\pi r^2$$\n\n- [ ] üben\n```")
    msg = writer.write_note("Kreis", "the circle formulas")
    assert msg.startswith("Wrote the note 'Kreis'")
    n = notion._find_note("Kreis")
    assert n["content"].startswith("<h2>Formeln</h2>")                 # the repeated title was left out
    assert 'data-type="block-math"' in n["content"] and 'data-type="taskList"' in n["content"]
    assert "::: tip" in model.prompts[0]                                # it was told MyNotion's blocks


def test_write_from_the_last_answer(writer, notion):
    notion.last_reply = lambda: "Mitochondria make energy."
    model = say(writer, "- Mitochondria make energy.")
    writer.write_note("Cells", "", from_last_answer=True)
    assert "Mitochondria make energy." in model.prompts[0]
    assert "Mitochondria" in notion._find_note("Cells")["content"]


def test_write_into_an_existing_note_adds_to_it(writer, notion):
    nid = notion._create_note("Kreis", "<p>alt</p>")
    say(writer, "## Neu\n\nmehr")
    assert writer.write_note("Kreis", "more").startswith("Added")
    assert notion._note_by_id(nid)["content"] == "<p>alt</p><h2>Neu</h2><p>mehr</p>"


# ── edit ──

def test_add_a_section_after_a_heading(writer, notion):
    nid = notion._create_note("Bio", "<h2>Zellen</h2><p>a</p><h2>Genetik</h2><p>b</p>")
    say(writer, "### Mitose\n\nZellteilung")
    assert "after the 'Zellen' part" in writer.edit_note("Bio", "add", "a part about mitosis", section="zellen")
    assert notion._note_by_id(nid)["content"] == "<h2>Zellen</h2><p>a</p><h3>Mitose</h3><p>Zellteilung</p><h2>Genetik</h2><p>b</p>"


def test_summary_goes_on_top_and_replaces_the_old_one(writer, notion):
    text = " ".join(f"wort{i}" for i in range(40))
    nid = notion._create_note("Bio", f"<p>{text}</p>")
    say(writer, "**Zusammenfassung**\n\n- erstens", "**Zusammenfassung**\n\n- zweitens")
    writer.edit_note("Bio", "summary")
    assert writer.edit_note("Bio", "summary").startswith("Updated the summary")
    content = notion._note_by_id(nid)["content"]
    assert content.startswith('<div data-type="callout" data-kind="note"><p><strong>Zusammenfassung</strong></p>')
    assert "zweitens" in content and "erstens" not in content and content.count("Zusammenfassung") == 1


def test_fix_spelling(writer, notion):
    nid = notion._create_note("Bio", "<p>Die Zelle teilt sich in zwei Tochterzellen, das nent man Mitose.</p>")
    say(writer, "Die Zelle teilt sich in zwei Tochterzellen, das nennt man Mitose.")
    assert writer.edit_note("Bio", "fix_spelling").startswith("Fixed 1 word in 'Bio'")
    assert "nennt" in notion._note_by_id(nid)["content"]


def test_spelling_fix_that_rewrites_too_much_is_refused(writer, notion):
    old = "<p>Die Zelle teilt sich in zwei Tochterzellen, das nent man Mitose.</p>"
    nid = notion._create_note("Bio", old)
    say(writer, "Mitose: Zellteilung in zwei.")
    assert "without changing too much" in writer.edit_note("Bio", "fix_spelling")
    assert notion._note_by_id(nid)["content"] == old


def test_translate_keeps_formulas(writer, notion):
    nid = notion._create_note("Kreis", '<p>Die Fläche ist <span data-latex="\\pi r^2" data-type="inline-math"></span></p>')
    say(writer, "The area is")
    assert "lost some parts" in writer.edit_note("Kreis", "translate", language="English")
    say(writer, "The area is $\\pi r^2$")
    assert writer.edit_note("Kreis", "translate", language="English").startswith("Translated")
    assert notion._note_by_id(nid)["content"] == '<p>The area is <span data-type="inline-math" data-latex="\\pi r^2"></span></p>'


def test_rewrite_one_part(writer, notion):
    nid = notion._create_note("Krieg", "<h2>Einleitung</h2><p>sehr langer Text hier</p><h2>Daten</h2><p>1914 Beginn</p>")
    model = say(writer, "## Einleitung\n\nkurz")
    assert writer.edit_note("Krieg", "rewrite", "make it shorter", section="Einleitung").startswith("Changed the 'Einleitung' part")
    assert "1914 Beginn" not in model.prompts[0]                  # the model only saw that part
    assert notion._note_by_id(nid)["content"] == "<h2>Einleitung</h2><p>kurz</p><h2>Daten</h2><p>1914 Beginn</p>"


# ── "this note" elsewhere, and routing ──

def test_read_and_add_to_this_note(notion, monkeypatch):
    monkeypatch.setattr(NE, "mynotion_running", lambda: True)
    nid = notion._create_note("Physik", "<p>Kraft</p>")
    open_in_mynotion(notion, nid)
    assert notion.read_note("this note").startswith("Note 'Physik'")
    assert notion.add_note("F = m a", title="this note") == "Added to 'Physik'."
    monkeypatch.setattr(NE, "mynotion_running", lambda: False)      # MyNotion closed: nothing is open
    assert notion.open_note() is None


def test_note_writing_words_offer_the_tools(notion, writer):
    from Engines.Tool_Engine import ToolEngine
    tools = ToolEngine(notion=notion, writer=writer)
    for text in ("organise this note", "write a study sheet on the french revolution", "fix the spelling in it",
                 "translate my biology note into English", "put a summary at the top"):
        names = {s["function"]["name"] for s in tools.schemas_for(text)}
        assert {"write_note", "organize_note", "edit_note"} <= names, text


# ── how the real model writes (seen with qwen3:8b) ──

def test_spaced_formulas_four_colons_and_toggles_in_lists():
    from Engines.NoteWriter import strip_fence
    md = strip_fence("<<<\n- $ A $ is the area, costs $5 and $6\n\n1. What is U?  \n   :::: toggle What is U?  \n"
                     "   $ U = 2\\pi r $  \n   :::\n>>>")
    html_ = md_to_html(md)
    assert '<span data-type="inline-math" data-latex="A"></span> is the area, costs $5 and $6' in html_
    assert '<details class="toggle"><summary>What is U?</summary>' in html_
    assert '<span data-type="inline-math" data-latex="U = 2\\pi r"></span>' in html_
    assert "<ol>" not in html_ and "&lt;&lt;&lt;" not in html_ and "&gt;&gt;&gt;" not in html_


def test_lines_one_under_the_other_stay_apart():
    assert md_to_html("eins\nzwei") == "<p>eins<br>zwei</p>"


def test_joined_words_and_text_turned_into_formulas_are_not_lost():
    old = "licht energie wird umgewandelt: 6CO2 + 6H2O"
    assert nothing_missing(missing(old, "Lichtenergie wird umgewandelt: $6CO_2 + 6H_2O$"))
    assert missing(old, "Energie wird umgewandelt")["words"] == ["6co2", "6h2o", "licht"]


def test_sentences_made_headings_get_one_more_try(writer, notion):
    nid = notion._create_note("Bio", "<p>Photosynthese findet in den Chloroplasten statt und braucht Licht</p><p>Test am Montag</p>")
    model = say(writer, "## Photosynthese findet in den Chloroplasten statt und braucht Licht\n\n- [ ] Test am Montag",
                "## Photosynthese\n\nPhotosynthese findet in den Chloroplasten statt und braucht Licht\n\n- [ ] Test am Montag")
    assert writer.organize_note("Bio").startswith("Organised")
    assert "turned sentences into headings" in model.prompts[1]
    assert notion._note_by_id(nid)["content"].startswith("<h2>Photosynthese</h2><p>Photosynthese findet")


def test_exercise_numbers_highlights_and_boxes_must_stay():
    old = "5.2)\n\nZeilen zuerst\n\n5.3)\n\nEs ist {{0}}wichtig{{/0}} und $x$\n\n::: note\nRegel\n:::"
    gap = missing(old, "## Zeilen\n\nZeilen zuerst\n\n5.3)\n\nEs ist wichtig und {{0}}$x${{/0}}\n\nRegel")
    assert gap["words"] == ["5.2"]
    assert "{{0}}wichtig" in gap["marks"]
    assert gap["boxes"] == ["note"]


def test_a_box_that_is_never_closed_takes_only_the_lines_under_it():
    html_ = md_to_html("::: tip\nmerken\n\nnormaler Text")
    assert html_ == '<div data-type="callout" data-kind="tip"><p>merken</p></div><p>normaler Text</p>'


def test_a_rewrite_that_keeps_the_old_lines_too_is_refused(writer, notion):
    old = "<p>Photosynthese findet in den Chloroplasten statt</p><p>Licht wird zu chemischer Energie</p>"
    nid = notion._create_note("Bio", old)
    twice = "\n\n".join(["Photosynthese findet in den Chloroplasten statt", "Licht wird zu chemischer Energie",
                          "## Grundlagen", "- Photosynthese findet in den Chloroplasten statt\n"
                          "- Licht wird zu chemischer Energie"])
    model = say(writer, twice, twice)
    assert "repeated parts" in writer.edit_note("Bio", "rewrite", "make the lines a list")
    assert "twice" in model.prompts[1]
    assert notion._note_by_id(nid)["content"] == old


# ── a selection from MyNotion: rework(html, action, …) -> (new html or None, why not) ──────────────────────

PARA = "<p>The mitochondria is the the powerhouse of the cell and it makes a lot of energy for the cell.</p>"


def rework(*replies):
    model = FakeModel(*replies)
    return NoteWriter(None, ask=model), model


def test_rework_rewrites_a_paragraph():
    w, model = rework("Mitochondria are the powerhouse of the cell: they produce most of its energy.")
    html, why = w.rework(PARA, "rewrite", title="Biology")
    assert html == "<p>Mitochondria are the powerhouse of the cell: they produce most of its energy.</p>" and why == ""
    assert "Biology" in model.prompts[0] and "powerhouse of the cell and it makes" in model.prompts[0]
    assert "<p>" not in model.prompts[0]                         # the model works in Markdown


def test_rework_part_of_a_sentence_stays_one_piece():
    w, _ = rework("the cell's **powerhouse**")
    html, _ = w.rework("the powerhouse of the cell", "rewrite")
    assert html == "<p>the cell's <strong>powerhouse</strong></p>"


def test_rework_shorter_must_be_shorter():
    longer = "The mitochondria is really and truly the powerhouse of the whole cell and it makes a great lot of energy for it."
    w, model = rework(longer, "Mitochondria power the cell.")
    html, why = w.rework(PARA, "shorter")
    assert html == "<p>Mitochondria power the cell.</p>"
    assert len(model.prompts) == 2 and "shorter" in model.prompts[1].lower()      # told what was wrong, once


def test_rework_gives_up_after_one_retry():
    longer = PARA[3:-4] + " And some more words on top of it."
    w, model = rework(longer, longer, "never asked")
    html, why = w.rework(PARA, "shorter")
    assert html is None and "shorter" in why.lower()
    assert len(model.prompts) == 2


def test_rework_spelling_accepts_small_fixes_only():
    w, _ = rework("The mitochondria is the powerhouse of the cell and it makes a lot of energy for the cell.")
    html, _ = w.rework(PARA, "spelling")
    assert html == "<p>The mitochondria is the powerhouse of the cell and it makes a lot of energy for the cell.</p>"
    w, _ = rework("Cells have organelles.", "Cells have organelles.")
    html, why = w.rework(PARA, "spelling")
    assert html is None and "too much" in why


def test_rework_spelling_with_nothing_to_fix():
    w, model = rework("Alles richtig geschrieben.")
    html, why = w.rework("<p>Alles richtig geschrieben.</p>", "spelling")
    assert html is None and why == "I found no mistakes in that part."
    assert len(model.prompts) == 1                              # nothing to retry


def test_rework_table_keeps_every_word():
    lines = "<p>Bio: 5.5</p><p>Mathe: 4</p>"
    w, _ = rework("| Fach | Note |\n|---|---|\n| Bio | 5.5 |\n| Mathe | 4 |")
    html, why = w.rework(lines, "table")
    assert "<table" in html and "Mathe" in html and "5.5" in html
    w, _ = rework("| Fach | Note |\n|---|---|\n| Bio | 5.5 |", "| Fach | Note |\n|---|---|\n| Bio | 5.5 |")
    html, why = w.rework(lines, "table")
    assert html is None and "mathe" in why.lower()              # says what would be lost
    w, _ = rework("Bio: 5.5, Mathe: 4", "Bio: 5.5 and Mathe: 4")
    html, why = w.rework(lines, "table")
    assert html is None and "table" in why


def test_rework_keeps_formulas_pictures_and_highlights():
    part = ('<p>Die Fläche ist <span data-latex="A = \\pi r^2" data-type="inline-math"></span> und das ist '
            '<mark data-color="#bbf7d0">wichtig</mark> für die Prüfung am Freitag.</p>')
    w, model = rework("Fläche: $A = \\pi r^2$, {{0}}wichtig{{/0}} für Freitag.")
    html, _ = w.rework(part, "shorter")
    assert 'data-latex="A = \\pi r^2"' in html and '<mark data-color="#bbf7d0">wichtig</mark>' in html
    assert "{{0}}wichtig{{/0}}" in model.prompts[0]
    w, _ = rework("Fläche: $A = \\pi r^2$, wichtig für Freitag.", "Fläche: $A = \\pi r^2$, wichtig für Freitag.")
    html, why = w.rework(part, "shorter")
    assert html is None and "highlight" in why
    w, _ = rework("Die Fläche ist {{0}}wichtig{{/0}} für Freitag.", "Die Fläche ist {{0}}wichtig{{/0}} für Freitag.")
    html, why = w.rework(part, "rewrite")
    assert html is None and "formula" in why


def test_rework_with_an_own_instruction():
    w, model = rework("- makes energy\n- is the powerhouse of the cell")
    html, _ = w.rework(PARA, "custom", instruction="turn into bullet points")
    assert html.startswith("<ul>") and html.count("<li>") == 2
    assert "turn into bullet points" in model.prompts[0]
    assert NoteWriter(None, ask=FakeModel()).rework(PARA, "custom") == (None, "How should I change it?")


def test_rework_refuses_the_old_lines_next_to_the_new_ones():
    both = PARA[3:-4] + "\n\nMitochondria are the powerhouse of the cell and they make a lot of energy for the cell."
    w, model = rework(both, both)
    html, why = w.rework(PARA, "rewrite")
    assert html is None and len(model.prompts) == 2


def test_rework_the_same_text_back_is_not_a_proposal():
    same = PARA[3:-4]
    w, model = rework(same, same)
    html, why = w.rework(PARA, "rewrite")
    assert html is None and "different" in why


def test_rework_an_empty_answer():
    w, _ = rework("", "")
    assert w.rework(PARA, "rewrite") == (None, "I couldn't come up with a version just now. Try again.")


def test_rework_limits():
    w, model = rework("never asked")
    assert w.rework("<p></p>", "rewrite") == (None, "There's no text in what you selected.")
    assert w.rework("<p>" + "wort " * 1000 + "</p>", "rewrite") == (None, "That's too much at once. Select a smaller part.")
    assert w.rework(PARA, "dance") == (None, "I don't know that kind of change.")
    assert model.prompts == []


def test_rework_try_again_differs_from_the_last_version():
    w, model = rework("Mitochondria: the cell's power plants.")
    temps = []
    real = model.__call__
    w.ask = lambda prompt, history=(), temperature=0.3: (temps.append(temperature), real(prompt, history, temperature))[1]
    html, _ = w.rework(PARA, "rewrite", previous="<p>Mitochondria power the cell.</p>")
    assert html == "<p>Mitochondria: the cell's power plants.</p>"
    assert "Mitochondria power the cell." in model.prompts[0] and temps[0] >= 0.6


def test_rework_uses_the_surrounding_text_only_as_context():
    w, model = rework("It produces ATP.")
    w.rework("<p>It makes energy.</p>", "rewrite", context="Chapter 3: Mitochondria. It makes energy. Next: ribosomes.")
    assert "Chapter 3: Mitochondria" in model.prompts[0]


def test_rework_never_touches_the_database(notion):
    note_id = notion._create_note("Biology", PARA)
    w = NoteWriter(notion, ask=FakeModel("Mitochondria power the cell."))
    assert w.rework(PARA, "shorter")[0]
    assert notion._note_by_id(note_id)["content"] == PARA and notion._state("aria_editing") is None

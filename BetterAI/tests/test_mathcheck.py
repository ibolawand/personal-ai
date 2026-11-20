"""Checking worked differential equations in a note with exact maths (Engines/MathCheck.py). No model involved."""

import sympy as sp

from main import tidy_reply
from Engines.MathCheck import check_note, exercises, parse_expr

M = lambda tex: f'<span data-latex="{tex}" data-type="inline-math"></span>'
P = lambda *parts: "<p>" + " ".join(parts) + "</p>"
x = sp.Symbol("x")


# ── reading the formulas ──

def test_latex_as_students_write_it():
    assert parse_expr("0,25x^2 + 1") == sp.Rational(1, 4) * x**2 + 1
    assert parse_expr(r"\frac{1}{12} \cdot x^3 + x- \frac{1}{12}") == x**3 / 12 + x - sp.Rational(1, 12)
    assert parse_expr(r"x^\frac{1}{2}") == sp.sqrt(x)
    assert parse_expr(r"\sqrt(x)") == sp.sqrt(x)
    assert parse_expr(r"\sqrt{x}") == sp.sqrt(x)
    assert parse_expr(r"4 \cdot e^{3x}") == 4 * sp.exp(3 * x)
    assert parse_expr(r"\frac{4x^3}{3} - \frac{3x^2}{2} + ln(x)") == 4 * x**3 / 3 - 3 * x**2 / 2 + sp.log(x)
    assert parse_expr("0.01x^4+C_1x+C_2") == x**4 / 100 + sp.Symbol("C_1") * x + sp.Symbol("C_2")
    assert parse_expr("-3x +2") == 2 - 3 * x
    assert parse_expr("2(x+1)(x-1)") == 2 * (x + 1) * (x - 1)


def test_what_it_cannot_read_is_none_not_a_crash():
    for tex in (r"\int 3x^2 dx", r"\begin{pmatrix}1\\2\end{pmatrix}", "K'(t)", "__import__('os')", "", "x +"):
        assert parse_expr(tex) is None, tex


# ── finding the exercises ──

NOTE = (
    P("4.3)") + P(M("y''=0.12x^2")) + P(M("y(0)=1"), M("y(1)=3.01"))
    + P(M(r"y'=\int0.12x^2 dx= 0,04x^3+C_1")) + P(M(r"y=\int0.04x^3+C_1 dx=0.01x^4+C_1x+C_2"), "→ allgemeine Lösung")
    + P(M("C_1=2"), "⇒ spezielle loesung :", M("y(x)=0.01x^4+2x+1"))
    + '<img src="mynotion-image://image/4">'
    + P("4.15)") + P(M("y'= 0,25x^2 + 1") + ";", M("y(2)=1")) + P(M("y'= 0,25x^2 + 1"), "|" + M(r"\int"))
    + P(M(r"y= \frac{1}{12} \cdot x^3 + x + c"))
    + P("spezielle Lösung →", M(r"y=\frac{1}{12}\cdot x^3 + x- \frac{1}{12}"))
    + P("4.16)") + P(M(r"y''=\sqrt(x)= x^\frac{1}{2}"))
    + P(M(r"y = \frac{4x^\frac{5}{2}}{6} + C_2 + C_1"))
    + "<h2>Trennen der Variablen</h2>" + P("ohne Nummer", M("y'=2x"), M("y=x^2"))
)


def test_exercises_are_split_at_their_numbers():
    found = exercises(NOTE)
    assert [e.label for e in found] == ["4.3", "4.15", "4.16"]
    assert found[0].formulas[0] == "y''=0.12x^2"


def test_a_correct_solution():
    msg = check_note(NOTE, "4.3")
    assert msg.startswith("4.3: correct")
    assert "y(0) = 1" in msg and "y(1) = 3.01" in msg


def test_the_condition_that_fails_is_named_with_its_real_value():
    msg = check_note(NOTE, "4.15")
    assert msg.startswith("4.15: not right")
    assert "fits y' = " in msg                      # the derivative is fine…
    assert "y(2) is 2.583, not 1" in msg            # …the constant is not
    assert "x^3/12 + x - 5/3" in msg                # the right one, worked out exactly


def test_a_wrong_integration_and_misplaced_constants():
    msg = check_note(NOTE, "4.16")
    assert msg.startswith("4.16: not right")
    assert "doesn't fit y'' = sqrt(x)" in msg
    assert "4x^(5/2)/15" in msg


def test_the_whole_note_one_line_per_exercise():
    msg = check_note(NOTE)
    lines = msg.split("\n")
    assert [l.split(":")[0] for l in lines] == ["4.3", "4.15", "4.16"]


def test_an_exercise_that_is_not_there():
    assert "couldn't find exercise 9.9" in check_note(NOTE, "9.9")
    assert "4.3, 4.15 and 4.16" in check_note(NOTE, "9.9")


def test_a_note_without_differential_equations():
    assert "no differential equation" in check_note(P("Einkaufen: Milch") + P("5.1)") + P(M("a^2+b^2=c^2")))


# ── general solutions and separable equations ──

def test_a_general_solution_needs_as_many_constants_as_the_order():
    note = P("4.13)") + P(M("y'' = -3x +2")) + P(M(r"y=\frac{-3x^3}{6} + x^2 + Cx"))
    msg = check_note(note)
    assert msg.startswith("4.13: almost")
    assert "fits y''" in msg and "2 constants" in msg

    wrong = P("4.13)") + P(M("y'' = -3x +2")) + P(M(r"y=\frac{-3x^4}{12} + x^2 + Cx"))
    assert check_note(wrong).startswith("4.13: not right")


def test_an_equation_with_y_on_the_right():
    good = P("4.26)") + P(M(r"y'=3x^2 \cdot y"), M("y(0)=4")) + P(M(r"y(x)=4 \cdot e^{x^3}"))
    assert check_note(good).startswith("4.26: correct")
    bad = P("4.26)") + P(M(r"\frac{dy}{dx}=3x^2\cdot y"), M("y(0)=4")) + P(M(r"y(x)=4 \cdot e^{3x}"))
    msg = check_note(bad)
    assert msg.startswith("4.26: not right") and "4e^(x^3)" in msg
    assert "y(0) = 4 is fine" in msg                 # what is right is said too


def test_no_final_answer_yet():
    msg = check_note(P("4.4)") + P(M("y'=2x"), M("y(0)=1")))
    assert msg.startswith("4.4: no final") and "y = " in msg


# ── two exercises side by side ──

def test_columns_are_checked_one_by_one():
    tabs = "\t\t\t\t   "
    d1, d2 = M("y'=2x"), M("y'=1")
    note = (P("4.26) a)" + " " * 30 + "4.26b)")
            + f"<p>{d1} {M('y(0)=1')}{tabs}{d2} {M('y(0)=5')}</p>"
            + f"<p>{M('y=x^2+1')}{tabs}{M('y=x+4')}</p>")
    msg = check_note(note)
    a, b = msg.split("\n")
    assert a.startswith("4.26 a: correct")
    assert b.startswith("4.26 b: not right") and "y(0) is 4, not 5" in b


def test_two_exercises_mixed_in_one_line_get_no_verdict():
    note = P("4.13)") + P("a)", M("y'' = -3x +2"), "b)", M("y'= 4x^2")) + P(M("y=x"))
    msg = check_note(note)
    assert "can't tell" in msg and "correct" not in msg and "not right" not in msg


# ── as Aria's tool ──

def test_the_tool_checks_the_open_note_and_its_words_are_final(notion, monkeypatch):
    import Engines.NotionEngine as NE
    from Engines.Tool_Engine import ToolEngine
    from llm_engine import FINAL_PREFIX
    monkeypatch.setattr(NE, "mynotion_running", lambda: True)
    tools = ToolEngine(notion=notion)
    nid = notion._create_note("Differentialgleichung", NOTE)
    assert "can't see one open" in tools.execute("check_solution", {})
    notion._set_state("open_note", str(nid))
    out = tools.execute("check_solution", {"exercise": "4.15"})
    assert out.startswith(FINAL_PREFIX + "4.15: not right yet.")      # the model doesn't get to reword the maths
    said = out[len(FINAL_PREFIX):]
    assert tidy_reply(said) == said                                    # …and tidying the reply leaves it alone
    assert tools.execute("check_solution", {"title": "Differentialgleichung", "exercise": "4.3"}) \
        .startswith(FINAL_PREFIX + "4.3: correct")
    assert notion._note_by_id(nid)["content"] == NOTE                  # only reads


def test_checking_words_offer_the_tool(notion):
    from Engines.Tool_Engine import ToolEngine
    tools = ToolEngine(notion=notion)
    for text in ("is my solution right?", "check exercise 4.15", "stimmt mein Rechenweg?",
                 "did I solve 4.3 correctly?", "ist die Lösung von 4.15 richtig?"):
        assert "check_solution" in {s["function"]["name"] for s in tools.schemas_for(text)}, text

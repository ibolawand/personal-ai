"""
"Is my solution right?" — worked differential equations in a MyNotion note, checked with exact maths (SymPy).

A small language model guesses at maths, so nothing here asks it: the code reads the formulas of an exercise,
finds the equation (y' = …, y'' = …), the conditions (y(0) = 1) and the final answer (the last y = …), and then
simply tries it out: derive the answer, put it into the equation, put the numbers into the conditions.

  check_note(html)            every numbered exercise ("4.15)") of the note, one line each
  check_note(html, "4.15")    one exercise

What it says is decided here, word for word: "4.15: not right yet. Your y = … fits y' = …, but y(2) is 2.583,
not 1. It should be y = x^3/12 + x - 5/3."

Formulas are read by a small parser of its own (no eval, no LaTeX library): fractions, powers, roots, e^…, ln,
sin/cos/tan, constants like C_1, decimal commas. What it can't read (integrals, matrices) is skipped. Two exercises
written side by side with Tab are checked one by one (the same column finder as "organise this note"); two mixed
in one line get no verdict, because nobody can tell which line belongs to which.
"""

import re
from dataclasses import dataclass, field

import sympy as sp

from Engines.NoteWriter import _find_all, _group_columns, _kids, _parse, _text

X = sp.Symbol("x")
Y = sp.Function("y")(X)
FUNCS = {"ln": sp.log, "log": sp.log, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "exp": sp.exp, "sqrt": sp.sqrt}
SKIP = ("\\left", "\\right", "\\,", "\\;", "\\!", "\\ ", "\\quad", "\\displaystyle")
MAX_TEX = 300


class Unreadable(Exception):
    pass


# ── LaTeX -> SymPy ────────────────────────────────────────────────────────────

_TOKEN = re.compile(r"""
    (?P<num>\d+(?:[.,]\d+)?)
  | (?P<cmd>\\[a-zA-Z]+|\\[,;!\ ])
  | (?P<letter>[a-zA-Z])
  | (?P<op>[-+*/^_(){}\[\]'])
  | (?P<space>\s+)
""", re.X)


def _tokens(tex: str) -> list:
    out, i = [], 0
    while i < len(tex):
        m = _TOKEN.match(tex, i)
        if not m:
            raise Unreadable(tex[i])
        i = m.end()
        kind, text = m.lastgroup, m.group()
        if kind == "space" or text in SKIP:
            continue
        if kind == "cmd":
            name = text[1:]
            if name in ("cdot", "times"):
                out.append(("op", "*"))
            elif name in FUNCS:
                out.append(("func", name))
            elif name in ("frac", "dfrac", "tfrac"):
                out.append(("frac", ""))
            elif name == "pi":
                out.append(("const", sp.pi))
            else:
                raise Unreadable(text)             # \int, \begin, \vec, …
            continue
        if kind == "letter":                       # "ln(", "sin(" written as plain letters
            for name in ("sqrt", "sin", "cos", "tan", "exp", "log", "ln"):
                if tex.startswith(name, m.start()) and tex[m.start() + len(name):].lstrip()[:1] in ("(", "{", "\\"):
                    out.append(("func", name))
                    i = m.start() + len(name)
                    break
            else:
                out.append(("letter", text))
            continue
        out.append((kind, text))
    return out


class _Parser:
    def __init__(self, tex: str):
        self.t = _tokens(tex)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None, text=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (text and v != text):
            raise Unreadable(f"expected {text or kind}")
        self.i += 1
        return v

    def at(self, text) -> bool:
        return self.peek() == ("op", text)

    def expr(self):
        sign = 1
        while self.at("+") or self.at("-"):
            sign *= -1 if self.take() == "-" else 1
        value = sign * self.term()
        while self.at("+") or self.at("-"):
            value = value + self.term() if self.take() == "+" else value - self.term()
        return value

    def starts_factor(self) -> bool:
        k, v = self.peek()
        return k in ("num", "letter", "func", "frac", "const") or (k == "op" and v in "({")

    def term(self):
        value = self.factor()
        while True:
            if self.at("*"):
                self.take()
                value = value * self.signed_factor()
            elif self.at("/"):
                self.take()
                value = value / self.signed_factor()
            elif self.starts_factor():             # 2x, x(x+1), 4 e^{3x}
                value = value * self.factor()
            else:
                return value

    def signed_factor(self):
        if self.at("-"):
            self.take()
            return -self.factor()
        return self.factor()

    def factor(self):
        base = self.atom()
        if self.at("^"):
            self.take()
            return base ** self.small()
        return base

    def small(self):
        """What a ^ or \\frac takes without braces: {…}, or one token (x^2, x^\\frac{1}{2}; x^12 is x^1 · 2)."""
        k, v = self.peek()
        if self.at("{"):
            return self.group("{", "}")
        if k == "num" and len(v) > 1 and v.isdigit():
            self.t[self.i] = ("num", v[1:])
            return sp.Integer(v[0])
        if self.at("-"):
            self.take()
            return -self.small()
        return self.atom()

    def group(self, open_, close):
        self.take("op", open_)
        value = self.expr()
        self.take("op", close)
        return value

    def atom(self):
        k, v = self.peek()
        if k == "num":
            self.take()
            return sp.Rational(v.replace(",", "."))
        if k == "const":
            self.take()
            return v
        if k == "frac":
            self.take()
            return self.small() / self.small()
        if k == "func":
            self.take()
            if v == "sqrt" and self.at("["):
                n = self.group("[", "]")
                return self.argument() ** (1 / n)
            fn = FUNCS[v]
            if self.at("^"):                        # sin^2 x
                self.take()
                power = self.small()
                return fn(self.argument()) ** power
            return fn(self.argument())
        if k == "letter":
            self.take()
            return self.letter(v)
        if self.at("("):
            return self.group("(", ")")
        if self.at("{"):
            return self.group("{", "}")
        raise Unreadable(str(v))

    def argument(self):
        if self.at("("):
            return self.group("(", ")")
        if self.at("{"):
            return self.group("{", "}")
        return self.factor()

    def letter(self, v):
        if v == "y":
            order = 0
            while self.at("'"):
                self.take()
                order += 1
            if self.at("("):                        # y(x) is y; y(2) only makes sense on the left of a condition
                save = self.i
                if self.group("(", ")") != X:
                    self.i = save
                    raise Unreadable("y(…)")
            return sp.Derivative(Y, (X, order)) if order else Y
        if self.at("'"):
            raise Unreadable(v + "'")
        if v == "x":
            return X
        if v == "e":
            return sp.E
        if self.at("_"):
            self.take()
            k, sub = self.peek()
            if self.at("{"):
                self.take()
                sub = ""
                while not self.at("}"):
                    sub += str(self.take())
                self.take()
            elif k in ("num", "letter"):
                self.take()
            else:
                raise Unreadable("_")
            return sp.Symbol(f"{v}_{sub}")
        return sp.Symbol(v)


def parse_expr(tex: str):
    """A formula's side as a SymPy expression, or None when it isn't something this can read."""
    tex = (tex or "").strip()
    if not tex or len(tex) > MAX_TEX:
        return None
    try:
        p = _Parser(tex)
        value = p.expr()
        if p.i != len(p.t):
            return None
        return sp.sympify(value)
    except (Unreadable, ZeroDivisionError, TypeError, ValueError, RecursionError, sp.SympifyError):
        return None


# ── what a formula says ───────────────────────────────────────────────────────

_ODE = re.compile(r"^y('+)(?:\(x\))?$")
_COND = re.compile(r"^y('*)\(([-+]?\d+(?:[.,]\d+)?)\)$")
_ANSWER = re.compile(r"^y(?:\(x\))?$")
_LEIBNIZ = re.compile(r"^\\[dt]?frac\{dy\}\{dx\}$")


@dataclass
class Fact:
    kind: str                 # "ode", "cond" or "answer"
    rhs: object
    order: int = 0            # how many dashes: y'' is 2
    at: object = None         # the x of a condition
    decimal: bool = False     # written with decimals (0,25): shown that way again


def _sides(tex: str) -> list:
    """Split at the = signs outside braces ("y' = \\int … dx = 0,04x^3 + C" has three sides)."""
    parts, depth, cur = [], 0, ""
    for ch in tex:
        depth += ch == "{"
        depth -= ch == "}"
        if ch == "=" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def read(tex: str) -> Fact | None:
    fact = _read(tex)
    if fact:
        fact.decimal = bool(re.search(r"\d[.,]\d", tex))
    return fact


def _read(tex: str) -> Fact | None:
    sides = _sides(tex or "")
    if len(sides) < 2:
        return None
    lhs = re.sub(r"\s+|\\left|\\right", "", sides[0])
    rhs = parse_expr(sides[-1])                     # the last side: what it finally comes to
    if rhs is None:
        return None
    if _LEIBNIZ.match(lhs):
        return Fact("ode", rhs, 1)
    m = _ODE.match(lhs)
    if m:
        return Fact("ode", rhs, len(m.group(1)))
    m = _COND.match(lhs)
    if m:
        return Fact("cond", rhs, len(m.group(1)), sp.Rational(m.group(2).replace(",", "."))) \
            if not rhs.free_symbols else None
    if _ANSWER.match(lhs) and not rhs.has(Y):
        return Fact("answer", rhs)
    return None


# ── the exercises of a note ───────────────────────────────────────────────────

LABEL = re.compile(r"^\s*(\d+\.\d+)\s*\)?\s*(?:([a-h])\s*\))?")
PART = re.compile(r"^\s*([a-h])\s*\)")


@dataclass
class Exercise:
    label: str
    lines: list = field(default_factory=list)      # each: the formulas (LaTeX) of one line, in order

    @property
    def formulas(self) -> list:
        return [f for line in self.lines for f in line]


def _formulas(nodes) -> list:
    out = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n["attrs"].get("data-type") in ("inline-math", "block-math"):
            out.append(n["attrs"].get("data-latex", ""))
        else:
            out += _formulas(n["children"])
    return out


def _label(text: str, number: str = "") -> str:
    m = LABEL.match(text)
    if m:
        return m.group(1) + (" " + m.group(2) if m.group(2) else "")
    m = PART.match(text)
    return f"{number} {m.group(1)}".strip() if m and number else ""


def exercises(content: str) -> list:
    found, cur = [], None

    def side_by_side(rows):
        """rows: each a list of cells (lists of nodes). A header row with numbers starts one exercise per column."""
        nonlocal cur
        texts = ["".join(_text(n) if isinstance(n, dict) else n for n in cell) for cell in rows[0]]
        number = (LABEL.match(next((t for t in texts if LABEL.match(t)), "")) or [None, ""])[1] or \
                 (cur.label.split(" ")[0] if cur else "")
        labels = [_label(t, number) for t in texts]
        if sum(bool(l) for l in labels) >= 2:
            cols = [Exercise(l) if l else None for l in labels]
            for row in rows:
                for col, cell in zip(cols, row):
                    if col is not None and _formulas(cell):
                        col.lines.append(_formulas(cell))
            found.extend(c for c in cols if c is not None)
            cur = None
        elif cur is not None:                       # no column headings: all of it belongs to the open exercise
            for row in rows:
                line = [f for cell in row for f in _formulas(cell)]
                if line:
                    cur.lines.append(line)

    for n in _group_columns(_parse(content)["children"]):
        if not isinstance(n, dict):
            continue
        tag = n["tag"]
        if tag == "columns":
            side_by_side(n["rows"])
        elif tag == "table":
            rows = [[c["children"] for c in _kids(tr, "td", "th")] for tr in _find_all(n, "tr")]
            if rows:
                side_by_side(rows)
        elif re.fullmatch(r"h[1-6]", tag):
            cur = None
        elif tag == "p" or n["attrs"].get("data-type") == "block-math":
            label = _label(_text(n)) if tag == "p" else ""
            if label:
                cur = Exercise(label)
                found.append(cur)
            line = _formulas([n])
            if cur is not None and line:
                cur.lines.append(line)
    return found


# ── checking one exercise ─────────────────────────────────────────────────────

def _zero(e) -> bool:
    try:
        e = sp.simplify(e)
    except Exception:
        pass
    if e == 0:
        return True
    names = sorted(e.free_symbols, key=str)
    for k, x0 in enumerate((sp.Rational(7, 10), sp.Rational(13, 10), sp.Rational(21, 10))):
        values = {s: (x0 if s == X else sp.Rational(37 + 11 * i + 5 * k, 100)) for i, s in enumerate(names)}
        try:
            if abs(complex(sp.N(e.subs(values), 30))) > 1e-12:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _decimals(e):
    """Fractions that are plain decimals (3/25 = 0.12) written as decimals; exponents stay fractions."""
    if e.is_Rational and not e.is_Integer:
        q = e.q
        for p in (2, 5):
            while q % p == 0:
                q //= p
        if q == 1:
            return sp.Symbol(f"{float(abs(e)):.10g}") * (-1 if e < 0 else 1)
        return e
    if e.is_Pow:
        return sp.Pow(_decimals(e.base), e.exp, evaluate=False)
    if e.args:
        return e.func(*[_decimals(a) for a in e.args])
    return e


def show(e, decimal: bool = False) -> str:
    """An expression the way it's written by hand: x^3/12 + x - 5/3, 4e^(x^3), 0.12x^2."""
    if decimal:
        try:
            e = _decimals(e)
        except Exception:
            pass
    s = sp.sstr(e).replace("exp(", "e^(").replace("log(", "ln(").replace("**", "^")
    s = re.sub(r"(?<![\w.^])(\d+(?:\.\d+)?)\*(?=[a-zA-Z(])", r"\1", s)     # 2*x -> 2x (but C_2·x, x^2·y)
    return s.replace("*", "·")


def _num(v) -> str:
    v = sp.nsimplify(v)
    if v.is_Integer:
        return str(int(v))
    return f"{float(v):.4g}"


def _lhs(order: int, at=None) -> str:
    return "y" + "'" * order + (f"({_num(at)})" if at is not None else "")


def _right_answer(ode: Fact, conds: list):
    """The solution worked out exactly (None if SymPy can't): with the conditions if there are enough of them."""
    try:
        if not ode.rhs.has(Y):                      # y'' = f(x): integrate, one constant each time
            sol = ode.rhs
            consts = []
            for i in range(ode.order):
                c = sp.Symbol(f"C_{ode.order - i}")
                consts.append(c)
                sol = sp.integrate(sol, X) + c
            if sol.has(sp.Integral):
                return None
        else:
            hints = ("separable", "1st_linear") if ode.order == 1 else \
                ("nth_linear_constant_coeff_homogeneous", "nth_linear_constant_coeff_undetermined_coefficients")
            sol = None
            for hint in hints:
                try:
                    res = sp.dsolve(sp.Eq(Y.diff(X, ode.order), ode.rhs), Y, hint=hint)
                    res = res[0] if isinstance(res, list) else res
                    if res.lhs == Y:
                        sol = res.rhs
                        break
                except (NotImplementedError, ValueError):
                    continue
            if sol is None:
                return None
            consts = sorted(sol.free_symbols - {X}, key=str)
            named = {c: sp.Symbol(re.sub(r"^C(\d+)$", r"C_\1", c.name)) for c in consts}
            sol, consts = sol.subs(named), [named[c] for c in consts]
        if conds and len(conds) == ode.order == len(consts):
            eqs = [sp.Eq(sol.diff(X, c.order).subs(X, c.at), c.rhs) for c in conds]
            fixed = sp.solve(eqs, consts, dict=True)
            if len(fixed) == 1:
                sol = sol.subs(fixed[0])
        return sp.simplify(sol) if sol.has(sp.exp, sp.log) else sp.expand(sol)
    except Exception:
        return None


def check(ex: Exercise) -> tuple[str, str]:
    """(verdict, sentence): verdict is correct / almost / wrong / open / unclear / none."""
    facts, ode, ode_line = [], None, None
    for i, line in enumerate(ex.lines):
        read_line = [f for f in (read(t) for t in line) if f]
        odes = [f for f in read_line if f.kind == "ode"]
        if ode is None and odes:
            if any(o.order != odes[0].order or not _zero(o.rhs - odes[0].rhs) for o in odes[1:]):
                return "unclear", ("I can't tell the exercises in that line apart: two different equations are in "
                                   "one line. Put each one in its own column or on its own lines.")
            ode, ode_line = odes[0], i
        facts += [(i, f) for f in read_line]
    if ode is None:
        return "none", ""
    eq = f"{_lhs(ode.order)} = {show(ode.rhs.subs(Y, sp.Symbol('y')), ode.decimal)}"
    conds = []
    for _, f in facts:
        if f.kind == "cond" and not any(c.order == f.order and c.at == f.at for c in conds):
            conds.append(f)
    answers = [f for i, f in facts if f.kind == "answer" and i >= ode_line]
    if not answers:
        return "open", f"no final answer yet: I see {eq} but no line \"y = …\" after it."
    ans = answers[-1].rhs
    dec = ode.decimal or answers[-1].decimal
    consts = ans.free_symbols - {X}
    fits = _zero(ans.diff(X, ode.order) - ode.rhs.subs(Y, ans))
    mine = f"y = {show(ans, dec)}"

    if consts:                                      # a general solution: the conditions aren't worked in (yet)
        if not fits:
            right = _right_answer(ode, [])
            return "wrong", (f"not right yet. Your {mine} doesn't fit {eq}."
                             + (f" It should be y = {show(right, dec)}." if right is not None else ""))
        if len(consts) < ode.order:
            return "almost", (f"almost. Your {mine} fits {eq}, but a {_lhs(ode.order)} equation needs "
                              f"{ode.order} constants and yours has {len(consts)}.")
        if conds:
            return "almost", (f"almost. Your general solution {mine} fits {eq}; the constants from "
                              f"{' and '.join(f'{_lhs(c.order, c.at)} = {_num(c.rhs)}' for c in conds)} are still open.")
        return "correct", f"correct. Your general solution {mine} fits {eq}."

    good, bad = [], []
    for c in conds:
        value = ans.diff(X, c.order).subs(X, c.at)
        name = _lhs(c.order, c.at)
        if _zero(value - c.rhs):
            good.append(f"{name} = {_num(c.rhs)}")
        else:
            bad.append(f"{name} is {_num(value)}, not {_num(c.rhs)}")
    if fits and not bad:
        return "correct", f"correct. Your {mine} fits {eq}" + (f" and {' and '.join(good)}." if good else ".")
    parts = [f"Your {mine} " + (f"fits {eq}" if fits else f"doesn't fit {eq}")]
    if bad:
        parts.append(("but " if fits else "and ") + " and ".join(bad))
    said = ", ".join(parts) + "."
    if good:
        said += f" {' and '.join(good)} is fine."
    right = _right_answer(ode, conds)
    if right is not None:
        said += f" It should be y = {show(right, dec)}."
    return "wrong", "not right yet. " + said


# ── the whole note ────────────────────────────────────────────────────────────

def _same(label: str, asked: str) -> bool:
    norm = lambda s: re.sub(r"[\s)(]+", "", s.lower())
    a, b = norm(label), norm(asked)
    return a == b or (a.startswith(b) and not b[-1:].isalpha() and a[len(b):].isalpha())


def _list(names: list) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def check_note(content: str, exercise: str = "") -> str:
    found = exercises(content)
    results = [(ex, *check(ex)) for ex in found]
    checkable = [(ex, v, s) for ex, v, s in results if v != "none"]
    exercise = (exercise or "").strip()
    if exercise:
        wanted = [(ex, v, s) for ex, v, s in results if _same(ex.label, exercise)]
        if not wanted:
            have = [ex.label for ex, _, _ in checkable]
            return (f"I couldn't find exercise {exercise} in the note."
                    + (f" I can check {_list(have)}." if have else ""))
        if all(v == "none" for _, v, _ in wanted):
            return (f"I see no differential equation in {exercise} that I can check (I need a line like "
                    "y' = … and a final y = …).")
        checkable = [(ex, v, s) for ex, v, s in wanted if v != "none"]
    if not checkable:
        return ("I found no differential equation to check in this note. I need numbered exercises (\"4.15)\") "
                "with a line like y' = … and a final y = ….")
    return "\n".join(f"{ex.label}: {s}" for ex, v, s in checkable)


def check_in_note(notion, title: str = "this", exercise: str = "") -> str:
    """The tool: the note open in MyNotion (or named), checked; the answer is final, the model doesn't reword it."""
    from llm_engine import FINAL_PREFIX
    note = notion.resolve_note(title)
    if not note:
        if notion.is_this(title):
            return "Which note? I can't see one open in MyNotion. Say its name."
        return f"I couldn't find a note called '{title}'."
    return FINAL_PREFIX + check_note(note["content"] or "", exercise)

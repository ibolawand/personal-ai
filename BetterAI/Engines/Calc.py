"""
Exact maths and unit conversion, because a small language model guesses at arithmetic.

calculate("17% of 2340"), calculate("(46.8 * 1.18) / 3"), calculate("sqrt(2) * 10")
convert(5, "km", "miles"), convert(180, "cm", "feet"), convert(20, "c", "f")

Expressions are parsed with Python's ast and only numbers, + - * / // % ** and a few math functions are allowed —
nothing is ever executed with eval.
"""

import ast
import math
import operator
import re

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
       ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "sin": lambda x: math.sin(math.radians(x)),
         "cos": lambda x: math.cos(math.radians(x)), "tan": lambda x: math.tan(math.radians(x)),
         "log": math.log10, "ln": math.log, "floor": math.floor, "ceil": math.ceil}
CONSTS = {"pi": math.pi, "e": math.e}

# unit -> (dimension, factor to the base unit)
UNITS = {
    "mm": ("len", 0.001), "cm": ("len", 0.01), "m": ("len", 1), "km": ("len", 1000), "in": ("len", 0.0254),
    "ft": ("len", 0.3048), "yd": ("len", 0.9144), "mi": ("len", 1609.344),
    "mg": ("mass", 1e-6), "g": ("mass", 0.001), "kg": ("mass", 1), "t": ("mass", 1000), "oz": ("mass", 0.0283495),
    "lb": ("mass", 0.453592), "st": ("mass", 6.35029),
    "ml": ("vol", 0.001), "cl": ("vol", 0.01), "l": ("vol", 1), "cup": ("vol", 0.24), "floz": ("vol", 0.0295735),
    "gal": ("vol", 3.78541), "tbsp": ("vol", 0.0147868), "tsp": ("vol", 0.00492892),
    "kmh": ("speed", 1 / 3.6), "mph": ("speed", 0.44704), "ms": ("speed", 1),
    "b": ("data", 1), "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9), "tb": ("data", 1e12),
    "s": ("time", 1), "min": ("time", 60), "h": ("time", 3600), "day": ("time", 86400), "week": ("time", 604800),
}
ALIASES = {"millimeter": "mm", "centimeter": "cm", "meter": "m", "metre": "m", "kilometer": "km", "kilometre": "km",
           "inch": "in", "inches": "in", "foot": "ft", "feet": "ft", "yard": "yd", "mile": "mi", "miles": "mi",
           "gram": "g", "kilogram": "kg", "kilo": "kg", "kilos": "kg", "ton": "t", "tonne": "t", "ounce": "oz",
           "pound": "lb", "pounds": "lb", "lbs": "lb", "stone": "st", "liter": "l", "litre": "l",
           "milliliter": "ml", "millilitre": "ml", "cups": "cup", "gallon": "gal", "tablespoon": "tbsp",
           "teaspoon": "tsp", "km/h": "kmh", "kph": "kmh", "m/s": "ms", "second": "s", "sec": "s", "minute": "min",
           "hour": "h", "hr": "h", "days": "day", "weeks": "week", "byte": "b", "kilobyte": "kb", "megabyte": "mb",
           "gigabyte": "gb", "terabyte": "tb", "celsius": "c", "°c": "c", "fahrenheit": "f", "°f": "f", "kelvin": "k"}


def _num(x) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        x = int(x)
    if isinstance(x, int):
        return f"{x:,}" if abs(x) >= 1000 else str(x)
    if abs(x) >= 1e6:
        return f"{x:,.6g}"
    r = round(x, 4)
    return f"{r:,}" if abs(r) >= 1000 else f"{r:g}"


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("that power is too big")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS:
        return FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in CONSTS:
        return CONSTS[node.id]
    raise ValueError("only numbers and basic maths are allowed")


def _prepare(expr: str) -> str:
    s = expr.lower().strip().rstrip("?=. ")
    s = s.replace("×", "*").replace("x", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    s = re.sub(r"\bwhat(?:'s| is)\b|\bcalculate\b|\bhow much is\b", "", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"\1/100*", s)            # 17% of 2340
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)                   # 5% alone
    s = re.sub(r"\bplus\b", "+", s)
    s = re.sub(r"\bminus\b", "-", s)
    s = re.sub(r"\btimes\b|\bmultiplied by\b", "*", s)
    s = re.sub(r"\bdivided by\b|\bover\b", "/", s)
    s = re.sub(r"\bsquared\b", "**2", s)
    s = re.sub(r"\bsquare root of\s*([\d.]+)", r"sqrt(\1)", s)
    return s.strip()


def calculate(expression: str):
    try:
        value = _eval(ast.parse(_prepare(expression), mode="eval"))
    except ZeroDivisionError:
        return "That divides by zero."
    except (SyntaxError, ValueError, TypeError) as e:
        return f"I can't calculate '{expression}': {e if isinstance(e, ValueError) else 'not a maths expression'}."
    return f"{expression.strip()} = {_num(value)}"


def _unit(u: str) -> str:
    u = u.strip().lower().rstrip(".")
    u = ALIASES.get(u, ALIASES.get(u.rstrip("s"), u))
    return u


def convert(value, from_unit: str, to_unit: str):
    try:
        v = float(str(value).replace(",", "."))
    except ValueError:
        return f"'{value}' isn't a number."
    a, b = _unit(from_unit), _unit(to_unit)
    temps = {"c", "f", "k"}
    if a in temps and b in temps:
        c = v if a == "c" else (v - 32) * 5 / 9 if a == "f" else v - 273.15
        out = c if b == "c" else c * 9 / 5 + 32 if b == "f" else c + 273.15
        return f"{_num(v)} °{a.upper()} = {_num(round(out, 2))} °{b.upper()}"
    if a not in UNITS or b not in UNITS:
        bad = a if a not in UNITS else b
        return f"I don't know the unit '{bad}'."
    if UNITS[a][0] != UNITS[b][0]:
        return f"I can't convert {from_unit} to {to_unit}, they measure different things."
    out = v * UNITS[a][1] / UNITS[b][1]
    return f"{_num(v)} {from_unit} = {_num(round(out, 4))} {to_unit}"


def split_bill(total, people=1, tip_percent=0):
    """'The bill was 87.40, 3 people, 15% tip' -> each pays (bill + tip) / people."""
    try:
        total, people, tip = float(total), max(1, int(float(people))), float(tip_percent or 0)
    except (TypeError, ValueError):
        return "I need the bill amount, how many people, and the tip in percent."
    tip_amount = total * tip / 100
    each = (total + tip_amount) / people
    out = f"Bill {total:.2f}"
    if tip:
        out += f" + {tip:g}% tip ({tip_amount:.2f}) = {total + tip_amount:.2f}"
    return out + (f", split {people} ways: {each:.2f} each." if people > 1 else ".")

import pytest

from Engines.Calc import calculate, convert


@pytest.mark.parametrize("expr,result", [
    ("17% of 2340", "397.8"), ("(12 + 7) * 3", "57"), ("46.8 * 1.18 / 3", "18.408"), ("2^10", "1,024"),
    ("100 divided by 8", "12.5"), ("7 times 6", "42"), ("square root of 81", "9"), ("5 squared", "25"),
    ("what is 15 plus 27?", "42"), ("10 / 3", "3.3333"),
])
def test_calculate(expr, result):
    assert calculate(expr).endswith("= " + result)


@pytest.mark.parametrize("expr", ["__import__('os').system('ls')", "open('x')", "2 ** 99999", "hello"])
def test_calculate_refuses_anything_but_maths(expr):
    assert calculate(expr).startswith("I can't calculate")


def test_divide_by_zero():
    assert calculate("5 / 0") == "That divides by zero."


@pytest.mark.parametrize("args,result", [
    ((5, "km", "miles"), "5 km = 3.1069 miles"), ((180, "cm", "feet"), "180 cm = 5.9055 feet"),
    ((20, "C", "F"), "20 °C = 68 °F"), ((98.6, "fahrenheit", "celsius"), "98.6 °F = 37 °C"),
    ((2, "cups", "ml"), "2 cups = 480 ml"), ((1.5, "GB", "MB"), "1.5 GB = 1,500 MB"),
])
def test_convert(args, result):
    assert convert(*args) == result


def test_convert_mismatch_and_unknown():
    assert "different things" in convert(5, "kg", "km")
    assert "don't know the unit" in convert(5, "parsecs", "km")


def test_split_bill():
    from Engines.Calc import split_bill
    assert split_bill(87.40, 3, 15) == "Bill 87.40 + 15% tip (13.11) = 100.51, split 3 ways: 33.50 each."
    assert split_bill(20, 1) == "Bill 20.00."

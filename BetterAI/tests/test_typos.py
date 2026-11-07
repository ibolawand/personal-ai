import pytest

from Engines.Typos import fix_typos


@pytest.mark.parametrize("typed,fixed", [
    ("ope n notes", "open notes"),
    ("pla y some music", "play some music"),
    ("opne my calender", "open my calendar"),
    ("pley no excuses", "play no excuses"),
    ("remidn me tommorow at 6", "remind me tomorrow at 6"),
    ("is there anything on my calender pitch", "is there anything on my calendar pitch"),
    ("whats the wether", "whats the weather"),
    ("can u turn the volumn down", "can you turn the volume down"),
    # left alone
    ("open notes", "open notes"),
    ("pitch", "pitch"),
    ("a d", "a d"),
    ("hello there", "hello there"),
    ("i am just bored", "i am just bored"),
    ("plan my week", "plan my week"),
    ("", ""),
])
def test_fix_typos(typed, fixed):
    assert fix_typos(typed) == fixed

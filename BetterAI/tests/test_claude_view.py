"""Where Claude's figure stands beside Aria (ui/claude_view.py) and what his page is told."""
from ui.claude_view import place_beside, ClaudeLink, SIZE, OVERLAP

SCREEN = (0, 0, 1920, 1050)


def test_he_stands_on_her_left_with_his_feet_level_with_hers():
    x, y, side = place_beside((1500, 600, 300, 400), SCREEN)
    assert (x, y, side) == (1500 - SIZE[0] + OVERLAP, 600 + 400 - SIZE[1], 1)


def test_at_the_left_edge_he_stands_on_her_right_and_turns_the_other_way():
    x, y, side = place_beside((50, 600, 300, 400), SCREEN)
    assert side == -1 and x == 50 + 300 - OVERLAP


def test_he_stays_on_the_screen():
    x, y, _ = place_beside((1700, 900, 120, 120), SCREEN)       # next to the orb, low on the screen
    assert 0 <= x <= 1920 - SIZE[0] and 0 <= y <= 1050 - SIZE[1]


def test_calls_wait_for_his_page_and_repeats_are_skipped():
    sent = []
    link = ClaudeLink(sent.append)
    link.set_side(1)
    link.enter()
    link.set_state("talking")
    link.set_state("talking")
    assert sent == []
    link.mark_ready()
    assert sent == ["window.claude.setSide(1)", "window.claude.setState(\"talking\")", "window.claude.enter()"]

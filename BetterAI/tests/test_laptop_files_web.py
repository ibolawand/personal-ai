"""Apps from the menu, file search (names and contents), web search parsing."""

import os
from pathlib import Path

import pytest

import Engines.LaptopEngine as L
from Engines.FilesEngine import FilesEngine


# ── apps ──

DESKTOP_FILES = {
    "CiscoPacketTracer-9.0.1": "Name=Cisco Packet Tracer 9.0.1\nExec=/opt/pt/packettracer.AppImage %f",
    "CiscoPacketTracerPtsa-9.0.1": "Name=Cisco Packet Tracer Ptsa 9.0.1\nExec=/opt/pt/ptsa.AppImage",
    "discord": "Name=Discord\nExec=/usr/bin/discord",
    "libreoffice-writer": "Name=LibreOffice Writer\nGenericName=Word Processor\nExec=libreoffice --writer",
    "firefox": "Name=Firefox Web Browser\nGenericName=Web Browser\nExec=firefox %u",
    "hidden": "Name=Hidden Helper\nExec=helper\nNoDisplay=true",
}


@pytest.fixture
def menu(tmp_path, monkeypatch):
    for name, body in DESKTOP_FILES.items():
        (tmp_path / f"{name}.desktop").write_text(f"[Desktop Entry]\nType=Application\n{body}\n")
    monkeypatch.setattr(L, "MENU_DIRS", [str(tmp_path)])
    return L.MenuApps()


@pytest.mark.parametrize("query,expected", [
    ("packet tracer", "Cisco Packet Tracer 9.0.1"), ("my packet tracer", "Cisco Packet Tracer 9.0.1"),
    ("discord", "Discord"), ("writer", "LibreOffice Writer"), ("web browser", "Firefox Web Browser"),
    ("hidden helper", None), ("asdfgh", None),
])
def test_menu_matching(menu, query, expected):
    found = menu.find(query)
    assert (found["name"] if found else None) == expected


def test_discord_is_not_vscode():
    # regression: the old fuzzy matcher sent "discord" to VS Code
    assert L._match_app("discord") is None
    assert L._match_app("pycharn") == "pycharm"
    assert L._match_app("vs code") == "vscode"


def test_open_app_launches_menu_entries(menu, monkeypatch):
    launched = []
    monkeypatch.setattr(L, "_launch", launched.append)
    lp = L.LaptopEngine(None)
    lp.menu = menu
    lp._windows = lambda: []
    assert lp.open_app("discord") == "Opening Discord."
    assert launched == [["gtk-launch", "discord"]]
    assert "couldn't find" in lp.open_app("gimp")


# ── files ──

@pytest.fixture
def files(tmp_path, monkeypatch):
    import Engines.FilesEngine as F
    root = tmp_path / "school"
    (root / "dbs").mkdir(parents=True)
    (root / "dbs" / "week3.md").write_text("Normalization: first, second and third normal form. Primary keys.")
    (root / "networks.txt").write_text("Subnetting a /24 into four /26 networks.")
    (root / "plsql_cursors.txt").write_text("cursor loops")
    monkeypatch.setattr(F, "INDEX_FILE", tmp_path / "index.db")
    return FilesEngine(None, roots=[str(root)])


def test_find_by_name(files):
    assert "plsql_cursors.txt" in files.find_files("plsql")


def test_search_inside_documents(files):
    out = files.search_contents("third normal form")
    assert out.startswith("Documents that mention") and "week3.md" in out
    assert files.last_results[0].name == "week3.md"          # so "open the first one" works


def test_name_search_falls_back_to_contents(files):
    out = files.find_files("subnetting")
    assert "networks.txt" in out and "No file names match" in out


def test_index_drops_deleted_files(files, tmp_path):
    files.update_index()
    (tmp_path / "school" / "networks.txt").unlink()
    files.update_index()
    assert "No document mentions" in files.search_contents("subnetting")


def test_files_outside_the_allowed_folders_are_refused(files, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    assert "outside" in files.read_file(str(outside))


# ── web search ──

def test_question_words_are_removed_for_wikipedia(monkeypatch):
    import Engines.WebSearch as W
    seen = {}

    def fake_get_json(url, params):
        seen.update(params)
        return {"query": {"pages": {"1": {"title": "Photosynthesis", "index": 2, "extract": "Plants make sugar."},
                                    "2": {"title": "C4 carbon fixation", "index": 1, "extract": "A pathway."}}}}
    monkeypatch.setattr(W, "_get_json", fake_get_json)
    out = W.WebSearch()._wikipedia("how does photosynthesis work?")
    assert seen["gsrsearch"] == "photosynthesis"
    assert out[0].startswith("[Wikipedia: Photosynthesis]")       # exact title first, despite search rank


def test_page_text_keeps_sentences_not_menus():
    p = __import__("Engines.WebSearch", fromlist=["_TextExtractor"])._TextExtractor()
    p.feed("<nav>Home About</nav><p>" + "This is a real sentence that is long enough to keep. " * 2 + "</p>"
           "<script>var x=1;</script>")
    text = "".join(p.parts)
    assert "real sentence" in text and "Home About" not in text and "var x" not in text

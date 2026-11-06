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


# ── Spotify ──

def _track(name, artist, popularity):
    return {"name": name, "artists": [{"name": artist}], "popularity": popularity, "uri": f"spotify:{name}"}


def test_spotify_picks_the_matching_song_not_the_most_popular():
    # regression: "NF No Excuses" played "DROP!" by Forrest Frank (more popular)
    from Controller.Spotify_controll import SpotifyEngine
    tracks = [_track("No Excuses", "NF", 59), _track("DROP!", "Forrest Frank", 64), _track("NO EXCUSES", "NEFFEX", 46)]
    best, sure = SpotifyEngine._best_track_match(tracks, "NF No Excuses")
    assert (best["name"], best["artists"][0]["name"], sure) == ("No Excuses", "NF", 1.0)


def test_spotify_avoids_remixes_unless_asked():
    from Controller.Spotify_controll import SpotifyEngine
    tracks = [_track("Hope - Remix", "NF", 70), _track("Hope", "NF", 60)]
    assert SpotifyEngine._best_track_match(tracks, "hope nf")[0]["name"] == "Hope"
    assert SpotifyEngine._best_track_match(tracks, "hope remix nf")[0]["name"] == "Hope - Remix"


def test_spotify_errors_become_sentences():
    import spotipy
    from Controller.Spotify_controll import friendly_errors

    @friendly_errors
    def boom():
        raise spotipy.SpotifyException(403, -1, "Player command failed: Premium required", reason="PREMIUM_REQUIRED")
    assert "Premium" in boom()


def test_network_status_is_read_only(monkeypatch):
    calls = []
    outputs = {"general": "enabled\n", "connection": "Home-5G:802-11-wireless\nlo:loopback\n",
               "show": "Controller x\n\tPowered: yes\n", "devices": "Device AA:BB Galaxy Buds\n"}

    def fake_run(cmd, timeout=5):
        calls.append(cmd)
        key = next(k for k in outputs if k in cmd)
        return outputs[key]
    monkeypatch.setattr(L, "_run", fake_run)
    out = L.LaptopEngine(None).network_status()
    assert out == "Wi-Fi is on, connected to Home-5G; Bluetooth is on, connected to Galaxy Buds."
    assert not any(c[:3] == ["nmcli", "radio", "wifi"] for c in calls)        # never switches anything

import functools
import random
import re
import shutil
import subprocess
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

DEVICE_WAIT_S = 15        # after opening the Spotify app, wait this long for it to show up as a device


def _words(text):
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()


def friendly_errors(fn):
    """Spotify API errors -> a sentence Aria can say, instead of '<tool> failed: http status 403'."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as e:
            msg = f"{e.http_status} {getattr(e, 'reason', '')} {e.msg}".lower()
            if e.http_status == 403 and "premium" in msg:
                return "Spotify only lets apps control playback with a Premium account."
            if e.http_status == 404 or "no active device" in msg:
                return "Spotify isn't running on any device right now. Open Spotify and try again."
            if e.http_status == 401:
                return "My Spotify login expired. Restart me and log in to Spotify again."
            return f"Spotify said no: {e.msg}"
    return wrapper


class SpotifyEngine:
    def __init__(self, client_id, client_secret, market=None):
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:8888/callback",
            scope="user-modify-playback-state user-read-playback-state user-read-currently-playing playlist-read-private"
        ))

        # Resolve the market once at startup instead of never passing one.
        # Without this, search results can rank/include tracks that aren't
        # even available in your actual Spotify catalog, which is a common
        # cause of "wrong song" results.
        if market:
            self.market = market
        else:
            try:
                self.market = self.sp.current_user().get("country", "AT")
            except Exception:
                self.market = "AT"

    def _get_device_id(self, launch=True):
        """The active device, else any device. With none at all, start the Spotify app on this laptop
        and wait for it to appear (the old version just gave up with 'open Spotify first')."""
        devices = self.sp.devices().get("devices", [])
        if not devices and launch and shutil.which("spotify"):
            subprocess.Popen(["spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            end = time.time() + DEVICE_WAIT_S
            while not devices and time.time() < end:
                time.sleep(1)
                devices = self.sp.devices().get("devices", [])
        if not devices:
            return None
        for d in devices:
            if d["is_active"]:
                return d["id"]
        computer = [d for d in devices if d.get("type") == "Computer"]
        return (computer or devices)[0]["id"]

    def play(self):
        device_id = self._get_device_id()
        if device_id:
            self.sp.start_playback(device_id=device_id)

    def pause(self):
        self.sp.pause_playback()

    def skip(self):
        self.sp.next_track()

    def previous(self):
        self.sp.previous_track()

    def find_track(self, query: str):
        """(track, how_sure) for 'no excuses', 'NF no excuses' or 'no excuses by NF'."""
        title, artist = query, None
        m = re.match(r"^(.*\S)\s+(?:by|from|von)\s+(.+)$", query.strip(), re.I)
        if m:
            title, artist = m.group(1), m.group(2)
        tracks = []
        if artist:
            tracks = self.sp.search(q=f"track:{title} artist:{artist}", limit=10, type="track",
                                    market=self.market)["tracks"]["items"]
        if not tracks:
            tracks = self.sp.search(q=query.replace(" by ", " "), limit=10, type="track",
                                    market=self.market)["tracks"]["items"]
        if not tracks:
            return None, 0.0
        return self._best_track_match(tracks, query)

    @friendly_errors
    def play_song(self, query: str):
        if not query or not query.strip():
            return "What do you want me to play?"
        track, sure = self.find_track(query)
        if not track or sure < 0.3:
            return f"I couldn't find '{query}' on Spotify."
        device_id = self._get_device_id()
        if not device_id:
            return "Spotify isn't running and I couldn't start it. Open Spotify and try again."
        self.sp.start_playback(device_id=device_id, uris=[track["uri"]])
        said = f"{track['name']} by {track['artists'][0]['name']}"
        if sure < 0.6:
            return f"I couldn't find exactly '{query}'. The closest was {said}, so that's playing."
        return f"Playing {said}."

    @friendly_errors
    def play_artist(self, artist: str):
        """Look up the actual artist entity and play their real top tracks,
        instead of fuzzy-matching the artist name against track metadata
        (which can surface covers, remixes, or unrelated tracks)."""
        device_id = self._get_device_id()
        if not device_id:
            return "No Spotify devices found."

        artist_results = self.sp.search(q=artist, limit=5, type="artist", market=self.market)
        candidates = artist_results["artists"]["items"]
        if not candidates:
            return f"Couldn't find an artist called '{artist}'"

        # Prefer an exact (case-insensitive) name match over the top search
        # hit, since search can rank a similarly-named artist first.
        exact = [c for c in candidates if c["name"].lower() == artist.lower()]
        best = exact[0] if exact else max(candidates, key=lambda c: c.get("popularity", 0))

        top_tracks = self.sp.artist_top_tracks(best["id"], country=self.market)
        tracks = top_tracks.get("tracks", [])
        if not tracks:
            return f"Couldn't find top tracks for '{best['name']}'"

        uris = [t["uri"] for t in tracks]
        self.sp.start_playback(device_id=device_id, uris=uris)
        return f"Playing tracks by {best['name']}"

    @friendly_errors
    def play_playlist(self, query: str):
        device_id = self._get_device_id()
        if not device_id:
            return "No Spotify devices found."

        results = self.sp.search(q=query, limit=1, type="playlist", market=self.market)
        playlists = results["playlists"]["items"]
        if not playlists:
            return f"Couldn't find playlist '{query}'"

        playlist = playlists[0]
        self.sp.start_playback(device_id=device_id, context_uri=playlist["uri"])
        return f"Playing playlist '{playlist['name']}'"

    @friendly_errors
    def play_genre(self, genre: str):
        """Play music from a genre. The old /recommendations endpoint is
        permanently gone for apps created after Nov 2024, so this stays
        with search — but scoped to market and biased toward well-known
        tracks in that genre rather than an unfiltered dump."""
        device_id = self._get_device_id()
        if not device_id:
            return "No Spotify devices found."

        results = self.sp.search(
            q=f'genre:"{genre.lower()}"', limit=30, type="track", market=self.market
        )
        tracks = results["tracks"]["items"]

        if not tracks:
            return self.play_song(genre)

        # Bias toward more recognizable tracks instead of pure genre-tag noise.
        tracks.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        top_tracks = tracks[:20]
        uris = [t["uri"] for t in top_tracks]
        random.shuffle(uris)
        self.sp.start_playback(device_id=device_id, uris=uris)
        return f"Playing {genre} music"

    @friendly_errors
    def now_playing(self):
        current = self.sp.current_playback()
        if not current or not current["is_playing"]:
            return "Nothing is playing right now."
        track = current["item"]
        return f"{track['name']} by {track['artists'][0]['name']}"

    def set_volume(self, volume: int):
        self.sp.volume(max(0, min(100, volume)))
        return f"Volume set to {volume}%"

    # ---------- internals ----------

    @staticmethod
    def _best_track_match(tracks, query):
        """(track, how_sure 0..1). The track whose title + artists contain the most of the asked words wins;
        Spotify's own ranking and popularity only break ties. (It used to take the most popular result,
        so 'NF No Excuses' played 'DROP!' by Forrest Frank.)"""
        want = [w for w in _words(query) if w not in ("by", "the", "song", "from", "von")]
        best, best_key, best_cov = None, None, 0.0
        for rank, t in enumerate(tracks):
            title = _words(t["name"])
            artists = _words(" ".join(a["name"] for a in t["artists"]))
            have = set(title) | set(artists)
            cov = sum(w in have for w in want) / len(want) if want else 0.0
            title_in_query = bool(title) and all(w in want for w in title)       # "No Excuses" ⊂ "nf no excuses"
            remix = any(w in title for w in ("remix", "cover", "karaoke", "instrumental")) and \
                not any(w in want for w in ("remix", "cover", "karaoke", "instrumental"))
            key = (round(cov, 2), title_in_query, not remix, -rank, t.get("popularity", 0))
            if best_key is None or key > best_key:
                best, best_key, best_cov = t, key, cov
        return best, best_cov
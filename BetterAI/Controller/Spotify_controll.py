import random
import spotipy
from spotipy.oauth2 import SpotifyOAuth


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

    def _get_device_id(self):
        devices = self.sp.devices().get("devices", [])
        if not devices:
            return None
        for d in devices:
            if d["is_active"]:
                return d["id"]
        return devices[0]["id"]

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

    def play_song(self, query: str):
        if not query or not query.strip():
            return "What do you want me to play?"

        device_id = self._get_device_id()
        if not device_id:
            return "No Spotify devices found. Open Spotify first."

        results = self.sp.search(q=query, limit=10, type="track", market=self.market)
        tracks = results["tracks"]["items"]
        if not tracks:
            return f"Couldn't find anything for '{query}'"

        track = self._best_track_match(tracks, query)
        self.sp.start_playback(device_id=device_id, uris=[track["uri"]])
        return f"Playing {track['name']} by {track['artists'][0]['name']}"

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

    def _best_track_match(self, tracks, query):
        """Prefer an exact (case-insensitive) title match, then fall back
        to the highest-popularity result, instead of always taking
        whatever search happened to rank first."""
        query_lower = query.strip().lower()
        exact = [t for t in tracks if t["name"].strip().lower() == query_lower]
        if exact:
            exact.sort(key=lambda t: t.get("popularity", 0), reverse=True)
            return exact[0]
        return max(tracks, key=lambda t: t.get("popularity", 0))
import os

import ollama
import json
import requests

from Engines.pcengine import PCEngine


class ToolEngine:
    def __init__(self, spotify=None, arduino=None, vision=None, ha=None):
        self.spotify = spotify
        self.arduino = arduino
        self.vision = vision
        self.ha = ha
        self.pc = PCEngine(tv_ip="192.168.0.45")

    def web_search(self, query: str):
        try:
            response = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
                timeout=5
            )
            data = response.json()
            answer = data.get("AbstractText") or data.get("Answer")
            if answer:
                return answer
            topics = data.get("RelatedTopics", [])
            if topics and "Text" in topics[0]:
                return topics[0]["Text"]
            return "I couldn't find a clear answer for that."
        except Exception as e:
            return f"Search failed: {e}"

    def handle(self, user_input: str, llm_model: str):
        try:
            response = ollama.chat(
                model=llm_model,
                messages=[{
                    "role": "user",
                    "content": f"""Decide if this user message needs a tool. When in doubt about music, USE the tool.

User said: "{user_input}"

Available tools:
- play_song(query) — play a specific song by title
- play_artist(artist) — play top tracks from an artist. Use this for ANY request mentioning an artist name
- play_playlist(query) — search and play a playlist
- play_genre(genre) — play music by genre
- pause() — pause Spotify
- skip() — skip current track
- previous() — go back a track
- now_playing() — what's currently playing
- set_volume(volume) — change volume 0-100
- web_search(query) — search the web
- set_led_color(r, g, b) — change LED strip color
- set_led_effect(effect) — solid, breathe, pulse, flicker
- set_led_brightness(value) — 0-255
- led_off() — turn off LEDs
- none — only for non-music, non-device conversation
- open_app(app) — open an app: pycharm, vscode, arduino, discord, explorer, lmstudio, spotify
- open_browser(url) — open browser, optionally to a specific URL
- set_pc_volume(level) — set system volume 0-100
- mute() — mute system audio
- unmute() — unmute system audio
- screenshot() — take a screenshot of the current screen
- shutdown() — shutdown the PC
- restart() — restart the PC
- sleep_pc() — put PC to sleep
- lock() — lock the PC
- notify_phone(message) — send a push notification to Lala's phone
- check_phone_battery() — check phone battery level and charging state
- check_phone_location() — check if the phone is home or away
- turn_on_smart_tv() — turn on the TV via Home Assistant (smart TV integration)
- turn_off_smart_tv() — turn off the TV via Home Assistant

Music detection rules:
- ANY mention of an artist name → play_artist
- ANY mention of a song title → play_song
- ANY mention of a genre → play_genre
- "play something", "put on music" → play_genre with args genre="pop"



TV detection rules:
- tv_power() — turn TV on or off
- tv_volume_up() — increase TV volume
- tv_volume_down() — decrease TV volume
- tv_mute() — mute TV

Phone/Home Assistant detection rules:
- "text me", "remind me later", "notify me", "send me a message" → notify_phone with the message text
- "is my phone charging", "battery level", "how much battery" → check_phone_battery
- "where's my phone", "am I home", "is my phone home" → check_phone_location
- "turn on the tv" when referring to the smart TV via Home Assistant rather than the Samsung remote tool → turn_on_smart_tv (prefer tv_power unless user explicitly mentions Home Assistant)

Vision detection rules:
- look() — use the camera to see and identify who is there

Reply ONLY with JSON: {{"tool": "<name>", "args": {{}}}}

Examples:
{{"tool": "play_artist", "args": {{"artist": "Lana Del Rey"}}}}

{{"tool": "notify_phone", "args": {{"message": "Don't forget to drink water"}}}}
{{"tool": "check_phone_battery", "args": {{}}}}
{{"tool": "check_phone_location", "args": {{}}}}"""
                }]
            )

            raw = response['message']['content'].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            tool = data.get("tool", "none")
            args = data.get("args", {})

            if tool == "tool":
                return None

            # ── Built-in melodies ──────────────────────────────────────────────
         
            # ── Home Assistant helpers ───────────────────────────────────────────
            def _notify_phone(message: str):
                if not self.ha:
                    return "Home Assistant is not connected."
                ok = self.ha.notify_phone(message)
                return "Sent to your phone." if ok else "Couldn't reach your phone."

            def _check_phone_battery():
                if not self.ha:
                    return "Home Assistant is not connected."
                level = self.ha.get_phone_battery()
                if level is None:
                    return "Couldn't read phone battery."
                charging = self.ha.is_phone_charging()
                status = "charging" if charging else "not charging"
                return f"Phone is at {level}% and {status}."

            def _check_phone_location():
                if not self.ha:
                    return "Home Assistant is not connected."
                loc = self.ha.get_phone_location()
                if not loc:
                    return "Couldn't read phone location."
                if loc["zone"] == "home":
                    return "Your phone is home."
                elif loc["zone"] == "not_home":
                    return "Your phone is away from home."
                else:
                    return f"Your phone is at {loc['zone']}."

            # dispatch table
            handlers = {
                "look": lambda: self.vision.describe_current_frame(),
                # Spotify
                "play_song": lambda: self.spotify.play_song(args.get("query", "")),
                "play_artist": lambda: self.spotify.play_artist(args.get("artist", "")),
                "play_playlist": lambda: self.spotify.play_playlist(args.get("query", "")),
                "play_genre": lambda: self.spotify.play_genre(args.get("genre", "")),
                "pause": lambda: self.spotify.pause() or "Paused.",
                "skip": lambda: self.spotify.skip() or "Skipped.",
                "previous": lambda: self.spotify.previous() or "Going back.",
                "now_playing": lambda: self.spotify.now_playing(),
                "set_volume": lambda: self.spotify.set_volume(int(args.get("volume", 50))),
                # LEDs
                "set_led_color": lambda: self.arduino.set_color(int(args.get("r", 255)), int(args.get("g", 255)),
                                                                 int(args.get("b", 255))) or "Color set.",
                "set_led_effect": lambda: self.arduino.set_effect(
                    args.get("effect", "solid")) or f"Effect set to {args.get('effect')}.",
                "set_led_brightness": lambda: self.arduino.set_brightness(
                    int(args.get("value", 150))) or f"Brightness set to {args.get('value')}.",
                "led_off": lambda: self.arduino.off() or "LEDs off.",
                # PC
                "open_app": lambda: self.pc.open_app(args.get("app", "")),
                "open_browser": lambda: self.pc.open_browser(args.get("url", "https://google.com")),
                "set_pc_volume": lambda: self.pc.set_volume(int(args.get("level", 50))),
                "mute": lambda: self.pc.mute(),
                "unmute": lambda: self.pc.unmute(),
                "screenshot": lambda: self.pc.screenshot(),
                "shutdown": lambda: self.pc.shutdown(),
                "restart": lambda: self.pc.restart(),
                "sleep_pc": lambda: self.pc.sleep_pc(),
                "lock": lambda: self.pc.lock(),
                # Web
                "web_search": lambda: self.web_search(args.get("query", "")),
                # TV (Samsung remote via PCEngine)
                "tv_power": lambda: self.pc.tv_power(),
                "tv_volume_up": lambda: self.pc.tv_volume_up(),
                "tv_volume_down": lambda: self.pc.tv_volume_down(),
                "tv_mute": lambda: self.pc.tv_mute(),
                # TV (Home Assistant)
                "turn_on_smart_tv": lambda: (
                    "Turned the TV on." if self.ha and self.ha.turn_on_tv() else "Couldn't reach the TV."
                ),
                "turn_off_smart_tv": lambda: (
                    "Turned the TV off." if self.ha and self.ha.turn_off_tv() else "Couldn't reach the TV."
                ),
                # Home Assistant — phone
                "notify_phone": lambda: _notify_phone(args.get("message", "")),
                "check_phone_battery": lambda: _check_phone_battery(),
                "check_phone_location": lambda: _check_phone_location(),
            }

            handler = handlers.get(tool)
            if handler:
                return handler()
            else:
                print(f"[Tools] Unknown tool: {tool}")
                return None

        except Exception as e:
            print(f"[Tools] Failed: {e}")

        return None
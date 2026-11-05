# ══════════════════════════════════════════════════════════════════════════════
# HomeAssistantController — Aria's bridge to your home network
#
# Talks to Home Assistant's REST API to control/read your phone, TV, and
# anything else you add to HA later (lights, plugs, etc).
#
# Setup:
#   1. Set HA_TOKEN env var (the Long-Lived Access Token you just created)
#   2. Set HA_URL below to your PC's local IP (not localhost — Aria might
#      run on a different machine someday, and it's good practice anyway)
#
# Find your entity IDs in HA: Settings → Devices & Services → Entities
# (search "phone" or "tv" to find the exact entity_id strings to use below)
# ══════════════════════════════════════════════════════════════════════════════

import os
import requests

HA_URL = "https://home.lala-home.uk"  # ← replace with your PC's IPv4 from ipconfig
HA_TOKEN = os.environ.get("HA_TOKEN")

# ── Entity IDs — update these once you've found the real ones in HA ───────────
# Settings → Devices & Services → Entities, search "phone" / "tv"
ENTITY_PHONE_NOTIFY = "notify.mobile_app_sm_s928b"  # service, not entity
ENTITY_PHONE_LOCATION = "device_tracker.sm_s928b"
ENTITY_PHONE_BATTERY = "sensor.sm_s928b_battery_level"
ENTITY_PHONE_MEDIA_PLAYER = "media_player.sm_s928b"
ENTITY_TV = "media_player.samsung_tv"  # adjust once TV is added


class HomeAssistantController:
    """
    Aria's interface to Home Assistant.
        ha.notify_phone("Don't forget to drink water")
        ha.get_phone_battery()
        ha.get_phone_location()
        ha.is_phone_home()
        ha.turn_on_tv()
        ha.turn_off_tv()
        ha.set_dnd(True)
        ha.set_bluetooth(False)
        ha.set_flashlight(True)
        ha.set_phone_volume("media", 50)
        ha.launch_app("com.spotify.music")
    """

    def __init__(self):
        if not HA_TOKEN:
            raise RuntimeError("not configured (set HA_TOKEN in Engines/.env to enable)")
        self._headers = {
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        }
        self._ok = self._check_connection()
        if not self._ok:
            raise RuntimeError(f"server not reachable at {HA_URL}")

    def _check_connection(self) -> bool:
        try:
            r = requests.get(f"{HA_URL}/api/", headers=self._headers, timeout=5)
            if r.status_code == 200:
                print("[HomeAssistant] Connected.")
                return True
            else:
                print(f"[HomeAssistant] Connection failed: HTTP {r.status_code}")
                return False
        except requests.RequestException as e:
            print(f"[HomeAssistant] Could not reach HA at {HA_URL}: {e}")
            return False

    def speak_on_phone(self, text: str) -> bool:
        """Play TTS audio through the phone speaker by sending a TTS notification."""
        notify_service = ENTITY_PHONE_NOTIFY.split(".", 1)[1]  # Strips to 'mobile_app_sm_s928b'
        return self.call_service("notify", notify_service, {
            "message": "TTS",  # Tells the Android system this is a voice event
            "data": {
                "tts_text": text,  # This is what your phone will read out loud
                "media_stream": "alarm_stream_max"  # Bypasses silent mode if needed (optional)
            }
        })

    # ── Generic helpers ───────────────────────────────────────────────────────

    def get_state(self, entity_id: str) -> dict | None:
        """Get the full state object for any entity."""
        if not self._ok:
            return None
        try:
            r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=self._headers, timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"[HomeAssistant] get_state({entity_id}) failed: {e}")
            return None

    def call_service(self, domain: str, service: str, data: dict) -> bool:
        """Call any HA service, e.g. call_service('notify', 'mobile_app_phone', {...})"""
        if not self._ok:
            return False
        try:
            r = requests.post(
                f"{HA_URL}/api/services/{domain}/{service}",
                headers=self._headers,
                json=data,
                timeout=10,
            )
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"[HomeAssistant] call_service({domain}.{service}) failed: {e}")
            return False

    def _send_phone_command(self, command: str, command_data: dict = None) -> bool:
        """
        Shared helper for the Companion App's special 'notification command'
        messages (command_dnd, command_bluetooth, etc). These all go through
        the same notify service as notify_phone/speak_on_phone, but with
        `message` set to the command name instead of user-facing text.

        NOTE: The exact keys expected inside `data` differ per command
        (e.g. command_volume_level wants a "stream" key, command_activity
        wants intent/package info). Verify against
        https://companion.home-assistant.io/docs/notifications/notification-commands
        for any command you haven't tested yet — the shapes below are the
        common pattern, not guaranteed exact for every command.
        """
        notify_service = ENTITY_PHONE_NOTIFY.split(".", 1)[1]
        return self.call_service("notify", notify_service, {
            "message": command,
            "data": command_data or {},
        })

    # ── Phone ─────────────────────────────────────────────────────────────────

    def notify_phone(self, message: str, title: str = "Aria"):
        """Send a push notification to your phone via the HA Companion App."""
        notify_service = ENTITY_PHONE_NOTIFY.split(".", 1)[1]  # strip "notify." prefix
        return self.call_service("notify", notify_service, {
            "title": title,
            "message": message,
        })

    def get_phone_battery(self) -> int | None:
        state = self.get_state(ENTITY_PHONE_BATTERY)
        if state:
            try:
                return int(float(state["state"]))
            except (ValueError, KeyError):
                pass
        return None

    def is_phone_charging(self) -> bool | None:
        # Companion app usually also exposes sensor.<phone>_battery_state or is_charging
        state = self.get_state(ENTITY_PHONE_BATTERY.replace("battery_level", "battery_state"))
        if state:
            return state.get("state", "").lower() in ("charging", "full")
        return None

    def get_phone_location(self) -> dict | None:
        """Returns dict with lat/lon/zone state (e.g. 'home', 'not_home', or a named zone)."""
        state = self.get_state(ENTITY_PHONE_LOCATION)
        if not state:
            return None
        attrs = state.get("attributes", {})
        return {
            "zone": state.get("state"),  # "home", "not_home", or zone name
            "latitude": attrs.get("latitude"),
            "longitude": attrs.get("longitude"),
        }

    def is_phone_home(self) -> bool:
        loc = self.get_phone_location()
        return loc is not None and loc["zone"] == "home"

    # ── Phone control commands (Companion App notification commands) ──────────
    # https://companion.home-assistant.io/docs/notifications/notification-commands
    # Note: there is no official call/SMS command — Google Play policy blocks
    # companion apps from placing calls or texting without direct user action.

    def set_dnd(self, on: bool) -> bool:
        """Requires Notification Listener access granted to HA in Android settings."""
        return self._send_phone_command("command_dnd", {"command": "on" if on else "off"})

    def set_bluetooth(self, on: bool) -> bool:
        return self._send_phone_command("command_bluetooth", {"command": "on" if on else "off"})

    def set_flashlight(self, on: bool) -> bool:
        return self._send_phone_command("command_flashlight", {"command": "on" if on else "off"})

    def set_phone_volume(self, stream: str, level: int) -> bool:
        """stream: e.g. 'media', 'ring', 'notification', 'alarm', 'call', 'system'."""
        return self._send_phone_command("command_volume_level", {
            "stream": stream,
            "command": max(0, min(100, level)),
        })

    def launch_app(self, package_name: str) -> bool:
        """package_name: e.g. 'com.spotify.music'. Find via 'adb shell pm list packages'."""
        return self._send_phone_command("command_activity", {
            "intent_package_name": package_name,
        })

    def broadcast_intent(self, action: str, package_name: str = None, extras: dict = None) -> bool:
        """
        Advanced escape hatch — sends an Android broadcast intent. Only useful
        if you (or an app you use, e.g. Tasker's broadcast receiver) is set up
        to listen for it. Most single-purpose control is better served by the
        specific commands above.
        """
        data = {"intent_action": action}
        if package_name:
            data["intent_package_name"] = package_name
        if extras:
            data["intent_extras"] = extras
        return self._send_phone_command("command_broadcast_intent", data)

    # ── TV ────────────────────────────────────────────────────────────────────

    def turn_on_tv(self):
        return self.call_service("media_player", "turn_on", {"entity_id": ENTITY_TV})

    def turn_off_tv(self):
        return self.call_service("media_player", "turn_off", {"entity_id": ENTITY_TV})

    def is_tv_on(self) -> bool | None:
        state = self.get_state(ENTITY_TV)
        if state:
            return state.get("state") == "on"
        return None

    def set_tv_volume(self, level: float):
        """level: 0.0 to 1.0"""
        return self.call_service("media_player", "volume_set", {
            "entity_id": ENTITY_TV,
            "volume_level": max(0.0, min(1.0, level)),
        })


# ══════════════════════════════════════════════════════════════════════════════
# Quick test
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ha = HomeAssistantController()
    ha.speak_on_phone("Hey, it's Aria. Can you hear me?")

    print("\n--- Phone ---")
    print("Battery:", ha.get_phone_battery())
    print("Location:", ha.get_phone_location())
    print("Home?:", ha.is_phone_home())

    print("\n--- TV ---")
    print("TV on?:", ha.is_tv_on())

    # Uncomment to test individual phone commands once entity IDs are confirmed:
    # ha.set_flashlight(True)
    # ha.set_dnd(True)
    # ha.set_phone_volume("media", 50)
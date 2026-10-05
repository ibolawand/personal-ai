import requests


class PhoneController:
    """
    Sends action commands to a Tasker HTTP Server profile running on the
    phone. Add new capabilities by creating a matching Tasker task with
    the same name as `action` — no changes needed here or in ToolEngine's
    dispatch table beyond registering the new action name.

    Requires ONE Tasker profile on the phone:
      Event: HTTP Request Received (any port, e.g. 1821)
      Task:
        1. Parse JSON body (%HTTPBody) -> variables %json_action, %json_arg1, %json_arg2
        2. Perform Task %json_action  (Par 1: %json_arg1, Par 2: %json_arg2)

    Then each capability is its own small Tasker task, named exactly like
    the action strings below (e.g. a task literally named "call_contact").
    """

    def __init__(self, phone_ip: str, port: int = 1821, timeout: float = 5.0):
        self.base_url = f"http://{phone_ip}:{port}"
        self.timeout = timeout

    def _send(self, action: str, args: dict = None) -> bool:
        try:
            resp = requests.post(
                self.base_url,
                json={"action": action, "args": args or {}},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except requests.RequestException as e:
            print(f"[Phone] Failed to reach phone for action '{action}': {e}")
            return False

    # ---------- calls / messaging ----------

    def call_contact(self, name: str) -> str:
        ok = self._send("call_contact", {"name": name})
        return f"Calling {name}." if ok else "Couldn't reach your phone."

    def send_text(self, contact: str, message: str) -> str:
        ok = self._send("send_text", {"contact": contact, "message": message})
        return f"Text sent to {contact}." if ok else "Couldn't reach your phone."

    # ---------- connectivity toggles ----------

    def set_wifi(self, on: bool) -> str:
        ok = self._send("set_wifi", {"on": on})
        return f"WiFi turned {'on' if on else 'off'}." if ok else "Couldn't reach your phone."

    def set_bluetooth(self, on: bool) -> str:
        ok = self._send("set_bluetooth", {"on": on})
        return f"Bluetooth turned {'on' if on else 'off'}." if ok else "Couldn't reach your phone."

    def set_dnd(self, on: bool) -> str:
        ok = self._send("set_dnd", {"on": on})
        return f"Do Not Disturb turned {'on' if on else 'off'}." if ok else "Couldn't reach your phone."

    def set_flashlight(self, on: bool) -> str:
        ok = self._send("set_flashlight", {"on": on})
        return f"Flashlight turned {'on' if on else 'off'}." if ok else "Couldn't reach your phone."

    # ---------- media / volume ----------

    def set_ringer_volume(self, level: int) -> str:
        ok = self._send("set_ringer_volume", {"level": max(0, min(100, level))})
        return f"Phone volume set to {level}%." if ok else "Couldn't reach your phone."

    def media_play_pause(self) -> str:
        ok = self._send("media_play_pause")
        return "Toggled media playback." if ok else "Couldn't reach your phone."

    def media_next(self) -> str:
        ok = self._send("media_next")
        return "Skipped track." if ok else "Couldn't reach your phone."

    # ---------- apps / misc ----------

    def open_app(self, app_name: str) -> str:
        ok = self._send("open_app", {"app": app_name})
        return f"Opening {app_name}." if ok else "Couldn't reach your phone."

    def set_alarm(self, time_str: str, label: str = "") -> str:
        ok = self._send("set_alarm", {"time": time_str, "label": label})
        return f"Alarm set for {time_str}." if ok else "Couldn't reach your phone."

    def take_photo(self) -> str:
        ok = self._send("take_photo")
        return "Took a photo." if ok else "Couldn't reach your phone."
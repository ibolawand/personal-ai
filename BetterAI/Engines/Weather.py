"""
Weather from Open-Meteo (free, official API, no key needed).

"What's the weather?", "do I need a jacket tomorrow?", "weather in Berlin", "my city is Vienna".
The home city is set by voice (or ARIA_LOCATION in Engines/.env) and kept in ~/.cache/aria/weather.json.
The morning briefing gets one line about today's weather when a home city is known.
"""

import json
import os

import requests

STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "weather.json")
TIMEOUT = 6

# WMO weather codes -> words
CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
         51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
         61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
         71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
         80: "rain showers", 81: "rain showers", 82: "heavy rain showers", 85: "snow showers", 86: "heavy snow showers",
         95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def advice(t_max, rain_prob, code=None) -> str:
    """What to wear, decided in code (the model called 3–9 degrees 'mild, no jacket needed')."""
    tips = []
    if t_max < 5:
        tips.append("a warm coat")
    elif t_max < 15:
        tips.append("a jacket")
    elif t_max < 20:
        tips.append("a light jacket or hoodie")
    if rain_prob >= 50 or (code is not None and int(code) in range(51, 83)):
        tips.append("an umbrella")
    if code is not None and int(code) in (71, 73, 75, 77, 85, 86):
        tips.append("warm shoes")
    return ("Advice: " + " and ".join(tips) + ".") if tips else "Advice: no jacket needed."


def describe(code) -> str:
    return CODES.get(int(code), "mixed weather") if code is not None else "unknown weather"


class Weather:
    def __init__(self):
        self.state = self._load()
        env = os.environ.get("ARIA_LOCATION", "").strip()
        if env and not self.state.get("home"):
            self.state["home_name"] = env

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f)
        except OSError:
            pass

    # ── places ──

    @staticmethod
    def geocode(city: str):
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": city, "count": 1, "language": "en"}, timeout=TIMEOUT).json()
        hits = r.get("results") or []
        if not hits:
            return None
        h = hits[0]
        return {"name": h["name"], "country": h.get("country", ""), "lat": h["latitude"], "lon": h["longitude"]}

    def _home(self):
        if self.state.get("home"):
            return self.state["home"]
        name = self.state.get("home_name")
        if name:
            place = self.geocode(name)
            if place:
                self.state["home"] = place
                self._save()
                return place
        return None

    def set_home_city(self, city: str):
        try:
            place = self.geocode(city)
        except requests.RequestException:
            return "I couldn't reach the weather service to look that city up."
        if not place:
            return f"I couldn't find a place called '{city}'."
        self.state["home"] = place
        self._save()
        return f"Got it, your city is {place['name']}, {place['country']}."

    # ── forecast ──

    def _forecast(self, place):
        return requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["lat"], "longitude": place["lon"], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        }, timeout=TIMEOUT).json()

    def get_weather(self, when: str = "now", city: str = ""):
        try:
            place = self.geocode(city) if city else self._home()
        except requests.RequestException:
            return "I couldn't reach the weather service."
        if not place:
            return ("I don't know where you are yet. Tell me your city (set_home_city)." if not city
                    else f"I couldn't find a place called '{city}'.")
        try:
            data = self._forecast(place)
        except requests.RequestException:
            return "I couldn't reach the weather service."
        w = (when or "now").lower()
        day = 1 if "tomorrow" in w else 2 if "day after" in w else 0
        d = data["daily"]
        rain = d["precipitation_probability_max"][day]
        line = (f"{describe(d['weather_code'][day])}, {round(d['temperature_2m_min'][day])} to "
                f"{round(d['temperature_2m_max'][day])} degrees, {rain}% chance of rain")
        where = place["name"]
        tip = advice(d["temperature_2m_max"][day], rain, d["weather_code"][day])
        if day == 0 and ("now" in w or w in ("", "today", "current")):
            c = data["current"]
            now = (f"Right now in {where}: {describe(c['weather_code'])}, {round(c['temperature_2m'])} degrees "
                   f"(feels like {round(c['apparent_temperature'])}), wind {round(c['wind_speed_10m'])} km/h.")
            return now + f" Today: {line}. {tip}"
        label = {0: "Today", 1: "Tomorrow", 2: "The day after tomorrow"}[day]
        return f"{label} in {where}: {line}. {tip}"

    def brief(self) -> str:
        """One line for the morning briefing, or '' (no city / offline)."""
        try:
            place = self._home()
            if not place:
                return ""
            d = self._forecast(place)["daily"]
        except Exception:
            return ""
        return (f"Weather today: {describe(d['weather_code'][0])}, {round(d['temperature_2m_min'][0])} to "
                f"{round(d['temperature_2m_max'][0])} degrees, {d['precipitation_probability_max'][0]}% chance of rain.")

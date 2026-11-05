import pytest

import Engines.Weather as W


class FakeResp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


GEO = {"results": [{"name": "Vienna", "country": "Austria", "latitude": 48.2, "longitude": 16.4}]}
FORECAST = {"current": {"temperature_2m": 2.9, "apparent_temperature": 0.5, "weather_code": 0, "wind_speed_10m": 3.2},
            "daily": {"weather_code": [3, 61, 0], "temperature_2m_max": [9.6, 8.7, 11],
                      "temperature_2m_min": [1.2, 3.4, 2], "precipitation_probability_max": [5, 80, 0]}}


@pytest.fixture
def weather(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "STATE_FILE", str(tmp_path / "weather.json"))
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return FakeResp(GEO if "geocoding" in url else FORECAST)
    monkeypatch.setattr(W.requests, "get", fake_get)
    w = W.Weather()
    w.calls = calls
    return w


def test_needs_a_city_first(weather):
    assert "don't know where you are" in weather.get_weather()
    assert weather.brief() == ""


def test_now_and_tomorrow(weather):
    assert weather.set_home_city("vienna") == "Got it, your city is Vienna, Austria."
    now = weather.get_weather("now")
    assert now.startswith("Right now in Vienna: clear, 3 degrees (feels like 0)")
    assert "Today: cloudy, 1 to 10 degrees, 5% chance of rain" in now
    assert weather.get_weather("tomorrow") == ("Tomorrow in Vienna: light rain, 3 to 9 degrees, 80% chance of rain. "
                                               "Advice: a jacket and an umbrella.")


@pytest.mark.parametrize("t_max,rain,code,expected", [
    (3, 0, 0, "Advice: a warm coat."), (9, 10, 3, "Advice: a jacket."), (24, 0, 0, "Advice: no jacket needed."),
    (22, 70, 61, "Advice: an umbrella."), (-2, 30, 73, "Advice: a warm coat and an umbrella and warm shoes."),
])
def test_advice(t_max, rain, code, expected):
    assert W.advice(t_max, rain, code) == expected


def test_home_city_is_remembered(weather):
    weather.set_home_city("vienna")
    again = W.Weather()
    assert again._home()["name"] == "Vienna"
    assert again.brief().startswith("Weather today: cloudy")


def test_offline_is_handled(weather, monkeypatch):
    weather.set_home_city("vienna")

    def boom(*a, **k):
        raise W.requests.ConnectionError("offline")
    monkeypatch.setattr(W.requests, "get", boom)
    assert weather.get_weather() == "I couldn't reach the weather service."
    assert weather.brief() == ""

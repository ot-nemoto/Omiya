"""Open-Meteo から天気を取得し、表示用の値に整形する共通モジュール（標準ライブラリのみ）。"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

# ---- 地点設定（環境変数で上書き可能） --------------------------------------
LOCATION_NAME = os.environ.get("LOCATION_NAME", "大宮")
LATITUDE = float(os.environ.get("LATITUDE", "35.906"))    # 大宮駅付近
LONGITUDE = float(os.environ.get("LONGITUDE", "139.624"))
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Tokyo")

API_URL = "https://api.open-meteo.com/v1/forecast"

# ---- WMO weather_code -> 絵文字 -------------------------------------------
# https://open-meteo.com/en/docs の WMO Weather interpretation codes 参照
WEATHER_EMOJI: dict[int, str] = {
    0: "☀️",   # 快晴
    1: "🌤️",  # ほぼ晴れ
    2: "⛅",   # 晴れ時々曇り
    3: "☁️",   # 曇り
    45: "🌫️", 48: "🌫️",                       # 霧・霧氷
    51: "🌦️", 53: "🌦️", 55: "🌦️",            # 霧雨
    56: "🌧️", 57: "🌧️",                       # 着氷性の霧雨
    61: "🌧️", 63: "🌧️", 65: "☔",              # 雨（弱・並・強）
    66: "🌧️", 67: "☔",                        # 着氷性の雨
    71: "🌨️", 73: "🌨️", 75: "❄️", 77: "❄️",  # 雪・雪あられ
    80: "🌦️", 81: "🌧️", 82: "☔",              # にわか雨
    85: "🌨️", 86: "❄️",                       # にわか雪
    95: "⛈️", 96: "⛈️", 99: "⛈️",             # 雷雨（ひょうを伴う場合あり）
}

WEATHER_TEXT: dict[int, str] = {
    0: "快晴", 1: "晴れ", 2: "晴れ時々曇り", 3: "曇り", 45: "霧", 48: "霧氷",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨", 56: "着氷性の霧雨", 57: "着氷性の霧雨",
    61: "小雨", 63: "雨", 65: "大雨", 66: "着氷性の雨", 67: "着氷性の大雨",
    71: "小雪", 73: "雪", 75: "大雪", 77: "雪あられ",
    80: "にわか雨", 81: "強いにわか雨", 82: "激しいにわか雨", 85: "にわか雪", 86: "強いにわか雪",
    95: "雷雨", 96: "雷雨（ひょう）", 99: "激しい雷雨（ひょう）",
}

WEEKDAYS = "月火水木金土日"
WIND_DIRS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]


def emoji(code: int | None) -> str:
    return WEATHER_EMOJI.get(code, "❓") if code is not None else "❓"


def text(code: int | None) -> str:
    return WEATHER_TEXT.get(code, "不明") if code is not None else "不明"


def wind_dir_name(deg: float | None) -> str:
    """風向（風が吹いてくる方角, 度）を 8 方位の日本語にする。"""
    if deg is None:
        return ""
    return WIND_DIRS[int((deg % 360 + 22.5) // 45) % 8]


# ---- データ取得 -------------------------------------------------------------
@dataclass
class Day:
    date: date
    code: int | None
    tmax: float | None
    tmin: float | None
    pop: int | None          # 降水確率(%)
    uv: float | None
    sunrise: str | None      # "HH:MM"
    sunset: str | None

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.date.weekday()]


@dataclass
class Weather:
    today: date
    temp: float | None
    feels: float | None
    wind_ms: float | None
    wind_deg: float | None
    code: int | None
    days: list[Day]


def _get(daily: dict, key: str, i: int):
    values = daily.get(key) or []
    return values[i] if i < len(values) else None


def parse(data: dict) -> Weather:
    cur = data.get("current") or {}
    daily = data["daily"]
    days = []
    for i, d in enumerate(daily["time"]):
        pop = _get(daily, "precipitation_probability_max", i)
        sr, ss = _get(daily, "sunrise", i), _get(daily, "sunset", i)
        days.append(Day(
            date=date.fromisoformat(d),
            code=_get(daily, "weather_code", i),
            tmax=_get(daily, "temperature_2m_max", i),
            tmin=_get(daily, "temperature_2m_min", i),
            pop=None if pop is None else int(pop),
            uv=_get(daily, "uv_index_max", i),
            sunrise=sr[-5:] if sr else None,
            sunset=ss[-5:] if ss else None,
        ))
    # current.time は「現地時間」。日付が取れなければ daily の先頭を今日とする
    today = date.fromisoformat(cur["time"][:10]) if cur.get("time") else days[0].date
    return Weather(
        today=today,
        temp=cur.get("temperature_2m"),
        feels=cur.get("apparent_temperature"),
        wind_ms=cur.get("wind_speed_10m"),
        wind_deg=cur.get("wind_direction_10m"),
        code=cur.get("weather_code", days[0].code),
        days=days,
    )


def fetch(retries: int = 3) -> Weather:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "timezone": TIMEZONE,
        "forecast_days": 7,
        "wind_speed_unit": "ms",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m",
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_probability_max", "uv_index_max", "sunrise", "sunset",
        ]),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as res:
                return parse(json.load(res))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Open-Meteo の取得に失敗しました: {last}")


def rnd(v: float | None) -> str:
    """四捨五入して整数表記（-0 を避ける）。"""
    if v is None:
        return "–"
    r = round(v)
    return str(0 if r == 0 else r)

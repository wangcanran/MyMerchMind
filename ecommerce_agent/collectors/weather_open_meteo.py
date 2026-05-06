"""季节/天气：Open-Meteo 公开 API（无需 Key，合规）。也可选用 OpenWeather（需 ECOMMERCE_OPENWEATHER_API_KEY）。"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .paths import collected_dir, write_json

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPENWEATHER_CURRENT = "https://api.openweathermap.org/data/2.5/weather"


def fetch_open_meteo_archive(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    *,
    timeout_sec: float = 30.0,
) -> Dict[str, Any]:
    """拉取历史日级气温与降水（用于季节性复盘与规划）。"""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "Asia/Shanghai",
    }
    url = f"{OPEN_METEO_ARCHIVE}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "ECommerceAgent/1.0"})
    with urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_open_meteo_forecast(
    latitude: float,
    longitude: float,
    days: int = 7,
    *,
    timeout_sec: float = 30.0,
) -> Dict[str, Any]:
    """未来数日预报（免费）。"""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "forecast_days": min(max(days, 1), 16),
        "timezone": "Asia/Shanghai",
    }
    url = f"{OPEN_METEO_FORECAST}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "ECommerceAgent/1.0"})
    with urlopen(req, timeout=timeout_sec) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_weather_bundle(
    latitude: float,
    longitude: float,
    *,
    history_days: int = 365,
    city_label: str = "",
    out_path: Optional[Path] = None,
) -> Path:
    """采集：过去 N 天归档 + 短期预报，写入 collected/weather_bundle.json。"""
    end = date.today()
    start = end - timedelta(days=max(1, history_days) - 1)
    out = out_path or (collected_dir() / "weather_bundle.json")

    bundle: Dict[str, Any] = {
        "source": "open-meteo",
        "city_label": city_label,
        "latitude": latitude,
        "longitude": longitude,
        "history_range": {"start": start.isoformat(), "end": end.isoformat()},
        "archive": None,
        "forecast": None,
        "openweather_current": None,
    }
    try:
        bundle["archive"] = fetch_open_meteo_archive(latitude, longitude, start, end)
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        bundle["archive_error"] = str(e)
    try:
        bundle["forecast"] = fetch_open_meteo_forecast(latitude, longitude, days=7)
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        bundle["forecast_error"] = str(e)

    import os

    ow_key = os.environ.get("ECOMMERCE_OPENWEATHER_API_KEY", "").strip()
    if ow_key:
        try:
            params = {"lat": latitude, "lon": longitude, "appid": ow_key, "units": "metric", "lang": "zh_cn"}
            url = f"{OPENWEATHER_CURRENT}?{urlencode(params)}"
            req = Request(url, headers={"User-Agent": "ECommerceAgent/1.0"})
            with urlopen(req, timeout=30.0) as resp:
                bundle["openweather_current"] = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            bundle["openweather_error"] = str(e)

    write_json(out, bundle)
    return out


def summarize_season_signals(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """从归档日序列提取简单季节信号（均温、降水累计），供后续 Agent 使用。"""
    arch = bundle.get("archive") or {}
    daily = arch.get("daily") or {}
    times: List[str] = list(daily.get("time") or [])
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    prec = daily.get("precipitation_sum") or []
    if not times or not tmax:
        return {"note": "无有效归档数据", "days": 0}
    temps_mid = [(float(a) + float(b)) / 2 for a, b in zip(tmax, tmin) if a is not None and b is not None]
    precip_total = sum(float(x or 0) for x in prec)
    return {
        "days": len(times),
        "mean_temp_c": round(sum(temps_mid) / len(temps_mid), 2) if temps_mid else None,
        "precipitation_sum_mm": round(precip_total, 2),
        "last_date": times[-1] if times else None,
    }

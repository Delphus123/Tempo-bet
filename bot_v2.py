#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_v2.py — Weather Trading Bot for Polymarket
=====================================================
Tracks weather forecasts from 3 sources (ECMWF, HRRR, METAR),
compares with Polymarket markets, paper trades using Kelly criterion.

Usage:
    python bot_v2.py          # main loop
    python bot_v2.py report   # full report
    python bot_v2.py status   # balance and open positions
"""

import re
import sys
import json
import math
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Telegram Alerts
try:
    from telegram_alerts import (
        alert_new_trade, alert_trade_closed, alert_trade_resolved,
        alert_pnl_update, alert_error, alert_bot_started, alert_daily_report
    )
    TELEGRAM_ENABLED = True
except Exception as e:
    print(f"[ALERTS] Telegram not available: {e}")
    TELEGRAM_ENABLED = False

# =============================================================================
# CONFIG
# =============================================================================

with open("config.json", encoding="utf-8") as f:
    _cfg = json.load(f)

BALANCE          = _cfg.get("balance", 10000.0)
MAX_BET          = _cfg.get("max_bet", 20.0)        # max bet per trade
MIN_EV           = _cfg.get("min_ev", 0.10)
MAX_PRICE        = _cfg.get("max_price", 0.45)
MIN_VOLUME       = _cfg.get("min_volume", 500)
MIN_HOURS        = _cfg.get("min_hours", 2.0)
MAX_HOURS        = _cfg.get("max_hours", 72.0)
KELLY_FRACTION   = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE     = _cfg.get("max_slippage", 0.03)  # max allowed ask-bid spread
SCAN_INTERVAL    = _cfg.get("scan_interval", 3600)   # every hour
CALIBRATION_MIN  = _cfg.get("calibration_min", 30)
VC_KEY           = _cfg.get("vc_key", "")

SIGMA_F = 2.0
SIGMA_C = 1.2

# Auto-Redemption Config (Option B)
AUTO_REDEMPTION = {
    "enabled": True,
    "price_high": 0.99,        # Sell 100% if price > $0.99
    "price_mid": 0.95,         # Sell 50% if price > $0.95 AND P&L > 50%
    "pnl_threshold": 1.0,      # P&L > 100% triggers mid-level sell
    "pnl_extreme": 5.0,        # P&L > 500% triggers 75% sell
    "stop_loss": -0.20,        # Stop loss at -20%
    "min_hold_hours": 6,       # Don't sell if < 6h old
}

DATA_DIR         = Path("data")
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE       = DATA_DIR / "state.json"
MARKETS_DIR      = DATA_DIR / "markets"
MARKETS_DIR.mkdir(exist_ok=True)
CALIBRATION_FILE = DATA_DIR / "calibration.json"

LOCATIONS = {
    "nyc":          {"lat": 40.7772,  "lon":  -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago":      {"lat": 41.9742,  "lon":  -87.9073, "name": "Chicago",       "station": "KORD", "unit": "F", "region": "us"},
    "miami":        {"lat": 25.7959,  "lon":  -80.2870, "name": "Miami",         "station": "KMIA", "unit": "F", "region": "us"},
    "dallas":       {"lat": 32.8471,  "lon":  -96.8518, "name": "Dallas",        "station": "KDAL", "unit": "F", "region": "us"},
    "seattle":      {"lat": 47.4502,  "lon": -122.3088, "name": "Seattle",       "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta":      {"lat": 33.6407,  "lon":  -84.4277, "name": "Atlanta",       "station": "KATL", "unit": "F", "region": "us"},
    "london":       {"lat": 51.5048,  "lon":    0.0495, "name": "London",        "station": "EGLC", "unit": "C", "region": "eu"},
    "paris":        {"lat": 48.9962,  "lon":    2.5979, "name": "Paris",         "station": "LFPG", "unit": "C", "region": "eu"},
    "munich":       {"lat": 48.3537,  "lon":   11.7750, "name": "Munich",        "station": "EDDM", "unit": "C", "region": "eu"},
    "ankara":       {"lat": 40.1281,  "lon":   32.9951, "name": "Ankara",        "station": "LTAC", "unit": "C", "region": "eu"},
    "seoul":        {"lat": 37.4691,  "lon":  126.4505, "name": "Seoul",         "station": "RKSI", "unit": "C", "region": "asia"},
    "tokyo":        {"lat": 35.7647,  "lon":  140.3864, "name": "Tokyo",         "station": "RJTT", "unit": "C", "region": "asia"},
    "shanghai":     {"lat": 31.1443,  "lon":  121.8083, "name": "Shanghai",      "station": "ZSPD", "unit": "C", "region": "asia"},
    "singapore":    {"lat":  1.3502,  "lon":  103.9940, "name": "Singapore",     "station": "WSSS", "unit": "C", "region": "asia"},
    "lucknow":      {"lat": 26.7606,  "lon":   80.8893, "name": "Lucknow",       "station": "VILK", "unit": "C", "region": "asia"},
    "tel-aviv":     {"lat": 32.0114,  "lon":   34.8867, "name": "Tel Aviv",      "station": "LLBG", "unit": "C", "region": "asia"},
    "toronto":      {"lat": 43.6772,  "lon":  -79.6306, "name": "Toronto",       "station": "CYYZ", "unit": "C", "region": "ca"},
    "sao-paulo":    {"lat": -23.4356, "lon":  -46.4731, "name": "Sao Paulo",     "station": "SBGR", "unit": "C", "region": "sa"},
    "buenos-aires": {"lat": -34.8222, "lon":  -58.5358, "name": "Buenos Aires",  "station": "SAEZ", "unit": "C", "region": "sa"},
    "wellington":   {"lat": -41.3272, "lon":  174.8052, "name": "Wellington",    "station": "NZWN", "unit": "C", "region": "oc"},
}

TIMEZONES = {
    "nyc": "America/New_York", "chicago": "America/Chicago",
    "miami": "America/New_York", "dallas": "America/Chicago",
    "seattle": "America/Los_Angeles", "atlanta": "America/New_York",
    "london": "Europe/London", "paris": "Europe/Paris",
    "munich": "Europe/Berlin", "ankara": "Europe/Istanbul",
    "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai", "singapore": "Asia/Singapore",
    "lucknow": "Asia/Kolkata", "tel-aviv": "Asia/Jerusalem",
    "toronto": "America/Toronto", "sao-paulo": "America/Sao_Paulo",
    "buenos-aires": "America/Argentina/Buenos_Aires", "wellington": "Pacific/Auckland",
}

MONTHS = ["january","february","march","april","may","june",
          "july","august","september","october","november","december"]

# =============================================================================
# MATH
# =============================================================================

def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast, t_low, t_high, sigma=None):
    """For regular buckets — exact match. For edge buckets — normal distribution."""
    s = sigma or 2.0
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / s)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / s)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0

def calc_ev(p, price):
    if price <= 0 or price >= 1: return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)

def calc_kelly(p, price):
    if price <= 0 or price >= 1: return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(0.0, f) * KELLY_FRACTION, 1.0), 4)

def bet_size(kelly, balance):
    raw = kelly * balance
    return round(min(raw, MAX_BET), 2)

# =============================================================================
# CALIBRATION
# =============================================================================

_cal: dict = {}

def load_cal():
    if CALIBRATION_FILE.exists():
        return json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    return {}

def get_sigma(city_slug, source="ecmwf"):
    key = f"{city_slug}_{source}"
    if key in _cal:
        return _cal[key]["sigma"]
    return SIGMA_F if LOCATIONS[city_slug]["unit"] == "F" else SIGMA_C

def get_brier_score(city_slug, source="ecmwf"):
    """Get Brier Score for a source. Returns 0.25 if no data (default uncertain)."""
    key = f"{city_slug}_{source}"
    if key in _cal and "brier_score" in _cal[key]:
        return _cal[key]["brier_score"]
    return 0.25  # Default uncertain prediction

def run_calibration(markets):
    """
    Recalculates sigma and Brier Score from resolved markets.
    Brier Score = mean((predicted_prob - actual)²)
    Lower is better (0 = perfect, 1 = worst)
    """
    resolved = [m for m in markets if m.get("resolved") and m.get("actual_temp") is not None]
    cal = load_cal()
    updated = []

    for source in ["ecmwf", "hrrr", "metar"]:
        for city in set(m["city"] for m in resolved):
            group = [m for m in resolved if m["city"] == city]
            errors = []
            brier_scores = []
            
            for m in group:
                # Find forecast snapshot for this source
                snap = None
                for s in reversed(m.get("forecast_snapshots", [])):
                    if s.get("best_source") == source or source in s.get("best_source", ""):
                        snap = s
                        break
                
                if not snap or snap.get("best") is None:
                    continue
                    
                forecast_temp = snap["best"]
                actual_temp = m["actual_temp"]
                
                # Calculate temperature error
                errors.append(abs(forecast_temp - actual_temp))
                
                # Calculate Brier Score for this prediction
                # We predicted a bucket - check if actual temp was in bucket
                if m.get("position"):
                    predicted_prob = m["position"].get("p", 0.5)  # Our assigned probability
                    # Actual outcome: 1 if we won, 0 if we lost
                    actual_outcome = 1 if m["resolved_outcome"] == "win" else 0
                    brier = (predicted_prob - actual_outcome) ** 2
                    brier_scores.append(brier)
            
            if len(errors) < CALIBRATION_MIN:
                continue
                
            mae = sum(errors) / len(errors)
            brier_score = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5
            
            key = f"{city}_{source}"
            old = cal.get(key, {}).get("sigma", SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C)
            new = round(mae, 3)
            old_brier = cal.get(key, {}).get("brier_score", 0.25)
            new_brier = round(brier_score, 4)
            
            cal[key] = {
                "sigma": new, 
                "n": len(errors), 
                "brier_score": new_brier,
                "brier_n": len(brier_scores),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if abs(new - old) > 0.05:
                updated.append(f"{LOCATIONS[city]['name']} {source}: σ {old:.2f}->{new:.2f}")
            if abs(new_brier - old_brier) > 0.02:
                updated.append(f"{LOCATIONS[city]['name']} {source}: Brier {old_brier:.3f}->{new_brier:.3f}")

    CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    if updated:
        print(f"  [CAL] {', '.join(updated)}")
    return cal

# =============================================================================
# FORECASTS
# =============================================================================

def get_ecmwf(city_slug, dates):
    """ECMWF via Open-Meteo with bias correction. For all cities."""
    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    result = {}
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={loc['lat']}&longitude={loc['lon']}"
            f"&daily=temperature_2m_max&temperature_unit={temp_unit}"
            f"&forecast_days=7&timezone={TIMEZONES.get(city_slug, 'UTC')}"
            f"&models=ecmwf_ifs025&bias_correction=true"
        )
        data = requests.get(url, timeout=(5, 8)).json()
        if "error" not in data:
            for date, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                if date in dates and temp is not None:
                    result[date] = round(temp, 1) if unit == "C" else round(temp)
    except Exception as e:
        print(f"  [ECMWF] {city_slug}: {e}")
    return result

def get_hrrr(city_slug, dates):
    """HRRR via Open-Meteo. US cities only, up to 48h horizon."""
    loc = LOCATIONS[city_slug]
    if loc["region"] != "us":
        return {}
    result = {}
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={loc['lat']}&longitude={loc['lon']}"
            f"&daily=temperature_2m_max&temperature_unit=fahrenheit"
            f"&forecast_days=3&timezone={TIMEZONES.get(city_slug, 'UTC')}"
            f"&models=gfs_seamless"  # HRRR+GFS seamless — best option for US
        )
        data = requests.get(url, timeout=(5, 8)).json()
        if "error" not in data:
            for date, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                if date in dates and temp is not None:
                    result[date] = round(temp)
    except Exception as e:
        print(f"  [HRRR] {city_slug}: {e}")
    return result

def get_model_ensemble(city_slug, dates):
    """
    Multi-model ensemble: uses ECMWF + HRRR + GFS to estimate confidence.
    Returns: {date: {"mean": float, "confidence": float, "members": int}}
    confidence = agreement between models (0-1, higher = more confident)
    """
    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    result = {}
    
    try:
        # Get forecasts from multiple models
        models = ["ecmwf_ifs025", "gfs_seamless"]
        all_temps = {date: [] for date in dates}
        
        for model in models:
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={loc['lat']}&longitude={loc['lon']}"
                f"&daily=temperature_2m_max"
                f"&temperature_unit={temp_unit}"
                f"&forecast_days=7"
                f"&timezone={TIMEZONES.get(city_slug, 'UTC')}"
                f"&models={model}&bias_correction=true"
            )
            data = requests.get(url, timeout=(5, 8)).json()
            
            if "error" not in data and "daily" in data:
                for date in dates:
                    if date in data["daily"]["time"]:
                        idx = data["daily"]["time"].index(date)
                        temp = data["daily"]["temperature_2m_max"][idx]
                        if temp is not None:
                            all_temps[date].append(float(temp))
        
        # Calculate mean and confidence from model agreement
        for date, temps in all_temps.items():
            if temps:
                mean_temp = sum(temps) / len(temps)
                
                # Confidence based on model agreement
                if len(temps) > 1:
                    variance = sum((t - mean_temp) ** 2 for t in temps) / len(temps)
                    std_dev = variance ** 0.5
                    # High confidence if models agree (std < 2°C)
                    confidence = max(0, min(1, 1 - (std_dev / 3.0)))
                else:
                    confidence = 0.5  # Only one model
                
                result[date] = {
                    "mean": round(mean_temp, 1) if unit == "C" else round(mean_temp),
                    "confidence": round(confidence, 2),
                    "members": len(temps)
                }
    except Exception as e:
        print(f"  [MODEL_ENSEMBLE] {city_slug}: {e}")
    
    return result

def get_metar(city_slug):
    """Current observed temperature from METAR station. D+0 only."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={station}&format=json"
        data = requests.get(url, timeout=(5, 8)).json()
        if data and isinstance(data, list):
            temp_c = data[0].get("temp")
            if temp_c is not None:
                if unit == "F":
                    return round(float(temp_c) * 9/5 + 32)
                return round(float(temp_c), 1)
    except Exception as e:
        print(f"  [METAR] {city_slug}: {e}")
    return None

def get_actual_temp(city_slug, date_str):
    """Actual temperature via Visual Crossing for closed markets."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    vc_unit = "us" if unit == "F" else "metric"
    url = (
        f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
        f"/{station}/{date_str}/{date_str}"
        f"?unitGroup={vc_unit}&key={VC_KEY}&include=days&elements=tempmax"
    )
    try:
        data = requests.get(url, timeout=(5, 8)).json()
        days = data.get("days", [])
        if days and days[0].get("tempmax") is not None:
            return round(float(days[0]["tempmax"]), 1)
    except Exception as e:
        print(f"  [VC] {city_slug} {date_str}: {e}")
    return None

def check_market_resolved(market_id):
    """
    Checks if the market closed on Polymarket and who won.
    Returns: None (still open), True (YES won), False (NO won)
    """
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(5, 8))
        data = r.json()
        closed = data.get("closed", False)
        if not closed:
            return None
        # Check YES price — if ~1.0 then WIN, if ~0.0 then LOSS
        prices = json.loads(data.get("outcomePrices", "[0.5,0.5]"))
        yes_price = float(prices[0])
        if yes_price >= 0.95:
            return True   # WIN
        elif yes_price <= 0.05:
            return False  # LOSS
        return None  # not yet determined
    except Exception as e:
        print(f"  [RESOLVE] {market_id}: {e}")
    return None

# =============================================================================
# POLYMARKET
# =============================================================================

def get_polymarket_event(city_slug, month, day, year):
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}", timeout=(5, 8))
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
    except Exception:
        pass
    return None

def get_market_price(market_id):
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(3, 5))
        prices = json.loads(r.json().get("outcomePrices", "[0.5,0.5]"))
        return float(prices[0])
    except Exception:
        return None

def parse_temp_range(question):
    if not question: return None
    num = r'(-?\d+(?:\.\d+)?)'
    if re.search(r'or below', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or below', question, re.IGNORECASE)
        if m: return (-999.0, float(m.group(1)))
    if re.search(r'or higher', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or higher', question, re.IGNORECASE)
        if m: return (float(m.group(1)), 999.0)
    m = re.search(r'between ' + num + r'-' + num + r'[°]?[FC]', question, re.IGNORECASE)
    if m: return (float(m.group(1)), float(m.group(2)))
    m = re.search(r'be ' + num + r'[°]?[FC] on', question, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return (v, v)
    return None

def hours_to_resolution(end_date_str):
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return 999.0

def in_bucket(forecast, t_low, t_high):
    if t_low == t_high:
        return round(float(forecast)) == round(t_low)
    return t_low <= float(forecast) <= t_high

# =============================================================================
# MARKET DATA STORAGE
# Each market is stored in a separate file: data/markets/{city}_{date}.json
# =============================================================================

def market_path(city_slug, date_str):
    return MARKETS_DIR / f"{city_slug}_{date_str}.json"

def load_market(city_slug, date_str):
    p = market_path(city_slug, date_str)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None

def save_market(market):
    p = market_path(market["city"], market["date"])
    p.write_text(json.dumps(market, indent=2, ensure_ascii=False), encoding="utf-8")

def load_all_markets():
    markets = []
    for f in MARKETS_DIR.glob("*.json"):
        try:
            markets.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return markets

def new_market(city_slug, date_str, event, hours):
    loc = LOCATIONS[city_slug]
    return {
        "city":               city_slug,
        "city_name":          loc["name"],
        "date":               date_str,
        "unit":               loc["unit"],
        "station":            loc["station"],
        "event_end_date":     event.get("endDate", ""),
        "hours_at_discovery": round(hours, 1),
        "status":             "open",           # open | closed | resolved
        "position":           None,             # filled when position opens
        "actual_temp":        None,             # filled after resolution
        "resolved_outcome":   None,             # win / loss / no_position
        "pnl":                None,
        "forecast_snapshots": [],               # list of forecast snapshots
        "market_snapshots":   [],               # list of market price snapshots
        "all_outcomes":       [],               # all market buckets
        "created_at":         datetime.now(timezone.utc).isoformat(),
    }

# =============================================================================
# STATE (balance and open positions)
# =============================================================================

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "balance":          BALANCE,
        "starting_balance": BALANCE,
        "total_trades":     0,
        "wins":             0,
        "losses":           0,
        "peak_balance":     BALANCE,
    }

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# =============================================================================
# CORE LOGIC
# =============================================================================

def take_forecast_snapshot(city_slug, dates):
    """Fetches forecasts from all sources and returns a snapshot."""
    now_str = datetime.now(timezone.utc).isoformat()
    ecmwf   = get_ecmwf(city_slug, dates)
    hrrr    = get_hrrr(city_slug, dates)
    gfs_ens = get_model_ensemble(city_slug, dates)
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snapshots = {}
    for date in dates:
        # Get GFS ensemble data for this date
        gfs_data = gfs_ens.get(date)
        
        snap = {
            "ts":    now_str,
            "ecmwf": ecmwf.get(date),
            "hrrr":  hrrr.get(date) if date <= (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d") else None,
            "metar": get_metar(city_slug) if date == today else None,
            "gfs_mean": gfs_data.get("mean") if gfs_data else None,
            "gfs_confidence": gfs_data.get("confidence") if gfs_data else None,
            "gfs_members": gfs_data.get("members") if gfs_data else 0,
        }
        # Best forecast: HRRR for US D+0/D+1, otherwise ECMWF
        loc = LOCATIONS[city_slug]
        if loc["region"] == "us" and snap["hrrr"] is not None:
            snap["best"] = snap["hrrr"]
            snap["best_source"] = "hrrr"
        elif snap["ecmwf"] is not None:
            snap["best"] = snap["ecmwf"]
            snap["best_source"] = "ecmwf"
        else:
            snap["best"] = None
            snap["best_source"] = None
        snapshots[date] = snap
    return snapshots

def scan_and_update():
    """Main function of one cycle: updates forecasts, opens/closes positions."""
    global _cal
    now      = datetime.now(timezone.utc)
    state    = load_state()
    balance  = state["balance"]
    new_pos  = 0
    closed   = 0
    resolved = 0

    for city_slug, loc in LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']}...", end=" ", flush=True)

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(4)]
            snapshots = take_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"skipped ({e})")
            continue

        for i, date in enumerate(dates):
            dt    = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(city_slug, MONTHS[dt.month - 1], dt.day, dt.year)
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours    = hours_to_resolution(end_date) if end_date else 0
            horizon  = f"D+{i}"

            # Load or create market record
            mkt = load_market(city_slug, date)
            if mkt is None:
                if hours < MIN_HOURS or hours > MAX_HOURS:
                    continue
                mkt = new_market(city_slug, date, event, hours)

            # Skip if market already resolved
            if mkt["status"] == "resolved":
                continue

            # Update outcomes list — prices taken directly from event
            outcomes = []
            for market in event.get("markets", []):
                question = market.get("question", "")
                mid      = str(market.get("id", ""))
                volume   = float(market.get("volume", 0))
                rng      = parse_temp_range(question)
                if not rng:
                    continue
                try:
                    prices = json.loads(market.get("outcomePrices", "[0.5,0.5]"))
                    # prices[0] = YES price, prices[1] = NO price
                    yes_price = float(prices[0])
                    no_price = float(prices[1]) if len(prices) > 1 else yes_price
                except Exception:
                    continue
                
                # Determine which side to buy based on bucket type
                # For ALL buckets, we bet that the forecast will be IN the bucket (YES)
                # prices[0] = YES = "forecast WILL be in bucket"
                # prices[1] = NO = "forecast will NOT be in bucket"
                bid = yes_price   # Buy YES at yes_price
                ask = no_price    # Sell NO at no_price
                
                outcomes.append({
                    "question":  question,
                    "market_id": mid,
                    "range":     rng,
                    "bid":       round(bid, 4),    # YES price (what we buy)
                    "ask":       round(ask, 4),    # NO price (what we sell)
                    "price":     round(bid, 4),    # for compatibility
                    "spread":    round(ask - bid, 4),
                    "volume":    round(volume, 0),
                    "yes_price": round(yes_price, 4),
                    "no_price":  round(no_price, 4),
                })

            outcomes.sort(key=lambda x: x["range"][0])
            mkt["all_outcomes"] = outcomes

            # Forecast snapshot
            snap = snapshots.get(date, {})
            forecast_snap = {
                "ts":          snap.get("ts"),
                "horizon":     horizon,
                "hours_left":  round(hours, 1),
                "ecmwf":       snap.get("ecmwf"),
                "hrrr":        snap.get("hrrr"),
                "metar":       snap.get("metar"),
                "best":        snap.get("best"),
                "best_source": snap.get("best_source"),
                "gfs_mean":    snap.get("gfs_mean"),
                "gfs_confidence": snap.get("gfs_confidence"),
                "gfs_members":  snap.get("gfs_members"),
            }
            mkt["forecast_snapshots"].append(forecast_snap)

            # Market price snapshot
            top = max(outcomes, key=lambda x: x["price"]) if outcomes else None
            market_snap = {
                "ts":       snap.get("ts"),
                "top_bucket": f"{top['range'][0]}-{top['range'][1]}{unit_sym}" if top else None,
                "top_price":  top["price"] if top else None,
            }
            mkt["market_snapshots"].append(market_snap)

            forecast_temp = snap.get("best")
            best_source   = snap.get("best_source")

            # --- STOP-LOSS AND TRAILING STOP ---
            if mkt.get("position") and mkt["position"].get("status") == "open":
                pos = mkt["position"]
                current_price = None
                for o in outcomes:
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

                if current_price is not None:
                    current_price = o.get("bid", current_price)  # sell at bid
                    entry = pos["entry_price"]
                    stop  = pos.get("stop_price", entry * 0.80)  # 20% stop by default

                    # Trailing: if up 20%+ — move stop to breakeven
                    if current_price >= entry * 1.20 and stop < entry:
                        pos["stop_price"] = entry
                        pos["trailing_activated"] = True

                    # Check stop
                    if current_price <= stop:
                        pnl = round((current_price - entry) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        pos["closed_at"]    = snap.get("ts")
                        pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
                        pos["exit_price"]   = current_price
                        pos["pnl"]          = pnl
                        pos["status"]       = "closed"
                        closed += 1
                        reason = "STOP" if current_price < entry else "TRAILING BE"
                        print(f"  [{reason}] {loc['name']} {date} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")

            # --- CLOSE POSITION if forecast shifted 2+ degrees ---
            if mkt.get("position") and forecast_temp is not None:
                pos = mkt["position"]
                old_bucket_low  = pos["bucket_low"]
                old_bucket_high = pos["bucket_high"]
                # 2-degree buffer — avoid closing on small forecast fluctuations
                unit = loc["unit"]
                buffer = 2.0 if unit == "F" else 1.0
                mid_bucket = (old_bucket_low + old_bucket_high) / 2 if old_bucket_low != -999 and old_bucket_high != 999 else forecast_temp
                forecast_far = abs(forecast_temp - mid_bucket) > (abs(mid_bucket - old_bucket_low) + buffer)
                if not in_bucket(forecast_temp, old_bucket_low, old_bucket_high) and forecast_far:
                    current_price = None
                    for o in outcomes:
                        if o["market_id"] == pos["market_id"]:
                            current_price = o["price"]
                            break
                    if current_price is not None:
                        pnl = round((current_price - pos["entry_price"]) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        mkt["position"]["closed_at"]    = snap.get("ts")
                        mkt["position"]["close_reason"] = "forecast_changed"
                        mkt["position"]["exit_price"]   = current_price
                        mkt["position"]["pnl"]          = pnl
                        mkt["position"]["status"]       = "closed"
                        closed += 1
                        print(f"  [CLOSE] {loc['name']} {date} — forecast changed | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
                        
                        # Telegram Alert: Position Closed
                        if TELEGRAM_ENABLED:
                            alert_trade_closed(
                                city=loc['name'],
                                date=date,
                                bucket=f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}",
                                pnl=pnl,
                                reason="Forecast Changed",
                                source=pos.get('forecast_src', 'N/A')
                            )

            # --- OPEN POSITION ---
            if not mkt.get("position") and forecast_temp is not None and hours >= MIN_HOURS:
                sigma = get_sigma(city_slug, best_source or "ecmwf")
                
                # Get GFS ensemble confidence for this date
                confidence = snap.get("gfs_confidence")
                
                # Confidence threshold: require high confidence for opening positions
                # If confidence is low, increase EV requirement
                min_ev = MIN_EV
                if confidence is not None:
                    if confidence < 0.5:
                        min_ev = MIN_EV * 1.5  # Require 50% more EV if low confidence
                        print(f"  [LOW CONF] {loc['name']} {date}: conf={confidence}, min_ev={min_ev:.2f}")
                else:
                    # No GFS ensemble data, use default
                    pass
                
                best_signal = None

                for o in outcomes:
                    t_low, t_high = o["range"]
                    price = o["price"]
                    volume = o["volume"]

                    if not in_bucket(forecast_temp, t_low, t_high):
                        continue

                    bid    = o.get("bid", o["price"])
                    ask    = o.get("ask", o["price"])
                    spread = o.get("spread", 0)

                    # Slippage filter
                    if spread > MAX_SLIPPAGE:
                        continue
                    if ask >= MAX_PRICE or volume < MIN_VOLUME:
                        continue

                    p  = bucket_prob(forecast_temp, t_low, t_high, sigma)
                    ev = calc_ev(p, ask)   # EV calculated from ask
                    if ev < min_ev:
                        continue

                    kelly = calc_kelly(p, ask)
                    size  = bet_size(kelly, balance)
                    
                    # MEGA EDGE ALERT: If EV > 50%, this is a HUGE opportunity!
                    # Increase bet size and alert!
                    if ev >= 0.50:
                        mega_edge = True
                        size = min(size * 2.5, MAX_BET * 2)  # Up to 2.5x normal size, up to 2x max bet
                        print(f"  [🔥 MEGA EDGE!] {loc['name']} {date} | EV: {ev:.0%} | Size: ${size:.2f}")
                        if TELEGRAM_ENABLED:
                            from telegram_alerts import alert_mega_edge
                            alert_mega_edge(
                                city=loc['name'],
                                date=date,
                                bucket=f"{t_low}-{t_high}{unit_sym}",
                                ev=ev,
                                forecast_temp=forecast_temp,
                                price=bid,
                                size=size,
                                source=best_source or "ecmwf"
                            )
                    else:
                        mega_edge = False
                    
                    if size < 0.50:
                        continue

                    best_signal = {
                        "market_id":    o["market_id"],
                        "question":     o["question"],
                        "bucket_low":   t_low,
                        "bucket_high":  t_high,
                        "entry_price":  bid,       # enter at YES price (bid)
                        "bid_at_entry": bid,       # what we paid for YES
                        "yes_price_at_entry": o.get("yes_price", bid),
                        "spread":       spread,
                        "shares":       round(size / bid, 2),  # shares based on YES price
                        "cost":         size,
                        "p":            round(p, 4),    # our probability estimate
                        "ev":           round(ev, 4),
                        "kelly":        round(kelly, 4),
                        "forecast_temp":forecast_temp,
                        "forecast_src": best_source,
                        "sigma":        sigma,
                        "gfs_confidence": confidence,
                        "bug_status":   "after-bug",   # Mark as post-fix
                        "opened_at":    snap.get("ts"),
                        "status":       "open",
                        "pnl":          None,
                        "exit_price":   None,
                        "close_reason": None,
                        "closed_at":    None,
                    }
                    break

                if best_signal:
                    balance -= best_signal["cost"]
                    mkt["position"] = best_signal
                    state["total_trades"] += 1
                    new_pos += 1
                    bucket_label = f"{best_signal['bucket_low']}-{best_signal['bucket_high']}{unit_sym}"
                    print(f"  [BUY]  {loc['name']} {horizon} {date} | {bucket_label} | "
                          f"${best_signal['entry_price']:.3f} | EV {best_signal['ev']:+.2f} | "
                          f"${best_signal['cost']:.2f} ({best_signal['forecast_src'].upper()})")
                    
                    # Telegram Alert: New Trade
                    if TELEGRAM_ENABLED:
                        alert_new_trade(
                            city=loc['name'],
                            date=date,
                            bucket=bucket_label,
                            price=best_signal['entry_price'],
                            ev=best_signal['ev'],
                            cost=best_signal['cost'],
                            source=best_signal['forecast_src']
                        )

            # Market closed by time
            if hours < 0.5 and mkt["status"] == "open":
                mkt["status"] = "closed"

            save_market(mkt)
            time.sleep(0.1)

        print("ok")

    # --- AUTO-RESOLUTION ---
    for mkt in load_all_markets():
        if mkt["status"] == "resolved":
            continue

        pos = mkt.get("position")
        if not pos or pos.get("status") != "open":
            continue

        market_id = pos.get("market_id")
        if not market_id:
            continue

        # Check if market closed on Polymarket
        won = check_market_resolved(market_id)
        if won is None:
            continue  # market still open

        # Market closed — record result
        price  = pos["entry_price"]
        size   = pos["cost"]
        shares = pos["shares"]
        pnl    = round(shares * (1 - price), 2) if won else round(-size, 2)

        balance += size + pnl
        pos["exit_price"]   = 1.0 if won else 0.0
        pos["pnl"]          = pnl
        pos["close_reason"] = "resolved"
        pos["closed_at"]    = now.isoformat()
        pos["status"]       = "closed"
        mkt["pnl"]          = pnl
        mkt["status"]       = "resolved"
        mkt["resolved_outcome"] = "win" if won else "loss"

        if won:
            state["wins"] += 1
        else:
            state["losses"] += 1

        result = "WIN" if won else "LOSS"
        print(f"  [{result}] {mkt['city_name']} {mkt['date']} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
        resolved += 1
        
        # Telegram Alert: Trade Resolved
        if TELEGRAM_ENABLED:
            # Get actual temp if available
            actual_temp = mkt.get('actual_temp')
            forecast_temp = pos.get('forecast_temp')
            alert_trade_resolved(
                city=mkt['city_name'],
                date=mkt['date'],
                pnl=pnl,
                actual_temp=actual_temp if actual_temp else forecast_temp if forecast_temp else "N/A",
                forecast=pos.get('forecast_temp', 'N/A'),
                source=pos.get('forecast_src', 'N/A')
            )

        save_market(mkt)
        time.sleep(0.3)

    state["balance"]      = round(balance, 2)
    state["peak_balance"] = max(state.get("peak_balance", balance), balance)
    save_state(state)

    # Run calibration if enough data collected
    all_mkts = load_all_markets()
    resolved_count = len([m for m in all_mkts if m["status"] == "resolved"])
    if resolved_count >= CALIBRATION_MIN:
        global _cal
        _cal = run_calibration(all_mkts)

    return new_pos, closed, resolved

# =============================================================================
# REPORT
# =============================================================================

def print_status():
    state    = load_state()
    markets  = load_all_markets()
    open_pos = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
    resolved = [m for m in markets if m["status"] == "resolved" and m.get("pnl") is not None]

    bal     = state["balance"]
    start   = state["starting_balance"]
    ret_pct = (bal - start) / start * 100
    wins    = state["wins"]
    losses  = state["losses"]
    total   = wins + losses

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STATUS")
    print(f"{'='*55}")
    print(f"  Balance:     ${bal:,.2f}  (start ${start:,.2f}, {'+'if ret_pct>=0 else ''}{ret_pct:.1f}%)")
    print(f"  Trades:      {total} | W: {wins} | L: {losses} | WR: {wins/total:.0%}" if total else "  No trades yet")
    print(f"  Open:        {len(open_pos)}")
    print(f"  Resolved:    {len(resolved)}")

    if open_pos:
        print(f"\n  Open positions:")
        total_unrealized = 0.0
        for m in open_pos:
            pos      = m["position"]
            unit_sym = "F" if m["unit"] == "F" else "C"
            label    = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"

            # Current price from latest market snapshot
            current_price = pos["entry_price"]
            snaps = m.get("market_snapshots", [])
            if snaps:
                # Find our bucket price in all_outcomes
                for o in m.get("all_outcomes", []):
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

            unrealized = round((current_price - pos["entry_price"]) * pos["shares"], 2)
            total_unrealized += unrealized
            pnl_str = f"{'+'if unrealized>=0 else ''}{unrealized:.2f}"

            print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | "
                  f"entry ${pos['entry_price']:.3f} -> ${current_price:.3f} | "
                  f"PnL: {pnl_str} | {pos['forecast_src'].upper()}")

        sign = "+" if total_unrealized >= 0 else ""
        print(f"\n  Unrealized PnL: {sign}{total_unrealized:.2f}")

    print(f"{'='*55}\n")

def print_report():
    markets  = load_all_markets()
    resolved = [m for m in markets if m["status"] == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — FULL REPORT")
    print(f"{'='*55}")

    if not resolved:
        print("  No resolved markets yet.")
    else:
        total_pnl = sum(m["pnl"] for m in resolved)
        wins      = [m for m in resolved if m["resolved_outcome"] == "win"]
        losses    = [m for m in resolved if m["resolved_outcome"] == "loss"]

        print(f"\n  Total resolved: {len(resolved)}")
        print(f"  Wins:           {len(wins)} | Losses: {len(losses)}")
        print(f"  Win rate:       {len(wins)/len(resolved):.0%}")
        print(f"  Total PnL:      {'+'if total_pnl>=0 else ''}{total_pnl:.2f}")

    # Calibration & Brier Score Report
    cal = load_cal()
    if cal:
        print(f"\n  CALIBRATION (Brier Score):")
        print(f"  {'City':<16} {'Source':<8} {'Brier':<8} {'N':<5} {'Quality'}")
        print(f"  {'-'*50}")
        
        for city in sorted(set(m["city"] for m in markets if m.get("city"))):
            for source in ["ecmwf", "hrrr", "metar"]:
                key = f"{city}_{source}"
                if key in cal and "brier_score" in cal[key]:
                    brier = cal[key]["brier_score"]
                    n = cal[key].get("brier_n", 0)
                    if brier < 0.15:
                        quality = "🟢 Excellent"
                    elif brier < 0.25:
                        quality = "🟡 Good"
                    elif brier < 0.35:
                        quality = "🟠 Fair"
                    else:
                        quality = "🔴 Poor"
                    print(f"  {LOCATIONS[city]['name']:<16} {source:<8} {brier:.4f}   {n:<5} {quality}")

    if not resolved:
        print(f"{'='*55}\n")
        return

    # Bug Check: Verify entry prices are reasonable
    print(f"\n  BUG CHECK (Entry Price Validation):")
    print(f"  {'City':<16} {'Forecast':<10} {'Bucket':<12} {'Entry':<8} {'Expected'}")
    print(f"  {'-'*60}")
    bugs_found = 0
    for m in resolved:
        pos = m.get("position", {})
        forecast = pos.get("forecast_temp")
        entry = pos.get("entry_price", 0)
        bucket = f"{pos.get('bucket_low', 'N/A')}-{pos.get('bucket_high', 'N/A')}"
        
        # Check if entry price makes sense
        # For a "≤" bucket with forecast below threshold, entry should be HIGH (>0.5)
        # For a "≤" bucket with forecast above threshold, entry should be LOW (<0.5)
        if forecast and entry:
            # Simple check: if forecast is in bucket, entry should be >0.5
            t_low, t_high = pos.get("bucket_low", -999), pos.get("bucket_high", 999)
            in_bucket = t_low <= forecast <= t_high
            expected_high = in_bucket  # If in bucket, expect high entry
            actual_high = entry > 0.5
            
            if expected_high != actual_high:
                status = "🔴 BUG"
                bugs_found += 1
            else:
                status = "🟢 OK"
            
            print(f"  {LOCATIONS.get(m['city'], {}).get('name', m['city']):<16} {forecast:<10.1f} {bucket:<12} {entry:<8.3f} {status}")
    
    if bugs_found > 0:
        print(f"\n  ⚠️  Found {bugs_found} potential bugs in entry pricing!")
        print(f"  This indicates YES/NO price interpretation may be wrong.")
    else:
        print(f"\n  ✅ All entry prices look correct.")

    print(f"\n  By city:")
    for city in sorted(set(m["city"] for m in resolved)):
        group = [m for m in resolved if m["city"] == city]
        w     = len([m for m in group if m["resolved_outcome"] == "win"])
        pnl   = sum(m["pnl"] for m in group)
        name  = LOCATIONS[city]["name"]
        print(f"    {name:<16} {w}/{len(group)} ({w/len(group):.0%})  PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")

    print(f"\n  Market details:")
    for m in sorted(resolved, key=lambda x: x["date"]):
        pos      = m.get("position", {})
        unit_sym = "F" if m["unit"] == "F" else "C"
        snaps    = m.get("forecast_snapshots", [])
        first_fc = snaps[0]["best"] if snaps else None
        last_fc  = snaps[-1]["best"] if snaps else None
        label    = f"{pos.get('bucket_low')}-{pos.get('bucket_high')}{unit_sym}" if pos else "no position"
        result   = m["resolved_outcome"].upper()
        pnl_str  = f"{'+'if m['pnl']>=0 else ''}{m['pnl']:.2f}" if m["pnl"] is not None else "-"
        fc_str   = f"forecast {first_fc}->{last_fc}{unit_sym}" if first_fc else "no forecast"
        actual   = f"actual {m['actual_temp']}{unit_sym}" if m["actual_temp"] else ""
        print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | {fc_str} | {actual} | {result} {pnl_str}")

    print(f"{'='*55}\n")

# =============================================================================
# MAIN LOOP
# =============================================================================

MONITOR_INTERVAL = 600  # monitor positions every 10 minutes

def check_auto_redemption(mkt, pos, current_price):
    """Check if position should be auto-redeemed based on Option B criteria."""
    if not AUTO_REDEMPTION.get("enabled", False):
        return None
    
    entry = pos["entry_price"]
    shares = pos["shares"]
    cost = pos["cost"]
    pnl_pct = (current_price - entry) / entry
    
    # Check min hold time
    opened_str = pos.get("opened_at", "")
    if opened_str:
        try:
            opened = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
            hours_held = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            if hours_held < AUTO_REDEMPTION["min_hold_hours"]:
                return None  # Too new, skip
        except:
            pass
    
    city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
    
    # Criterion 1: Price > $0.99 → Sell 100%
    if current_price >= AUTO_REDEMPTION["price_high"]:
        return {
            "action": "sell_full",
            "reason": f"AUTO: price ${current_price:.3f} > $0.99 (near certain win)",
            "pct": 1.0,
            "pnl_pct": pnl_pct * 100
        }
    
    # Criterion 2: P&L > 500% → Sell 75%
    if pnl_pct >= AUTO_REDEMPTION["pnl_extreme"]:
        return {
            "action": "sell_75",
            "reason": f"AUTO: P&L {pnl_pct*100:.0f}% > 500%",
            "pct": 0.75,
            "pnl_pct": pnl_pct * 100
        }
    
    # Criterion 3: Price > $0.95 AND P&L > 100% → Sell 50%
    if current_price >= AUTO_REDEMPTION["price_mid"] and pnl_pct >= AUTO_REDEMPTION["pnl_threshold"]:
        return {
            "action": "sell_50",
            "reason": f"AUTO: price ${current_price:.3f} > $0.95 AND P&L {pnl_pct*100:.0f}% > 100%",
            "pct": 0.50,
            "pnl_pct": pnl_pct * 100
        }
    
    # Criterion 4: P&L < -20% → Stop loss
    if pnl_pct <= AUTO_REDEMPTION["stop_loss"]:
        return {
            "action": "stop_loss",
            "reason": f"AUTO: P&L {pnl_pct*100:.0f}% < -20%",
            "pct": 1.0,
            "pnl_pct": pnl_pct * 100
        }
    
    return None

def monitor_positions():
    """Quick stop check on open positions without full scan."""
    markets  = load_all_markets()
    open_pos = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
    if not open_pos:
        return 0

    state   = load_state()
    balance = state["balance"]
    closed  = 0

    for mkt in open_pos:
        pos = mkt["position"]
        mid = pos["market_id"]

        # Get current price from all_outcomes (no extra requests)
        current_price = None
        for o in mkt.get("all_outcomes", []):
            if o["market_id"] == mid:
                current_price = o.get("bid", o["price"])  # use bid — sell price
                break

        if current_price is None:
            continue

        entry = pos["entry_price"]
        stop  = pos.get("stop_price", entry * 0.80)

        # Trailing: if up 20%+ — move stop to breakeven
        if current_price >= entry * 1.20 and stop < entry:
            pos["stop_price"] = entry
            pos["trailing_activated"] = True
            city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
            print(f"  [TRAILING] {city_name} {mkt['date']} — stop moved to breakeven ${entry:.3f}")

        # Check stop
        if current_price <= stop:
            pnl = round((current_price - entry) * pos["shares"], 2)
            balance += pos["cost"] + pnl
            pos["closed_at"]    = datetime.now(timezone.utc).isoformat()
            pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
            pos["exit_price"]   = current_price
            pos["pnl"]          = pnl
            pos["status"]       = "closed"
            closed += 1
            reason = "STOP" if current_price < entry else "TRAILING BE"
            city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
            print(f"  [{reason}] {city_name} {mkt['date']} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
            save_market(mkt)
            continue
        
        # Auto-Redemption Check (Option B)
        auto_action = check_auto_redemption(mkt, pos, current_price)
        if auto_action:
            city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
            sell_pct = auto_action["pct"]
            sell_shares = int(pos["shares"] * sell_pct)
            sell_value = round((current_price - entry) * sell_shares, 2)
            
            if auto_action["action"] == "sell_full" or auto_action["action"] == "stop_loss":
                # Full close
                balance += pos["cost"] + sell_value
                pos["closed_at"]    = datetime.now(timezone.utc).isoformat()
                pos["close_reason"] = auto_action["action"]
                pos["exit_price"]   = current_price
                pos["pnl"]          = sell_value
                pos["status"]       = "closed"
                closed += 1
                print(f"  [AUTO-{auto_action['action'].upper()}] {city_name} {mkt['date']} | PnL: +{auto_action['pnl_pct']:.0f}% | {auto_action['reason']}")
            else:
                # Partial close
                partial_cost = round(pos["cost"] * sell_pct, 2)
                balance += partial_cost + sell_value
                pos["cost"] = round(pos["cost"] * (1 - sell_pct), 2)
                pos["shares"] = pos["shares"] - sell_shares
                remaining_pnl = round((current_price - entry) * pos["shares"], 2)
                print(f"  [AUTO-{auto_action['action'].upper()}] {city_name} {mkt['date']} | Sold {sell_pct*100:.0f}% @ ${current_price:.3f} | PnL locked: +{sell_value:.2f} | Remaining: {pos['shares']} shares")
                
                # Alert via Telegram if enabled
                if TELEGRAM_ENABLED:
                    alert_pnl_update(city_name, current_price, entry, remaining_pnl, auto_action["reason"])
            
            save_market(mkt)

    if closed:
        state["balance"] = round(balance, 2)
        save_state(state)

    return closed


def run_loop():
    global _cal
    _cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STARTING")
    print(f"{'='*55}")
    print(f"  Cities:     {len(LOCATIONS)}")
    print(f"  Balance:    ${BALANCE:,.0f} | Max bet: ${MAX_BET}")
    print(f"  Scan:       {SCAN_INTERVAL//60} min | Monitor: {MONITOR_INTERVAL//60} min")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Data:       {DATA_DIR.resolve()}")
    print(f"  Ctrl+C to stop\n")

    # Telegram Alert: Bot Started
    if TELEGRAM_ENABLED:
        alert_bot_started()

    last_full_scan = 0

    while True:
        now_ts  = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Full scan once per hour
        if now_ts - last_full_scan >= SCAN_INTERVAL:
            print(f"[{now_str}] full scan...")
            try:
                new_pos, closed, resolved = scan_and_update()
                state = load_state()
                print(f"  balance: ${state['balance']:,.2f} | "
                      f"new: {new_pos} | closed: {closed} | resolved: {resolved}")
                last_full_scan = time.time()
            except KeyboardInterrupt:
                print(f"\n  Stopping — saving state...")
                save_state(load_state())
                print(f"  Done. Bye!")
                break
            except requests.exceptions.ConnectionError:
                print(f"  Connection lost — waiting 60 sec")
                time.sleep(60)
                continue
            except Exception as e:
                print(f"  Error: {e} — waiting 60 sec")
                time.sleep(60)
                continue
        else:
            # Quick stop monitoring
            print(f"[{now_str}] monitoring positions...")
            try:
                stopped = monitor_positions()
                if stopped:
                    state = load_state()
                    print(f"  balance: ${state['balance']:,.2f}")
            except Exception as e:
                print(f"  Monitor error: {e}")

        try:
            time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n  Stopping — saving state...")
            save_state(load_state())
            print(f"  Done. Bye!")
            break

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run_loop()
    elif cmd == "status":
        _cal = load_cal()
        print_status()
    elif cmd == "report":
        _cal = load_cal()
        print_report()
    else:
        print("Usage: python bot_v2.py [run|status|report]")

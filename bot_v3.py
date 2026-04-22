#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_v3.0.py — Weather Trading Bot for Polymarket
=====================================================
Tracks weather forecasts from 3 sources (ECMWF, HRRR, METAR),
compares with Polymarket markets, paper trades using Kelly criterion.

v3.0: 12 improvements — weighted ensemble, variable Kelly, adaptive scan,
      dynamic blocking, METAR bias correction, Brier-optimized sigma, and more.
v3.1: Smart filtering (confidence, bucket width, margin, bias correction)
v3.2: Optimized filters (data-driven, less restrictive)
v3.3: 8 tropical cities added (HK, Mumbai, Bangkok, Dubai, Mexico City, Bogota, Jakarta, Istanbul)
v3.4: Multi-model ensemble (ECMWF+ICON+JMA+UKMO+METEOFRANCE+GEM), spread-based filtering

Usage:
    python bot_v3.py          # main loop
    python bot_v3.py report   # full report
    python bot_v3.py status   # balance and open positions
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
MAX_BET          = _cfg.get("max_bet", 25.0)        # max bet per trade
MIN_EV           = _cfg.get("min_ev", 0.10)  # 10% - balanced for better coverage
MAX_PRICE        = _cfg.get("max_price", 0.65)  # v3.2: restored from 0.55 — data showed expensive entries were profitable
MIN_VOLUME       = _cfg.get("min_volume", 10000)  # $10k - increased for liquidity
MIN_HOURS        = _cfg.get("min_hours", 2.0)
MAX_HOURS        = _cfg.get("max_hours", 72.0)
KELLY_FRACTION   = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE     = _cfg.get("max_slippage", 0.03)  # max allowed ask-bid spread
SCAN_INTERVAL    = _cfg.get("scan_interval", 1800)     # every 30 min
CALIBRATION_MIN  = _cfg.get("calibration_min", 30)
VC_KEY           = _cfg.get("vc_key", "")
FAST_SCAN_INTERVAL = _cfg.get("fast_scan_interval", 900)   # 15 min (#8)
SLOW_SCAN_INTERVAL = _cfg.get("slow_scan_interval", 1800)  # 30 min (#8)
ADAPTIVE_SCAN    = _cfg.get("adaptive_scan", True)          # (#8)

SIGMA_F = 2.0
SIGMA_C = 1.2

# Auto-Redemption Config (Conservative)
AUTO_REDEMPTION = {
    "enabled": True,
    "price_high": 0.95,        # Sell 100% if price > $0.95 (more conservative)
    "price_mid": 0.90,        # Sell 50% if price > $0.90 AND P&L > 50%
    "pnl_threshold": 1.0,    # P&L > 100% triggers mid-level sell
    "pnl_extreme": 3.0,      # P&L > 300% triggers 75% sell
    "stop_loss": -0.15,       # Stop loss at -15% (tighter)
    "min_hold_hours": 4,      # Don't sell if < 4h old
}

# Cities Filter - Only trade in cities with good accuracy
ALLOWED_CITIES = [
    "lucknow",      # 2/2 wins - BEST
    "toronto",     # 1/1 win - Excellent
    "paris",       # 1/1 win - Good
    "london",      # Unknown - Include for data
    "seoul",       # Unknown - Include for data
    "tokyo",       # Unknown - Include for data
    "singapore",   # 1/1 win - Good
    "buenos-aires", # Unknown
    "sao-paulo",   # Unknown
    "tel-aviv",    # Unknown
    # v3.3: Tropical cities (stable climate, more predictable)
    "hong-kong",   # Tropical/subtropical - stable temps
    "mumbai",      # Tropical - very stable
    "bangkok",     # Tropical - predictable
    "dubai",       # Desert - extremely stable
    "mexico-city", # Subtropical altitude - moderate
    "bogota",      # Tropical altitude - stable
    "jakarta",     # Tropical equatorial - very stable
    "manila",      # v3.4.2: Tropical monsoon - spread 2.5°C, vol $6.9K
    "madrid",      # v3.4.2: Mediterranean - spread 2.1°C, vol $3.9K
]

# Blocked cities (poor accuracy historically) — can be overridden dynamically (#12)
BLOCKED_CITIES = [
    "ankara",      # 0/1 loss
    "atlanta",     # 0/1 loss
    "chicago",     # 0/1 loss
    "miami",       # 0/1 loss
    "munich",      # 0/1 loss
    "nyc",         # 0/1 loss
    "seattle",     # Unknown
    "dallas",      # Unknown
    "shanghai",    # API blocked — Open-Meteo inaccessible from China region
    "wellington",  # API error — noaa_gfs_v2_0 hangs on Open-Meteo
    "istanbul",    # v3.4.1: Polymarket market returns 0 outcomes, hangs scan
    "buenos-aires", # v3.4.2: 0/3 losses — forecast precise but bucket edge misplacement
]

# Dynamic blocked cities (#12) — populated at runtime
DYNAMIC_BLOCKED_CITIES = set()

# City-specific auto-redemption thresholds (#6)
CITY_THRESHOLDS = {}
# Populated dynamically in scan_and_update based on historical sigma

# Auto-Reinvestment Config (Conservative - 25%)
AUTO_REINVEST = {
    "enabled": True,
    "mode": "conservative",    # off, conservative (25%), moderate (50%), aggressive (100%)
    "min_balance": 10000,       # Don't reinvest below this
    "max_balance": 50000,      # Cap at this to limit exposure
    "fraction": 0.25,          # 25% of profits reinvested
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
    # v3.3: Tropical cities - stable climates, more predictable
    "hong-kong":   {"lat":  22.3193, "lon":  114.1694, "name": "Hong Kong",    "station": "VHHH", "unit": "C", "region": "asia"},
    "mumbai":      {"lat":  19.0760, "lon":   72.8777, "name": "Mumbai",       "station": "VABB", "unit": "C", "region": "asia"},
    "bangkok":     {"lat":  13.7563, "lon":  100.5018, "name": "Bangkok",      "station": "VTBS", "unit": "C", "region": "asia"},
    "dubai":       {"lat":  25.2048, "lon":   55.2708, "name": "Dubai",        "station": "OMDB", "unit": "C", "region": "asia"},
    "mexico-city": {"lat":  19.4326, "lon":  -99.1332, "name": "Mexico City",  "station": "MMMX", "unit": "C", "region": "na"},
    "bogota":      {"lat":   4.7110, "lon":  -74.0721, "name": "Bogota",       "station": "SKBO", "unit": "C", "region": "sa"},
    "jakarta":     {"lat":  -6.2088, "lon":  106.8456, "name": "Jakarta",      "station": "WIII", "unit": "C", "region": "asia"},
    "manila":      {"lat":  14.5995, "lon":  120.9842, "name": "Manila",       "station": "RPLL", "unit": "C", "region": "asia"},
    "madrid":      {"lat":  40.4168, "lon":  -3.7038, "name": "Madrid",       "station": "LEMD", "unit": "C", "region": "eu"},
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
    "buenos-aires": "America/Argentina/Buenos_Aires",
    # v3.3: Tropical cities
    "hong-kong": "Asia/Hong_Kong", "mumbai": "Asia/Kolkata",
    "bangkok": "Asia/Bangkok", "dubai": "Asia/Dubai",
    "mexico-city": "America/Mexico_City", "bogota": "America/Bogota",
    "jakarta": "Asia/Jakarta", "manila": "Asia/Manila", "madrid": "Europe/Madrid",
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

def calc_kelly(p, price, confidence=None):
    """Kelly criterion with variable fraction based on confidence (#4)."""
    if price <= 0 or price >= 1: return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    
    # Variable Kelly fraction based on GFS confidence (#4)
    if confidence is not None:
        if confidence > 0.7:
            kelly_frac = 0.50   # High confidence → 50%
        elif confidence >= 0.4:
            kelly_frac = 0.30   # Medium confidence → 30%
        else:
            kelly_frac = 0.15   # Low confidence → 15%
    else:
        kelly_frac = KELLY_FRACTION  # Default 25%
    
    return round(min(max(0.0, f) * kelly_frac, 1.0), 4)

def bet_size(kelly, balance, state=None, confidence=None):
    """Calculate bet size with optional auto-reinvestment and confidence scaling (#9)."""
    # Base bet from Kelly
    raw = kelly * balance
    
    # Confidence scaling (#9)
    if confidence is not None:
        if confidence < 0.3:
            raw *= 0.25
        elif confidence < 0.5:
            raw *= 0.5
        elif confidence > 0.8:
            raw *= 1.25
    
    # Auto-reinvestment: add 25% of accumulated profits to bet size
    if AUTO_REINVEST.get("enabled", False) and state:
        reinvest_pool = state.get("realized_profits", 0.0)
        min_bal = AUTO_REINVEST.get("min_balance", 10000)
        max_bal = AUTO_REINVEST.get("max_balance", 50000)
        fraction = AUTO_REINVEST.get("fraction", 0.25)
        
        # Only reinvest if above min_balance
        if balance >= min_bal and reinvest_pool > 0:
            extra = min(reinvest_pool * fraction, max_bal - balance)
            if extra > 0:
                raw += extra
    
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
    if key in _cal and "sigma" in _cal[key]:
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
    
    v3.0 (#2): Brier Score adjusted by price impact:
        brier = ((p * price) - actual_outcome)²
    
    v3.0 (#7): Sigma optimized via grid search to minimize Brier score
        instead of sigma = MAE.
    """
    resolved = [m for m in markets if m.get("resolved") and m.get("actual_temp") is not None]
    cal = load_cal()
    updated = []

    for source in ["ecmwf", "hrrr", "metar"]:
        for city in set(m["city"] for m in resolved):
            group = [m for m in resolved if m["city"] == city]
            brier_scores = []
            forecast_actual_pairs = []  # (forecast_temp, actual_temp) for sigma grid search
            
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
                forecast_actual_pairs.append((forecast_temp, actual_temp))
                
                # Calculate Brier Score with price impact adjustment (#2)
                if m.get("position"):
                    predicted_prob = m["position"].get("p", 0.5)
                    entry_price = m["position"].get("entry_price", 0.5)
                    actual_outcome = 1 if m["resolved_outcome"] == "win" else 0
                    # Price-adjusted Brier (#2): brier = ((p * price) - actual)²
                    brier = ((predicted_prob * entry_price) - actual_outcome) ** 2
                    brier_scores.append(brier)
            
            if len(forecast_actual_pairs) < CALIBRATION_MIN:
                continue
            
            # Grid search for optimal sigma (#7)
            best_sigma = None
            best_brier_sigma = float('inf')
            
            # Build bucket info from positions for sigma optimization
            bucket_pairs = []
            for m in group:
                pos = m.get("position")
                if not pos:
                    continue
                snap = None
                for s in reversed(m.get("forecast_snapshots", [])):
                    if s.get("best_source") == source or source in s.get("best_source", ""):
                        snap = s
                        break
                if snap and snap.get("best") is not None:
                    bucket_pairs.append({
                        "forecast": snap["best"],
                        "actual": m["actual_temp"],
                        "t_low": pos.get("bucket_low", -999),
                        "t_high": pos.get("bucket_high", 999),
                        "won": m.get("resolved_outcome") == "win"
                    })
            
            if bucket_pairs:
                for sigma_try in [round(s * 0.1, 1) for s in range(5, 51)]:  # 0.5 to 5.0
                    brier_sum = 0.0
                    count = 0
                    for bp in bucket_pairs:
                        p = bucket_prob(bp["forecast"], bp["t_low"], bp["t_high"], sigma_try)
                        actual = 1.0 if bp["won"] else 0.0
                        entry_p = bp.get("entry_price", 0.5)
                        brier_sum += ((p * entry_p) - actual) ** 2
                        count += 1
                    if count > 0:
                        avg_brier = brier_sum / count
                        if avg_brier < best_brier_sigma:
                            best_brier_sigma = avg_brier
                            best_sigma = sigma_try
            
            # Fallback: use MAE if grid search didn't find anything
            if best_sigma is None:
                errors = [abs(f - a) for f, a in forecast_actual_pairs]
                best_sigma = round(sum(errors) / len(errors), 3)
            
            brier_score = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5
            
            key = f"{city}_{source}"
            old = cal.get(key, {}).get("sigma", SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C)
            old_brier = cal.get(key, {}).get("brier_score", 0.25)
            new_brier = round(brier_score, 4)
            
            cal[key] = {
                "sigma": round(best_sigma, 3), 
                "n": len(forecast_actual_pairs), 
                "brier_score": new_brier,
                "brier_n": len(brier_scores),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if abs(best_sigma - old) > 0.05:
                updated.append(f"{LOCATIONS[city]['name']} {source}: σ {old:.2f}->{best_sigma:.2f}")
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
        # Get forecasts from multiple models (ECMWF + GFS + NOAA)
        models = ["ecmwf_ifs025", "gfs_seamless", "noaa_gfs_v2_0"]
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
# WEIGHTED ENSEMBLE FORECAST (#5)
# =============================================================================

def get_weighted_forecast(city_slug, date, snap):
    """
    Weighted ensemble forecast based on historical Brier score per source (#5).
    Instead of picking HRRR or ECMWF, use weighted average.
    Weight formula: w = 1 / (brier + 0.01), normalized.
    """
    sources_temps = {}
    if snap.get("ecmwf") is not None:
        sources_temps["ecmwf"] = snap["ecmwf"]
    if snap.get("hrrr") is not None:
        sources_temps["hrrr"] = snap["hrrr"]
    
    if not sources_temps:
        return None, None
    
    if len(sources_temps) == 1:
        src = list(sources_temps.keys())[0]
        return sources_temps[src], src
    
    # Calculate weights from Brier scores
    weights = {}
    for src in sources_temps:
        brier = get_brier_score(city_slug, src)
        weights[src] = 1.0 / (brier + 0.01)
    
    total_w = sum(weights.values())
    weighted_temp = sum(sources_temps[src] * weights[src] for src in sources_temps) / total_w
    
    loc = LOCATIONS[city_slug]
    weighted_temp = round(weighted_temp, 1) if loc["unit"] == "C" else round(weighted_temp)
    
    # Best source is the one with highest weight
    best_src = max(weights, key=weights.get)
    
    return weighted_temp, f"ensemble({','.join(sources_temps.keys())})"

# =============================================================================
# METAR BIAS CORRECTION (#11)
# =============================================================================

def calc_forecast_bias(city_slug):
    """
    Compare METAR observations with ECMWF/HRRR forecasts to detect systematic bias (#11).
    Returns bias dict: {"ecmwf": bias_val, "hrrr": bias_val}
    Bias = mean(forecast - actual)
    """
    cal = load_cal()
    bias = {}
    
    for source in ["ecmwf", "hrrr"]:
        key = f"{city_slug}_{source}"
        if key in cal and cal[key].get("bias") is not None:
            bias[source] = cal[key]["bias"]
    
    return bias

def apply_bias_correction(forecast, city_slug, source):
    """Apply METAR-based bias correction (#11)."""
    cal = load_cal()
    key = f"{city_slug}_{source}"
    if key in cal and cal[key].get("bias") is not None:
        return round(forecast - cal[key]["bias"], 1)
    return forecast

def update_forecast_bias(city_slug):
    """
    Calculate and store forecast bias by comparing recent METAR vs forecasts (#11).
    Called during scan cycles.
    """
    markets = load_all_markets()
    cal = load_cal()
    
    for source in ["ecmwf", "hrrr"]:
        diffs = []
        for m in markets:
            if m.get("city") != city_slug or not m.get("actual_temp"):
                continue
            for snap in m.get("forecast_snapshots", []):
                if snap.get(source) is not None and m.get("actual_temp") is not None:
                    diffs.append(snap[source] - m["actual_temp"])
        
        if len(diffs) >= 5:  # Need at least 5 comparisons
            bias = round(sum(diffs) / len(diffs), 3)
            key = f"{city_slug}_{source}"
            if key not in cal:
                cal[key] = {}
            cal[key]["bias"] = bias
            cal[key]["bias_n"] = len(diffs)
    
    CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")

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
        "realized_profits": 0.0,  # For auto-reinvestment tracking
    }

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# =============================================================================
# DYNAMIC BLOCKED CITIES (#12)
# =============================================================================

def update_dynamic_blocked_cities():
    """
    Dynamically block/unblock cities based on Brier scores (#12).
    - Block if Brier > 0.35 after 5+ resolved markets
    - Unblock if Brier improves to < 0.25
    """
    global DYNAMIC_BLOCKED_CITIES
    cal = load_cal()
    markets = load_all_markets()
    
    # Count resolved markets per city
    city_resolved = {}
    for m in markets:
        if m.get("status") == "resolved":
            city_resolved[m["city"]] = city_resolved.get(m["city"], 0) + 1
    
    for city in LOCATIONS:
        if city_resolved.get(city, 0) < 5:
            continue
        
        # Get average Brier score across sources
        brier_vals = []
        for source in ["ecmwf", "hrrr"]:
            brier = get_brier_score(city, source)
            if brier != 0.25:  # Has actual data
                brier_vals.append(brier)
        
        if not brier_vals:
            continue
        
        avg_brier = sum(brier_vals) / len(brier_vals)
        
        if avg_brier > 0.35:
            DYNAMIC_BLOCKED_CITIES.add(city)
        elif avg_brier < 0.25 and city in DYNAMIC_BLOCKED_CITIES:
            DYNAMIC_BLOCKED_CITIES.discard(city)

# =============================================================================
# CITY-SPECIFIC THRESHOLDS (#6)
# =============================================================================

def update_city_thresholds():
    """
    Build city-specific auto-redemption thresholds based on historical sigma (#6).
    Formula: stop_loss = base_stop * (1 + sigma/2)
    """
    global CITY_THRESHOLDS
    cal = load_cal()
    
    base_stop = AUTO_REDEMPTION["stop_loss"]
    
    for city in LOCATIONS:
        # Get average sigma across sources
        sigmas = []
        for source in ["ecmwf", "hrrr"]:
            key = f"{city}_{source}"
            if key in cal and "sigma" in cal[key]:
                sigmas.append(cal[key]["sigma"])
        
        if sigmas:
            avg_sigma = sum(sigmas) / len(sigmas)
        else:
            avg_sigma = SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C
        
        # Wider stops for more volatile cities
        city_stop = base_stop * (1 + avg_sigma / 2)
        city_stop = max(city_stop, -0.35)  # Cap at -35%
        
        CITY_THRESHOLDS[city] = {
            "stop_loss": round(city_stop, 3),
            "trailing_pct": 0.50,  # Keep trailing same for now
            "sigma": round(avg_sigma, 3),
        }

# =============================================================================
# v3.4: Multi-Model Ensemble
# =============================================================================

def _fetch_single_model(model_name, model_id, lat, lon, temp_unit, timezone, dates):
    """Fetch forecast for a single model. Returns {date: temp} dict."""
    result = {}
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max&temperature_unit={temp_unit}"
            f"&forecast_days=7&timezone={timezone}"
            f"&models={model_id}"
        )
        data = requests.get(url, timeout=(5, 12)).json()
        if "error" not in data and "daily" in data:
            for date in dates:
                if date in data["daily"]["time"]:
                    idx = data["daily"]["time"].index(date)
                    temp = data["daily"]["temperature_2m_max"][idx]
                    if temp is not None:
                        result[date] = float(temp)
    except Exception:
        pass
    return model_name, result


def get_multi_model_ensemble(city_slug, dates):
    """
    v3.4: Fetch forecasts from 6 models via Open-Meteo in parallel.
    Models: ECMWF, ICON, JMA, UKMO, METEOFRANCE, GEM
    Returns: {date: {"mean": float, "spread": float, "members": list, "temps": dict}}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    tz = TIMEZONES.get(city_slug, "UTC")
    result = {}

    models = {
        "ecmwf": "ecmwf_ifs025",
        "icon": "icon_seamless",
        "jma": "jma_seamless",
        "ukmo": "ukmo_seamless",
        "meteofr": "meteofrance_seamless",
        "gem": "gem_seamless",
    }

    try:
        # Fetch all models in parallel (6 requests in parallel instead of sequential)
        all_temps = {date: {} for date in dates}

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    _fetch_single_model, name, mid, loc["lat"], loc["lon"], temp_unit, tz, dates
                ): name
                for name, mid in models.items()
            }
            for future in as_completed(futures, timeout=20):
                try:
                    model_name, model_result = future.result(timeout=5)
                    for date, temp in model_result.items():
                        all_temps[date][model_name] = temp
                except Exception:
                    pass

        for date, temps in all_temps.items():
            if len(temps) < 3:
                continue  # Need at least 3 models

            values = list(temps.values())
            mean_temp = sum(values) / len(values)
            spread = max(values) - min(values)

            # Consensus: remove outlier (furthest from mean) and recalculate
            if len(values) >= 5:
                deviations = {k: abs(v - mean_temp) for k, v in temps.items()}
                outlier = max(deviations, key=deviations.get)
                filtered = [v for k, v in temps.items() if k != outlier]
                mean_temp = sum(filtered) / len(filtered)
                spread_filtered = max(filtered) - min(filtered)
            else:
                spread_filtered = spread

            result[date] = {
                "mean": round(mean_temp, 1) if unit == "C" else round(mean_temp),
                "spread": round(spread, 1),
                "spread_filtered": round(spread_filtered, 1),
                "members": list(temps.keys()),
                "temps": {k: round(v, 1) for k, v in temps.items()},
            }
    except Exception as e:
        print(f"  [MULTI_MODEL] {city_slug}: {e}")

    return result


# =============================================================================
# CORE LOGIC
# =============================================================================

def take_forecast_snapshot(city_slug, dates):
    """Fetches forecasts from all sources and returns a snapshot."""
    now_str = datetime.now(timezone.utc).isoformat()
    ecmwf   = get_ecmwf(city_slug, dates)
    hrrr    = get_hrrr(city_slug, dates)
    gfs_ens = get_model_ensemble(city_slug, dates)
    multi   = get_multi_model_ensemble(city_slug, dates)  # v3.4: multi-model consensus
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
            # v3.4: multi-model consensus data
            "multi_mean": multi.get(date, {}).get("mean") if multi else None,
            "multi_spread": multi.get(date, {}).get("spread") if multi else None,
            "multi_spread_filtered": multi.get(date, {}).get("spread_filtered") if multi else None,
            "multi_members": multi.get(date, {}).get("members") if multi else [],
            "multi_temps": multi.get(date, {}).get("temps") if multi else {},
        }
        
        # Apply METAR bias correction (#11)
        if snap["ecmwf"] is not None:
            snap["ecmwf_raw"] = snap["ecmwf"]
            snap["ecmwf"] = apply_bias_correction(snap["ecmwf"], city_slug, "ecmwf")
        if snap["hrrr"] is not None:
            snap["hrrr_raw"] = snap["hrrr"]
            snap["hrrr"] = apply_bias_correction(snap["hrrr"], city_slug, "hrrr")
        
        # Weighted ensemble forecast (#5)
        weighted_temp, weighted_src = get_weighted_forecast(city_slug, date, snap)
        
        # v3.4: Prefer multi-model consensus over single-model
        multi_mean = snap.get("multi_mean")
        multi_spread = snap.get("multi_spread")
        
        if multi_mean is not None and (multi_spread is None or multi_spread <= 5.0):
            # Use multi-model consensus if spread is reasonable (<5C)
            snap["best"] = multi_mean
            snap["best_source"] = f"multi_model({len(snap.get('multi_members',[]))}models)"
        elif weighted_temp is not None:
            snap["best"] = weighted_temp
            snap["best_source"] = weighted_src
        elif snap["ecmwf"] is not None:
            snap["best"] = snap["ecmwf"]
            snap["best_source"] = "ecmwf"
        else:
            snap["best"] = None
            snap["best_source"] = None
        
        snapshots[date] = snap
    return snapshots

def find_edge_signal(outcomes, forecast_temp, source, sigma, confidence, balance, state, unit_sym, city_name, date, snap):
    """Try edge buckets (≤X or ≥X) as fallback when no exact bucket qualifies."""
    candidates = []

    for o in outcomes:
        t_low, t_high = o["range"]

        # Only consider edge buckets
        if t_low != -999 and t_high != 999:
            continue

        bid = o.get("bid", o["price"])
        spread = o.get("spread", 0)
        volume = o.get("volume", 0)

        if spread > 0.10:
            continue
        if bid >= 0.75:
            continue
        if volume < 2000:
            continue

        p = bucket_prob(forecast_temp, t_low, t_high, sigma)

        if abs(p - bid) < 0.05:
            continue

        ev = calc_ev(p, bid)

        min_ev_edge = 0.05
        if confidence is not None and confidence < 0.5:
            min_ev_edge = 0.08

        if ev < min_ev_edge:
            continue

        kelly = calc_kelly(p, bid, confidence)
        size = bet_size(kelly, balance, state, confidence) * 0.6

        if size < 1.00:
            continue

        candidates.append({
            "signal": {
                "market_id": o["market_id"],
                "question": o["question"],
                "bucket_low": t_low,
                "bucket_high": t_high,
                "entry_price": bid,
                "bid_at_entry": bid,
                "yes_price_at_entry": o.get("yes_price", bid),
                "spread": spread,
                "shares": round(size / bid, 2),
                "cost": size,
                "p": round(p, 4),
                "ev": round(ev, 4),
                "kelly": round(kelly, 4),
                "forecast_temp": forecast_temp,
                "forecast_src": source,
                "sigma": sigma,
                "gfs_confidence": confidence,
                "trade_reason": f"edge_bucket_{'below' if t_low == -999 else 'above'}",
                "bug_status": "after-bug",
                "opened_at": snap.get("ts"),
                "status": "open",
                "pnl": None,
                "exit_price": None,
                "close_reason": None,
                "closed_at": None,
                "bucket_type": "edge",
            },
            "ev": ev,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["ev"], reverse=True)
    best = candidates[0]
    sig = best["signal"]
    bucket_label = f"{'≤' if sig['bucket_low'] == -999 else '≥'}{sig['bucket_high'] if sig['bucket_low'] == -999 else sig['bucket_low']}{unit_sym}"
    print(f"  [EDGE] {city_name} {date} | {bucket_label} | "
          f"${sig['entry_price']:.3f} | p={sig['p']:.2f} | EV {sig['ev']:+.2f} | "
          f"${sig['cost']:.2f} ({source})")

    if TELEGRAM_ENABLED:
        alert_new_trade(
            city=city_name,
            date=date,
            bucket=bucket_label,
            price=sig['entry_price'],
            ev=sig['ev'],
            cost=sig['cost'],
            source=source
        )

    return best["signal"]


def scan_and_update():
    """Main function of one cycle: updates forecasts, opens/closes positions."""
    global _cal
    now      = datetime.now(timezone.utc)
    state    = load_state()
    balance  = state["balance"]
    new_pos  = 0
    closed   = 0
    resolved = 0

    # Dynamic blocked cities (#12)
    update_dynamic_blocked_cities()
    # City-specific thresholds (#6)
    update_city_thresholds()

    for city_slug, loc in LOCATIONS.items():
        # City filter - skip blocked + dynamically blocked cities
        is_blocked = city_slug in BLOCKED_CITIES or city_slug in DYNAMIC_BLOCKED_CITIES
        if is_blocked:
            if city_slug in DYNAMIC_BLOCKED_CITIES and city_slug not in BLOCKED_CITIES:
                print(f"  -> {loc['name']}... [DYNAMIC BLOCKED] skipped")
            else:
                print(f"  -> {loc['name']}... [BLOCKED] skipped")
            continue
        
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']}...", end=" ", flush=True)

        # Update forecast bias for this city (#11)
        try:
            update_forecast_bias(city_slug)
        except Exception:
            pass  # Non-critical, skip if fails

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
                    yes_price = float(prices[0])
                    no_price = float(prices[1]) if len(prices) > 1 else yes_price
                except Exception:
                    continue
                
                bid = yes_price
                ask = no_price
                
                outcomes.append({
                    "question":  question,
                    "market_id": mid,
                    "range":     rng,
                    "bid":       round(bid, 4),
                    "ask":       round(ask, 4),
                    "price":     round(bid, 4),
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
                # v3.4: multi-model data
                "multi_mean":     snap.get("multi_mean"),
                "multi_spread":   snap.get("multi_spread"),
                "multi_members":  snap.get("multi_members"),
                "multi_temps":    snap.get("multi_temps"),
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
                    stop  = pos.get("stop_price", entry * 0.80)

                    # City-specific stop threshold (#6)
                    city_thresh = CITY_THRESHOLDS.get(city_slug, {})
                    city_stop_pct = city_thresh.get("stop_loss", AUTO_REDEMPTION["stop_loss"])

                    # Trailing: if up 20%+ — move stop to breakeven
                    if current_price >= entry * 1.20 and stop < entry:
                        pos["stop_price"] = entry
                        pos["trailing_activated"] = True

                    # Check stop (#3: skip if hours_left < 4)
                    hours_left = hours
                    if current_price <= stop and hours_left >= 4:
                        pnl = round((current_price - entry) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        pos["closed_at"]    = snap.get("ts")
                        pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
                        pos["exit_price"]   = current_price
                        pos["pnl"]          = pnl
                        pos["status"]       = "closed"
                        # Fix #1: Record actual_temp when closing position
                        try:
                            actual = get_actual_temp(city_slug, date)
                            if actual is not None:
                                mkt["actual_temp"] = actual
                                pos["actual_temp_at_close"] = actual
                        except Exception:
                            pass
                        closed += 1
                        reason = "STOP" if current_price < entry else "TRAILING BE"
                        print(f"  [{reason}] {loc['name']} {date} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")

            # --- CLOSE POSITION if forecast shifted 2+ degrees ---
            if mkt.get("position") and forecast_temp is not None and mkt["position"].get("status") == "open":
                pos = mkt["position"]
                old_bucket_low  = pos["bucket_low"]
                old_bucket_high = pos["bucket_high"]
                unit = loc["unit"]
                buffer = 2.0 if unit == "F" else 1.0
                mid_bucket = (old_bucket_low + old_bucket_high) / 2 if old_bucket_low != -999 and old_bucket_high != 999 else forecast_temp
                forecast_far = abs(forecast_temp - mid_bucket) > (abs(mid_bucket - old_bucket_low) + buffer)
                if not in_bucket(forecast_temp, old_bucket_low, old_bucket_high) and forecast_far and pos.get("status") != "closed":
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
                        # Fix #1: Record actual_temp when closing position
                        try:
                            actual = get_actual_temp(city_slug, date)
                            if actual is not None:
                                mkt["actual_temp"] = actual
                                mkt["position"]["actual_temp_at_close"] = actual
                        except Exception:
                            pass
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
                
                # v3.1 Improvement #3: Apply bias correction before bucket selection
                bias_corrected_temp = forecast_temp
                cal_data = load_cal()
                bias_key = f"{city_slug}_{best_source or 'ecmwf'}"
                if bias_key in cal_data and cal_data[bias_key].get("bias") is not None:
                    bias = cal_data[bias_key]["bias"]
                    if abs(bias) >= 0.5:  # Only correct if bias is significant
                        bias_corrected_temp = round(forecast_temp - bias, 1)
                        forecast_temp = bias_corrected_temp
                        
                # Get GFS ensemble confidence for this date
                confidence = snap.get("gfs_confidence")
                
                # Confidence threshold: require high confidence for opening positions
                min_ev = MIN_EV
                if confidence is not None:
                    if confidence < 0.5:
                        min_ev = MIN_EV * 1.5
                        print(f"  [LOW CONF] {loc['name']} {date}: conf={confidence}, min_ev={min_ev:.2f}")
                
                best_signal = None
                trade_reason = None  # (#10)

                for o in outcomes:
                    t_low, t_high = o["range"]
                    price = o["price"]
                    volume = o["volume"]

                    if not in_bucket(forecast_temp, t_low, t_high):
                        continue

                    # v3.2: Smart filtering — conf<15% reject + edge buckets need conf>=30%
                    bucket_width = t_high - t_low if t_low != -999 and t_high != 999 else 999
                    is_edge_bucket = (t_low == -999 or t_high == 999)
                    is_exact_bucket = (bucket_width == 0)

                    # Reject very low confidence (<15%)
                    if confidence is not None and confidence < 0.15:
                        continue

                    # Edge buckets (≥X or ≤X): require confidence >= 30%
                    if is_edge_bucket and confidence is not None and confidence < 0.30:
                        continue

                    # Exact 1°C buckets: require confidence >= 50%
                    if is_exact_bucket and confidence is not None and confidence < 0.50:
                        continue

                    # v3.4: Multi-model spread filter
                    multi_spread = snap.get("multi_spread") if isinstance(snap, dict) else None
                    if multi_spread is not None:
                        if multi_spread > 5.0:
                            # Models disagree heavily — BLOCK trade
                            continue
                        elif multi_spread > 3.0:
                            # Models moderately disagree — reduce bet 50%
                            # (will be applied later in bet sizing)
                            pass

                    bid    = o.get("bid", o["price"])
                    ask    = o.get("ask", o["price"])
                    spread = o.get("spread", 0)

                    # Slippage filter
                    if spread > MAX_SLIPPAGE:
                        continue
                    if ask >= MAX_PRICE or volume < MIN_VOLUME:
                        continue

                    p  = bucket_prob(forecast_temp, t_low, t_high, sigma)
                    ev = calc_ev(p, ask)
                    if ev < min_ev:
                        continue

                    kelly = calc_kelly(p, ask, confidence)  # (#4) variable Kelly
                    size  = bet_size(kelly, balance, state, confidence)  # (#9) confidence scaling
                    
                    # v3.1 Improvement #5: Reduce bet for low confidence (<60%)
                    if confidence is not None and confidence < 0.60:
                        size = size * 0.5  # Half bet for low confidence
                    
                    # v3.4: Reduce bet if multi-model spread is high (3-5C)
                    multi_spread = snap.get("multi_spread") if isinstance(snap, dict) else None
                    if multi_spread is not None and 3.0 < multi_spread <= 5.0:
                        size = size * 0.5  # Half bet for moderate disagreement
                    
                    # MEGA EDGE ALERT
                    mega_edge = False
                    if ev >= 0.50:
                        mega_edge = True
                        size = min(size * 2.5, MAX_BET * 2)
                        print(f"  [🔥 MEGA EDGE!] {loc['name']} {date} | EV: {ev:.0%} | Size: ${size:.2f}")
                        if TELEGRAM_ENABLED:
                            try:
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
                            except Exception:
                                pass
                    
                    # Determine trade_reason (#10)
                    if mega_edge:
                        trade_reason = "mega_edge"
                    elif confidence is not None and confidence > 0.7:
                        trade_reason = "high_confidence"
                    elif ev >= 0.30:
                        trade_reason = "high_ev"
                    else:
                        # Check if ensemble sources agree
                        ecmwf_val = snap.get("ecmwf")
                        hrrr_val = snap.get("hrrr")
                        if ecmwf_val is not None and hrrr_val is not None:
                            if abs(ecmwf_val - hrrr_val) < 2.0:
                                trade_reason = "ensemble_agreement"
                            else:
                                trade_reason = "high_ev"
                        else:
                            trade_reason = "high_ev"
                    
                    if size < 0.50:
                        continue

                    best_signal = {
                        "market_id":    o["market_id"],
                        "question":     o["question"],
                        "bucket_low":   t_low,
                        "bucket_high":  t_high,
                        "entry_price":  bid,
                        "bid_at_entry": bid,
                        "yes_price_at_entry": o.get("yes_price", bid),
                        "spread":       spread,
                        "shares":       round(size / bid, 2),
                        "cost":         size,
                        "p":            round(p, 4),
                        "ev":           round(ev, 4),
                        "kelly":        round(kelly, 4),
                        "forecast_temp":forecast_temp,
                        "forecast_src": best_source,
                        "sigma":        sigma,
                        "gfs_confidence": confidence,
                        "trade_reason": trade_reason,  # (#10)
                        "bug_status":   "after-bug",
                        "opened_at":    snap.get("ts"),
                        "status":       "open",
                        "pnl":          None,
                        "exit_price":   None,
                        "close_reason": None,
                        "closed_at":    None,
                        "bucket_type":  "exact",
                    }
                    break

                # --- EDGE BUCKET FALLBACK ---
                if not best_signal:
                    best_signal = find_edge_signal(
                        outcomes, forecast_temp, best_source, sigma, confidence,
                        balance, state, unit_sym, loc['name'], date, snap
                    )

                if best_signal:
                    balance -= best_signal["cost"]
                    mkt["position"] = best_signal
                    state["total_trades"] += 1
                    new_pos += 1
                    bucket_label = f"{best_signal['bucket_low']}-{best_signal['bucket_high']}{unit_sym}"
                    reason_tag = f" [{best_signal['trade_reason']}]" if best_signal.get('trade_reason') else ""
                    print(f"  [BUY]  {loc['name']} {horizon} {date} | {bucket_label} | "
                          f"${best_signal['entry_price']:.3f} | EV {best_signal['ev']:+.2f} | "
                          f"${best_signal['cost']:.2f} ({best_signal['forecast_src'].upper()}){reason_tag}")
                    
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
        if not pos or pos.get("status") not in ("open", "closed"):
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

        # Try to get actual temp for resolved market
        if mkt.get("actual_temp") is None:
            try:
                actual = get_actual_temp(mkt["city"], mkt["date"])
                if actual is not None:
                    mkt["actual_temp"] = actual
            except Exception:
                pass

        if won:
            state["wins"] += 1
            if AUTO_REINVEST.get("enabled", False):
                profit = pnl
                reinvest_amount = profit * AUTO_REINVEST.get("fraction", 0.25)
                state["realized_profits"] = state.get("realized_profits", 0.0) + reinvest_amount
        else:
            state["losses"] += 1

        result = "WIN" if won else "LOSS"
        print(f"  [{result}] {mkt['city_name']} {mkt['date']} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
        resolved += 1
        
        # Telegram Alert: Trade Resolved
        if TELEGRAM_ENABLED:
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
    print(f"  WEATHERBET v3.0 — STATUS")
    print(f"{'='*55}")
    print(f"  Balance:     ${bal:,.2f}  (start ${start:,.2f}, {'+'if ret_pct>=0 else ''}{ret_pct:.1f}%)")
    print(f"  Trades:      {total} | W: {wins} | L: {losses} | WR: {wins/total:.0%}" if total else "  No trades yet")
    print(f"  Open:        {len(open_pos)}")
    print(f"  Resolved:    {len(resolved)}")
    
    # Show dynamic blocked cities (#12)
    if DYNAMIC_BLOCKED_CITIES:
        blocked_names = [LOCATIONS.get(c, {}).get("name", c) for c in DYNAMIC_BLOCKED_CITIES if c not in BLOCKED_CITIES]
        if blocked_names:
            print(f"  Dyn Blocked: {', '.join(blocked_names)}")

    if open_pos:
        print(f"\n  Open positions:")
        total_unrealized = 0.0
        for m in open_pos:
            pos      = m["position"]
            unit_sym = "F" if m["unit"] == "F" else "C"
            label    = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"

            current_price = pos["entry_price"]
            snaps = m.get("market_snapshots", [])
            if snaps:
                for o in m.get("all_outcomes", []):
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

            unrealized = round((current_price - pos["entry_price"]) * pos["shares"], 2)
            total_unrealized += unrealized
            pnl_str = f"{'+'if unrealized>=0 else ''}{unrealized:.2f}"
            reason_tag = f" [{pos.get('trade_reason', '?')}]" if pos.get('trade_reason') else ""

            print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | "
                  f"entry ${pos['entry_price']:.3f} -> ${current_price:.3f} | "
                  f"PnL: {pnl_str} | {pos['forecast_src'].upper()}{reason_tag}")

        sign = "+" if total_unrealized >= 0 else ""
        print(f"\n  Unrealized PnL: {sign}{total_unrealized:.2f}")

    print(f"{'='*55}\n")

def print_report():
    markets  = load_all_markets()
    resolved = [m for m in markets if m["status"] == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET v3.0 — FULL REPORT")
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
        print(f"\n  CALIBRATION (Price-Adjusted Brier Score):")
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

    # Dynamic Blocked Cities (#12)
    if DYNAMIC_BLOCKED_CITIES:
        print(f"\n  DYNAMIC BLOCKED CITIES:")
        for city in sorted(DYNAMIC_BLOCKED_CITIES):
            if city not in BLOCKED_CITIES:
                avg_brier = sum(get_brier_score(city, s) for s in ["ecmwf", "hrrr"]) / 2
                print(f"    {LOCATIONS[city]['name']:<16} Brier: {avg_brier:.4f}")

    # City Thresholds (#6)
    if CITY_THRESHOLDS:
        print(f"\n  CITY-SPECIFIC THRESHOLDS:")
        print(f"  {'City':<16} {'Stop Loss':<12} {'Sigma':<8}")
        print(f"  {'-'*40}")
        for city in sorted(CITY_THRESHOLDS.keys()):
            t = CITY_THRESHOLDS[city]
            print(f"  {LOCATIONS[city]['name']:<16} {t['stop_loss']:<12.3f} {t['sigma']:<8.3f}")

    if not resolved:
        print(f"{'='*55}\n")
        return

    # Bug Check
    print(f"\n  BUG CHECK (Entry Price Validation):")
    print(f"  {'City':<16} {'Forecast':<10} {'Bucket':<12} {'Entry':<8} {'Expected'}")
    print(f"  {'-'*60}")
    bugs_found = 0
    for m in resolved:
        pos = m.get("position", {})
        forecast = pos.get("forecast_temp")
        entry = pos.get("entry_price", 0)
        bucket = f"{pos.get('bucket_low', 'N/A')}-{pos.get('bucket_high', 'N/A')}"
        
        if forecast and entry:
            t_low, t_high = pos.get("bucket_low", -999), pos.get("bucket_high", 999)
            fc_in_bucket = t_low <= forecast <= t_high
            expected_high = fc_in_bucket
            actual_high = entry > 0.5
            
            if expected_high != actual_high:
                status = "🔴 BUG"
                bugs_found += 1
            else:
                status = "🟢 OK"
            
            print(f"  {LOCATIONS.get(m['city'], {}).get('name', m['city']):<16} {forecast:<10.1f} {bucket:<12} {entry:<8.3f} {status}")
    
    if bugs_found > 0:
        print(f"\n  ⚠️  Found {bugs_found} potential bugs in entry pricing!")
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
        reason   = pos.get("trade_reason", "")
        reason_tag = f" [{reason}]" if reason else ""
        print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | {fc_str} | {actual} | {result} {pnl_str}{reason_tag}")

    print(f"{'='*55}\n")

# =============================================================================
# MAIN LOOP
# =============================================================================

MONITOR_INTERVAL = 600  # monitor positions every 10 minutes

def check_auto_redemption(mkt, pos, current_price, hours_left=None):
    """Check if position should be auto-redeemed based on Option B criteria.
    
    v3.0 (#3): If hours_left < 4, disable stop-loss (let market resolve naturally).
    v3.0 (#6): Uses city-specific thresholds.
    """
    if not AUTO_REDEMPTION.get("enabled", False):
        return None
    
    entry = pos["entry_price"]
    shares = pos["shares"]
    cost = pos["cost"]
    pnl_pct = (current_price - entry) / entry
    
    # Check min hold time
    bucket_type = pos.get("bucket_type", "exact")
    min_hold = 6 if bucket_type == "edge" else AUTO_REDEMPTION["min_hold_hours"]
    opened_str = pos.get("opened_at", "")
    if opened_str:
        try:
            opened = datetime.fromisoformat(opened_str.replace("Z", "+00:00"))
            hours_held = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            if hours_held < min_hold:
                return None  # Too new, skip
        except:
            pass
    
    # (#3) If hours_left < 4, disable stop-loss — let market resolve naturally
    if hours_left is not None and hours_left < 4:
        # Only allow profit-taking, no stop-loss
        pass
    else:
        # City-specific stop threshold (#6)
        city_slug = mkt.get("city", "")
        city_thresh = CITY_THRESHOLDS.get(city_slug, {})
        effective_stop = city_thresh.get("stop_loss", AUTO_REDEMPTION["stop_loss"])
        if bucket_type == "edge":
            effective_stop = -0.25  # Wider stop for edge buckets
        
        # Criterion 4: P&L < stop threshold → Stop loss
        if pnl_pct <= effective_stop:
            return {
                "action": "stop_loss",
                "reason": f"AUTO: P&L {pnl_pct*100:.0f}% < {effective_stop*100:.0f}%",
                "pct": 1.0,
                "pnl_pct": pnl_pct * 100
            }
    
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
                current_price = o.get("bid", o["price"])
                break

        if current_price is None:
            continue

        entry = pos["entry_price"]
        stop  = pos.get("stop_price", entry * 0.80)
        
        # Calculate hours_left for this position (#3)
        end_date = mkt.get("event_end_date", "")
        hours_left = hours_to_resolution(end_date) if end_date else 999.0

        # Trailing: if up 20%+ — move stop to breakeven
        if current_price >= entry * 1.20 and stop < entry:
            pos["stop_price"] = entry
            pos["trailing_activated"] = True
            city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
            print(f"  [TRAILING] {city_name} {mkt['date']} — stop moved to breakeven ${entry:.3f}")

        # Check stop (#3: only if hours_left >= 4)
        if current_price <= stop and hours_left >= 4:
            pnl = round((current_price - entry) * pos["shares"], 2)
            balance += pos["cost"] + pnl
            pos["closed_at"]    = datetime.now(timezone.utc).isoformat()
            pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
            pos["exit_price"]   = current_price
            pos["pnl"]          = pnl
            pos["status"]       = "closed"
            # Fix #1: Record actual_temp when closing position
            try:
                actual = get_actual_temp(mkt["city"], mkt["date"])
                if actual is not None:
                    mkt["actual_temp"] = actual
                    pos["actual_temp_at_close"] = actual
            except Exception:
                pass
            closed += 1
            reason = "STOP" if current_price < entry else "TRAILING BE"
            city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])
            print(f"  [{reason}] {city_name} {mkt['date']} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl>=0 else ''}{pnl:.2f}")
            save_market(mkt)
            continue
        
        # Auto-Redemption Check (with hours_left #3)
        auto_action = check_auto_redemption(mkt, pos, current_price, hours_left)
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
                # Fix #1: Record actual_temp when closing position
                try:
                    actual = get_actual_temp(mkt["city"], mkt["date"])
                    if actual is not None:
                        mkt["actual_temp"] = actual
                        pos["actual_temp_at_close"] = actual
                except Exception:
                    pass
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

    # Initialize city thresholds and dynamic blocking
    update_city_thresholds()
    update_dynamic_blocked_cities()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET v3.0 — STARTING")
    print(f"{'='*55}")
    print(f"  Cities:     {len(LOCATIONS)}")
    print(f"  Balance:    ${BALANCE:,.0f} | Max bet: ${MAX_BET}")
    print(f"  Scan:       {SLOW_SCAN_INTERVAL//60} min (adaptive) | Monitor: {MONITOR_INTERVAL//60} min")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0) + Weighted Ensemble")
    print(f"  Data:       {DATA_DIR.resolve()}")
    print(f"  Ctrl+C to stop\n")

    # Telegram Alert: Bot Started
    if TELEGRAM_ENABLED:
        alert_bot_started()

    last_full_scan = 0

    while True:
        now_ts  = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Adaptive scan interval (#8)
        effective_scan = SLOW_SCAN_INTERVAL
        if ADAPTIVE_SCAN:
            markets = load_all_markets()
            open_positions = [m for m in markets if m.get("position") and m["position"].get("status") == "open"]
            for m in open_positions:
                end_date = m.get("event_end_date", "")
                if end_date:
                    hrs = hours_to_resolution(end_date)
                    if hrs < 6:
                        effective_scan = FAST_SCAN_INTERVAL
                        break

        # Full scan
        if now_ts - last_full_scan >= effective_scan:
            print(f"[{now_str}] full scan (interval: {effective_scan//60}min)...")
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
        update_city_thresholds()
        update_dynamic_blocked_cities()
        print_status()
    elif cmd == "report":
        _cal = load_cal()
        update_city_thresholds()
        update_dynamic_blocked_cities()
        print_report()
    else:
        print("Usage: python bot_v3.py [run|status|report]")

# Changelog - Tempo-Bet

All notable changes to this project will be documented in this file.

## [v3.1] - 2026-04-12

### Added
- **Edge Bucket Fallback** — bot now tries edge buckets (≤X or ≥X) when no exact bucket qualifies
  - Uses normal CDF for continuous probability estimation (much better than binary 0/1)
  - Relaxed filters: max spread 10% (vs 3%), max price $0.75 (vs $0.65), min EV 5% (vs 10%)
  - Conservative sizing: 60% of normal bet size
  - Wider stop-loss: -25% (vs -15%) and min hold 6h (vs 4h)
  - Marked with `bucket_type: "edge"` in position dict
- Added `bucket_type: "exact"` to existing exact bucket positions for clarity

---

## [3.0] - 2026-04-12

### Added — 12 Improvements for Accuracy and P&L

- **#1: Record actual_temp when closing positions (CRITICAL)**
  - Stop-loss, trailing stop, and forecast-change closures now fetch and store actual temperature
  - Provides more calibration data instead of wasting it only on resolved markets
- **#2: Price-adjusted Brier Score**
  - New formula: `brier = ((p × price) - actual_outcome)²`
  - Reflects actual confidence-adjusted prediction quality
- **#3: Time-aware stop-loss**
  - If market resolves in < 4 hours, stop-loss is disabled (let it resolve naturally)
  - Prevents selling positions that might still win
- **#4: Variable Kelly fraction**
  - High confidence (>0.7): Kelly 50%
  - Medium (0.4–0.7): Kelly 30%
  - Low (<0.4): Kelly 15%
  - `calc_kelly()` now accepts a `confidence` parameter
- **#5: Weighted ensemble forecast**
  - Instead of picking HRRR or ECMWF, uses weighted average based on Brier score
  - Weight formula: `w = 1 / (brier + 0.01)` normalized
  - New function: `get_weighted_forecast()`
- **#6: City-specific auto-redemption thresholds**
  - Per-city stop-loss based on historical sigma (volatility)
  - Formula: `stop_loss = base_stop × (1 + sigma/2)`
  - Volatile cities get wider stops
- **#7: Brier-optimized sigma calibration**
  - Grid search from 0.5 to 5.0 (steps of 0.1) to find optimal sigma per city/source
  - Replaces simple MAE-based sigma
- **#8: Adaptive scan interval**
  - 15 min when positions have < 6h to resolution, 30 min otherwise
  - Configurable via `fast_scan_interval` and `slow_scan_interval`
- **#9: GFS confidence affects bet size**
  - confidence < 0.3: bet × 0.25
  - confidence < 0.5: bet × 0.5
  - confidence > 0.8: bet × 1.25
- **#10: Trade reason tracking**
  - Every position records why it was opened: `high_ev`, `high_confidence`, `mega_edge`, `ensemble_agreement`
  - Visible in status and report output
- **#11: METAR bias correction**
  - Compares METAR observations with forecasts to detect systematic bias per city
  - Applies correction: `corrected_forecast = forecast - bias`
  - New functions: `calc_forecast_bias()`, `apply_bias_correction()`, `update_forecast_bias()`
- **#12: Dynamic blocked cities**
  - Auto-blocks cities with Brier > 0.35 (after 5+ resolved markets)
  - Auto-unblocks if Brier improves to < 0.25
  - Replaces hardcoded-only blocking

### Changed
- Version string updated from `bot_v2.py` to `bot_v3.0`
- `config.json` now includes `fast_scan_interval`, `slow_scan_interval`, `adaptive_scan`
- CLI usage: `python bot_v3.py [run|status|report]`

---

## [Unreleased] - 2026-03-22

### Added
- **Auto-Reinvestment System (Conservative - 25%)**
  - Automatically reinvests 25% of profits into next trades
  - Configurable modes: off, conservative (25%), moderate (50%), aggressive (100%)
  - Min/max balance limits for risk control
  - `realized_profits` tracking in state
- **Auto-Redemption System (Option B)**
  - Automated profit-taking based on configurable thresholds
  - Criteria:
    - Price > $0.99 → Sell 100%
    - P&L > 500% → Sell 75%
    - Price > $0.95 AND P&L > 100% → Sell 50%
    - P&L < -20% → Stop Loss
  - Configurable min hold time (default: 6 hours)
  - Partial and full close support
- **MEGA EDGE Alert**
  - Telegram alert when EV > 50%
  - 2.5x bet size boost for high-confidence opportunities

### Changed
- **bet_size()** - Now supports auto-reinvestment parameter
- **state.json** - Added `realized_profits` field

---

## [1.1] - 2026-03-21

### Added
- **Model Ensemble + Confidence Score**
  - Multi-model forecasting (ECMWF + GFS)
  - Confidence score based on model agreement
  - Low confidence filter (increases EV requirement)
  - New function: `get_model_ensemble()`
- **Brier Score Calibration**
  - Measures prediction quality per source/city
  - Brier Score = mean((predicted_prob - actual)²)
  - Lower is better (0 = perfect, 1 = worst)
  - Quality indicators: 🟢 Excellent, 🟡 Good, 🟠 Fair, 🔴 Poor
- **Telegram Alerts**
  - `telegram_alerts.py` - Alert system
  - Alerts for: Bot start, New trade, Trade closed, Trade resolved
  - Real-time notifications via Telegram Bot
- **GitHub Security Audit Module**
  - `github_security_audit.py` - Analyzes repos before clone/pull

### Changed
- **EV Threshold** - Dynamically adjusted by confidence
  - Normal: 0.05 (5%)
  - Low confidence (<0.5): 0.08 (8%)

---

## [1.0] - 2026-03-21

### Added
- Initial fork from weatherbot by Ezekiel Njuguna
- 20 cities supported (US, Europe, Asia, South America)
- ECMWF + HRRR + METAR forecasting
- Kelly Criterion position sizing
- Paper trading mode
- Polymarket Gamma API integration
- Visual Crossing for actual temperature resolution

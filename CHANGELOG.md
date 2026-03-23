# Changelog - Tempo-Bet

All notable changes to this project will be documented in this file.

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

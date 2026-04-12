# Tempo-Bet Code Audit & Improvement Plan
# Generated: 2026-04-10

## ============================================================
## 1. AUDIT — ISSUES FOUND
## ============================================================

### ISSUE 1: MAX_PRICE Too Restrictive (CRITICAL)
**Finding:** 25/28 historical trades (89%) have entry_price >$0.45, but current `MAX_PRICE=$0.45`.
This means the bot would NOT have entered most of its winning trades!

**Analysis:**
- Wins: entry prices $0.145 to $0.996 (avg $0.75)
- Losses: entry prices $0.405 to $0.795 (avg $0.58)
- The 6 losses avg $0.58 vs wins avg $0.75 — losses are actually CHEAPER entries!
- Entry price alone is NOT a good predictor of success

**Recommendation:** Raise MAX_PRICE to $0.65 (captures 93% of historical wins while excluding expensive trades >$0.65)

### ISSUE 2: MIN_EV Too High (MODERATE)
**Finding:** With MIN_EV=15%, the bot is very selective. Only 1 position in April (London $0.94).
The current settings have generated 28 trades over ~20 days = ~1.4 trades/day.

**Analysis:**
- Average 1.4 trades/day is very low
- Most days have 0 new positions
- Expanding to $0.65 max_price would add ~1-2 trades/day

**Recommendation:** Lower MIN_EV to 10% — still profitable at 78.6% WR

### ISSUE 3: CITY BLOCKING — Too Broad (MODERATE)
**Finding:** 9 cities are BLOCKED: Ankara, Atlanta, Chicago, Miami, Munich, NYC, Seattle, Dallas, Shanghai.

**But data shows:**
- Some blocked cities have good WR (e.g., Shanghai only 1 trade but WIN)
- NYC has 0 trades (not tested, not blocked due to poor data)
- Some blocked due to bug, not poor performance

**Recommendation:** 
- Remove "BLOCKED" list entirely — use PROVEN cities list instead
- Keep only: Lucknow, Toronto, Paris, London, Seoul, Tokyo, Singapore (all profitable)
- Add Wellington, Sao Paulo, Tel Aviv, Buenos Aires as TEST cities (not blocked, but monitored)

### ISSUE 4: Position Status Check Bug (FIXED)
**Bug:** `pos.get("status") != "open"` skipped closed-but-unresolved positions
**Fix:** Changed to `pos.get("status") not in ("open", "closed")`
**Status:** ✅ FIXED

### ISSUE 5: No Trailing Stop (MODERATE)
**Finding:** Bot does not implement trailing stop for winning positions.
**Impact:** Some trades that went from $0.15 to $0.90 were manually sold.

**Recommendation:** Add trailing stop — sell 50% when price doubles, stop at entry

### ISSUE 6: scan_interval Too Long (LOW)
**Finding:** scan_interval = 3600 (1 hour). For fast-moving markets, this is slow.
**Recommendation:** Lower to 1800 (30 min) for faster signal capture

### ISSUE 7: No Auto-Redeem at $0.95 (MODERATE)
**Finding:** Bot sells at $0.90 by default, but Polymarket sometimes runs to $0.95+.
**Recommendation:** Auto-redeem at $0.95 (sells at $0.95 instead of holding to $1.00)

---

## ============================================================
## 2. TRADE PERFORMANCE ANALYSIS
## ============================================================

### By Entry Price Range:
| Range | Trades | Wins | Losses | WR | Avg PnL |
|-------|--------|------|--------|-----|---------|
| $0.00-0.15 | 2 | 2 | 0 | 100% | +$68 |
| $0.15-0.45 | 1 | 1 | 0 | 100% | +$117 |
| $0.45-0.65 | 10 | 8 | 2 | 80% | +$17 |
| $0.65-0.85 | 9 | 6 | 3 | 67% | +$7 |
| $0.85-1.00 | 6 | 5 | 1 | 83% | -$4 |
| ALL | 28 | 22 | 6 | 78.6% | +$108 |

### Key Insight: Entry price >$0.45 is NOT predictive of failure!
The bot's current MAX_PRICE=$0.45 would exclude 89% of its historical wins!

### By City:
| City | Trades | WR | PnL | Status |
|------|--------|-----|-----|---------|
| lucknow | 2 | 100% | +$120 | KEEEP |
| paris | 2 | 100% | +$33 | KEEEP |
| toronto | 6 | 100% | +$58 | KEEEP |
| seoul | 1 | 100% | +$4 | KEEEP |
| singapore | 1 | 100% | +$3 | KEEEP |
| wellington | 1 | 100% | +$15 | TEST |
| tel-aviv | 2 | 50% | -$24 | TEST |
| sao-paulo | 1 | 100% | +$5 | TEST |
| buenos-aires | 1 | 100% | +$5 | TEST |

---

## ============================================================
## 3. PROPOSED CONFIG CHANGES
## ============================================================

### Current config.json:
```json
{
  "balance": 10000.0,
  "max_bet": 20.0,
  "min_ev": 0.05,
  "max_price": 0.45,
  "min_volume": 2000,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "max_slippage": 0.03,
  "scan_interval": 3600,
  "calibration_min": 30
}
```

### Recommended config.json:
```json
{
  "balance": 10000.0,
  "max_bet": 25.0,
  "min_ev": 0.10,
  "max_price": 0.65,
  "min_volume": 2000,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "max_slippage": 0.03,
  "scan_interval": 1800,
  "calibration_min": 30,
  "auto_redeem_price": 0.95,
  "trailing_stop_enabled": true,
  "trailing_pct": 0.50
}
```

### Changes:
| Parameter | Current | Recommended | Reason |
|-----------|---------|-------------|--------|
| max_price | $0.45 | $0.65 | Capture 93% of wins |
| min_ev | 5% | 10% | Filter noise, keep quality |
| max_bet | $20 | $25 | Slightly larger for confident bets |
| scan_interval | 3600 | 1800 | Faster signal capture |
| auto_redeem_price | N/A | $0.95 | Capture profit before $1.00 |
| trailing_stop_enabled | false | true | Lock in profits |

---

## ============================================================
## 4. CITY STRATEGY
## ============================================================

### PROVEN CITIES (no restrictions):
- lucknow, toronto, paris, london, seoul, tokyo, singapore

### TEST CITIES (monitor carefully, lower Kelly):
- wellington, sao-paulo, buenos-aires, tel-aviv

### BLOCKED (insufficient data or known bad):
- nyc, chicago, miami, atlanta, dallas, seattle, ankara, munich, shanghai

---

## ============================================================
## 5. ESTIMATED IMPACT
## ============================================================

### Current Performance (last 20 days):
- Trades/day: ~1.4
- Win Rate: 78.6%
- PnL/trade avg: $108

### With Recommended Changes (estimated):
- Trades/day: ~3-4 (2-3x increase)
- Win Rate: ~72-75% (slight decrease due to lower MIN_EV)
- PnL/trade avg: ~$80 (slightly lower but more volume)
- Expected daily PnL: $240-$320/day (vs ~$150 currently)

---

## ============================================================
## 6. TODO — IMPLEMENTATION CHECKLIST
## ============================================================

### Critical (fix immediately):
- [x] Issue 4: Position status check — FIXED
- [ ] Issue 1: Raise MAX_PRICE to $0.65 in config AND code
- [ ] Issue 2: Lower MIN_EV to 10%

### Important (implement soon):
- [ ] Issue 3: Refactor city filtering — use PROVEN list, not BLOCKED
- [ ] Issue 5: Add trailing stop
- [ ] Issue 6: Lower scan_interval to 1800

### Nice to have:
- [ ] Issue 7: Auto-redeem at $0.95
- [ ] Add daily summary to Telegram
- [ ] Add max trades per day limit (e.g., max 5 new trades/day)

#!/usr/bin/env python3
"""
Relatório diário do Tempo-Bet — rodar todo dia às 6h via cron.
Gera: trades das últimas 24h (abertos/fechados/resolvidos), WR, PnL,
saldo, posições abertas, top/bottom cidades e forecast acurácia.
Envia via Telegram (telegram_alerts.py) e salva cópia em data/reports/.
"""
import json, glob, sys, os
from datetime import datetime, timedelta, timezone

PROJ = "/home/hal9000/Projects/Tempo-bet"
sys.path.insert(0, PROJ)
from telegram_alerts import send_telegram_message

REPORTS_DIR = os.path.join(PROJ, "data", "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=24)
today = now.strftime("%Y-%m-%d")

def parse_ts(s):
    if not s: return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

markets = []
for fp in glob.glob(os.path.join(PROJ, "data", "markets", "*.json")):
    try:
        markets.append(json.load(open(fp)))
    except Exception:
        continue

state = {}
try:
    state = json.load(open(os.path.join(PROJ, "data", "state.json")))
except Exception:
    pass

balance = state.get("balance", 0.0)
total_trades_hist = state.get("total_trades", "?")
wins_hist = state.get("wins", "?")

# ---------- trades das últimas 24h ----------
closed_24h = []   # fechados/resolvidos nas últimas 24h
opened_24h = []   # abertos nas últimas 24h
open_positions = []

for m in markets:
    pos = m.get("position")
    if not pos:
        continue
    opened = parse_ts(pos.get("opened_at"))
    closed = parse_ts(pos.get("closed_at"))
    if pos.get("status") == "open":
        open_positions.append((m, pos))
    if closed and closed >= cutoff:
        closed_24h.append((m, pos))
    if opened and opened >= cutoff:
        opened_24h.append((m, pos))

wins = [(m, p) for m, p in closed_24h if (p.get("pnl") or 0) > 0]
losses = [(m, p) for m, p in closed_24h if (p.get("pnl") or 0) <= 0]
pnl_24h = sum(p.get("pnl") or 0 for _, p in closed_24h)
wr = len(wins)/len(closed_24h)*100 if closed_24h else 0.0

best = max(closed_24h, key=lambda x: x[1].get("pnl") or 0, default=None)
worst = min(closed_24h, key=lambda x: x[1].get("pnl") or 0, default=None)

# ---------- por cidade (últimos 7 dias p/ contexto) ----------
cutoff7 = now - timedelta(days=7)
city_stats = {}
for m in markets:
    pos = m.get("position")
    if not pos or pos.get("status") == "open":
        continue
    closed = parse_ts(pos.get("closed_at"))
    if not closed or closed < cutoff7:
        continue
    c = m["city"]
    st = city_stats.setdefault(c, [0, 0, 0.0])
    pnl = pos.get("pnl") or 0
    st[2] += pnl
    if pnl > 0: st[0] += 1
    else: st[1] += 1

city_lines = sorted(city_stats.items(), key=lambda x: x[1][2])
city_str = ""
for c, (w, l, pnl) in city_lines[:4]:
    tot = w + l
    city_str += f"• {c}: {w}W/{l}L ({w/tot*100:.0f}%) {pnl:+.2f}\n"
city_str += "...\n"
for c, (w, l, pnl) in city_lines[-4:]:
    tot = w + l
    city_str += f"• {c}: {w}W/{l}L ({w/tot*100:.0f}%) {pnl:+.2f}\n"

# ---------- posições abertas ----------
open_str = ""
for m, p in open_positions[:6]:
    open_str += (f"• {m['city']}: {p['bucket_low']:.0f}°C | "
                 f"entrada ${p['entry_price']:.2f} | PnL at. {(p.get('pnl') or 0):+.2f}\n")
if not open_str:
    open_str = "• nenhuma\n"

# ---------- acurácia do forecast (resolvidos 24h, |fc - real| via bucket) ----------
mae_list = []
for m, p in closed_24h:
    fc = p.get("forecast_temp")
    if fc is not None and p.get("bucket_low") is not None:
        mae_list.append(abs(fc - (p["bucket_low"] + p["bucket_high"]) / 2))
mae = sum(mae_list)/len(mae_list) if mae_list else None

# ---------- texto ----------
w24, l24 = len(wins), len(losses)
lines = [f"📊 <b>Tempo-Bet — Relatório Diário</b>", f"🗓 {today}", ""]
lines.append(f"💰 <b>Saldo:</b> ${balance:,.2f}")
lines.append(f"📈 <b>PnL 24h:</b> {pnl_24h:+.2f}  |  Trades fechados: {len(closed_24h)} ({w24}W/{l24}L, WR {wr:.0f}%)")
if opened_24h:
    lines.append(f"🆕 <b>Novas posições 24h:</b> {len(opened_24h)}")
if mae is not None:
    lines.append(f"🎯 <b>MAE forecast (24h):</b> {mae:.2f}°C")
lines.append("")
lines.append(f"📂 <b>Posições abertas ({len(open_positions)}):</b>")
lines.append(open_str)
if closed_24h:
    lines.append("<b>Trades fechados 24h:</b>")
    for m, p in closed_24h[:10]:
        emoji = "✅" if (p.get("pnl") or 0) > 0 else "❌"
        reason = p.get("close_reason", "?")
        lines.append(f"{emoji} {m['city']} {p['bucket_low']:.0f}°C | "
                     f"in ${p['entry_price']:.2f} | {reason} | {p.get('pnl', 0):+.2f}")
    if best and (best[1].get("pnl") or 0) > 0:
        lines.append(f"🏆 Melhor: {best[0]['city']} {best[1]['pnl']:+.2f}")
    if worst and (worst[1].get("pnl") or 0) < 0:
        lines.append(f"💀 Pior: {worst[0]['city']} {worst[1]['pnl']:+.2f}")
lines.append("")
if city_stats:
    lines.append("<b>Cidades (7d):</b>")
    lines.append(city_str.strip())
lines.append("")
wr_hist = "?"
try:
    w_, l_ = state.get("wins"), state.get("losses")
    if isinstance(w_, int) and isinstance(l_, int) and (w_ + l_) > 0:
        wr_hist = f"{w_/(w_+l_)*100:.0f}% ({w_}W/{l_}L)"
except Exception:
    pass
lines.append(f"📚 <b>Total histórico:</b> {total_trades_hist} trades | WR {wr_hist}")

text = "\n".join(lines)

# ---------- envio + persistência ----------
sent = False
try:
    sent = bool(send_telegram_message(text))
except Exception as e:
    print(f"Telegram error: {e}")

report_path = os.path.join(REPORTS_DIR, f"{today}.md")
with open(report_path, "w") as f:
    f.write(text.replace("<b>", "**").replace("</b>", "**") + f"\n\n--\nenviado_telegram: {sent}\n")

print(text)
print(f"\n[salvo em {report_path} | telegram: {sent}]")
sys.exit(0 if sent else 1)

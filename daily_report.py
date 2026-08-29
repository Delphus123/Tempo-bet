#!/usr/bin/env python3
"""daily_report.py — Relatório diário do Tempo-bet (roda 06:00 via cron).

Métricas:
- Entradas (apostas abertas) nas últimas 24h
- Número de apostas e percentual de acertividade (resoluções nas últimas 24h)
- Médias da última semana (apostas/dia, acertividade 7d, P&L 7d)
Envia via Telegram (telegram_alerts) e salva em data/reports/.
"""
import json
import glob
import os
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
MARKETS = os.path.join(BASE, "data", "markets")
REPORTS = os.path.join(BASE, "data", "reports")
STATE = os.path.join(BASE, "data", "state.json")
os.makedirs(REPORTS, exist_ok=True)

BRL = None  # não usado, reservado


def load_state():
    try:
        with open(STATE) as fp:
            return json.load(fp)
    except Exception:
        return {}


def trade_summary(m, fname):
    pos = m.get("position") or {}
    return {
        "file": fname,
        "city": m.get("city") or fname.split("_")[0],
        "date": m.get("date") or fname.split("_", 1)[1].replace(".json", "") if "_" in fname else "?",
        "bucket": pos.get("bucket_low"),
        "entry_price": pos.get("entry_price"),
        "cost": pos.get("cost"),
        "opened_at": pos.get("opened_at"),
        "status": m.get("status"),
        "p": pos.get("p"),
        "ev": pos.get("ev"),
    }


def main():
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    entries_24h, resolved_24h, wins_24h, pnl_24h = [], 0, 0, 0.0
    entries_7d, resolved_7d, wins_7d, pnl_7d = 0, 0, 0, 0.0
    open_positions = []

    for f in glob.glob(os.path.join(MARKETS, "*.json")):
        fname = os.path.basename(f)
        try:
            with open(f) as fp:
                m = json.load(fp)
        except Exception:
            continue
        pos = m.get("position")
        status = m.get("status")
        if pos:
            opened = pos.get("opened_at")
            opened_dt = None
            if opened:
                try:
                    opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
                except Exception:
                    opened_dt = None
            if opened_dt and opened_dt >= cutoff_24h:
                entries_24h.append(trade_summary(m, fname))
            if opened_dt and opened_dt >= cutoff_7d:
                entries_7d += 1
            if status == "open":
                open_positions.append(trade_summary(m, fname))
        if status == "resolved":
            # data de resolução: usar mtime como aproximação se não houver campo
            resolved_field = m.get("resolved_at") or pos.get("resolved_at") if pos else None
            if resolved_field:
                try:
                    rdt = datetime.fromisoformat(resolved_field.replace("Z", "+00:00"))
                except Exception:
                    rdt = None
            else:
                rdt = datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc)
            actual = m.get("actual_temp")
            won = None
            if pos and actual is not None:
                lo = pos.get("bucket_low")
                hi = pos.get("bucket_high", lo)
                if lo is not None:
                    won = (lo <= actual <= hi)
            pnl = 0.0
            if pos and won is not None:
                entry = pos.get("entry_price") or 0
                cost = pos.get("cost") or 0
                pnl = (cost / entry - cost) if won else -cost
            if rdt and rdt >= cutoff_24h:
                resolved_24h += 1
                if won:
                    wins_24h += 1
                pnl_24h += pnl
            if rdt and rdt >= cutoff_7d:
                resolved_7d += 1
                if won:
                    wins_7d += 1
                pnl_7d += pnl

    def pct(w, r):
        return f"{100.0 * w / r:.0f}%" if r else "—"

    state = load_state()
    saldo = state.get("balance")

    lines = []
    lines.append("📊 *TEMPO-BET — RELATÓRIO DIÁRIO*")
    lines.append(f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_")
    lines.append("")
    if saldo is not None:
        lines.append(f"💰 Saldo: ${saldo:,.2f}")
        lines.append("")
    lines.append("🆕 *Últimas 24h*")
    lines.append(f"• Entradas: {len(entries_24h)}")
    for t in entries_24h:
        lines.append(f"  ▸ {t['city'].title()} {t['date']} | bucket {t['bucket']}°C @ ${t['entry_price']} (${t['cost']})")
    lines.append(f"• Resoluções: {resolved_24h} | Acertos: {wins_24h} ({pct(wins_24h, resolved_24h)})")
    lines.append(f"• P&L resolvido 24h: ${pnl_24h:+.2f}")
    lines.append("")
    lines.append("📈 *Últimos 7 dias*")
    lines.append(f"• Entradas: {entries_7d} (média {entries_7d / 7:.1f}/dia)")
    lines.append(f"• Resoluções: {resolved_7d} | Acertos: {wins_7d} ({pct(wins_7d, resolved_7d)})")
    lines.append(f"• P&L resolvido 7d: ${pnl_7d:+.2f}")
    lines.append("")
    lines.append(f"📂 Posições abertas: {len(open_positions)}")
    for t in open_positions:
        lines.append(f"  ▸ {t['city'].title()} {t['date']} | bucket {t['bucket']}°C @ ${t['entry_price']}")
    report = "\n".join(lines)

    # salva
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out = os.path.join(REPORTS, f"daily_{ts}.md")
    with open(out, "w") as fp:
        fp.write(report + "\n")
    # mantém só os 30 últimos
    olds = sorted(glob.glob(os.path.join(REPORTS, "daily_*.md")))
    for o in olds[:-30]:
        os.remove(o)

    print(report)

    # telegram
    try:
        sys.path.insert(0, BASE)
        from telegram_alerts import send_telegram_message
        send_telegram_message(report)
    except Exception as e:
        print(f"[WARN] telegram falhou: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

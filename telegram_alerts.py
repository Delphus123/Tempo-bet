#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_alerts.py — Send Telegram alerts for Tempo-Bet
"""

import requests
import json
from datetime import datetime

# Telegram Bot Token (from OpenClaw config)
TELEGRAM_BOT_TOKEN = "8307937716:AAGmvRDCEOl2dUMpmPfgpDB5Uxdx8RLsDB4"
TELEGRAM_CHAT_ID = "111597747"  # Rafael's Telegram ID

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def send_telegram_message(text):
    """Send message via Telegram Bot API"""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        return response.ok
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False

def format_currency(value):
    """Format currency with sign"""
    if value >= 0:
        return f"+${value:.2f}"
    return f"${value:.2f}"

def alert_new_trade(city, date, bucket, price, ev, cost, source):
    """Alert when a new trade is opened"""
    text = f"""🌤 <b>Tempo-Bet - NOVO TRADE</b>

📍 <b>Cidade:</b> {city}
📅 <b>Data:</b> {date}
🌡 <b>Bucket:</b> {bucket}
💰 <b>Entrada:</b> ${price:.3f}
📊 <b>EV:</b> +{ev:.1f}%
💵 <b>Valor:</b> ${cost:.2f}
🔮 <b>Fonte:</b> {source.upper()}

⏳ Status: <b>ABERTO</b>"""
    return send_telegram_message(text)

def alert_trade_closed(city, date, bucket, pnl, reason, source):
    """Alert when a trade is closed (stop-loss, take-profit, etc)"""
    emoji = "🛑" if "stop" in reason.lower() else "📤"
    text = f"""🌤 <b>Tempo-Bet - TRADE FECHADO</b>

📍 <b>Cidade:</b> {city}
📅 <b>Data:</b> {date}
🌡 <b>Bucket:</b> {bucket}
📊 <b>Motivo:</b> {reason}
💰 <b>P&L:</b> {format_currency(pnl)}
🔮 <b>Fonte:</b> {source.upper()}

⏳ Status: <b>FECHADO</b>"""
    return send_telegram_message(text)

def alert_trade_resolved(city, date, pnl, actual_temp, forecast, source):
    """Alert when a trade is resolved (win or loss)"""
    if pnl >= 0:
        emoji = "✅"
        result = "WIN"
    else:
        emoji = "❌"
        result = "LOSS"
    
    text = f"""🌤 <b>Tempo-Bet - TRADE RESOLVIDO</b>

{emoji} <b>Resultado:</b> {result}
📍 <b>Cidade:</b> {city}
📅 <b>Data:</b> {date}
🌡 <b>Temperatura:</b> {actual_temp}°C (previsto: {forecast}°C)
💰 <b>P&L:</b> {format_currency(pnl)}

📊 Status: <b>RESOLVIDO</b>"""
    return send_telegram_message(text)

def alert_pnl_update(open_positions, total_unrealized):
    """Alert with P&L update (sent periodically or when significant)"""
    sign = "+" if total_unrealized >= 0 else ""
    text = f"""🌤 <b>Tempo-Bet - P&L Update</b>

💰 <b>Unrealized P&L:</b> {sign}{total_unrealized:.2f}

📍 <b>Posições Abertas:</b>
"""
    for pos in open_positions:
        city = pos.get('city', 'Unknown')
        date = pos.get('date', 'N/A')
        bucket = pos.get('bucket', 'N/A')
        entry = pos.get('entry', 0)
        current = pos.get('current', 0)
        pnl = pos.get('pnl', 0)
        sign_pnl = "+" if pnl >= 0 else ""
        text += f"• {city} ({date}): {bucket} | {sign_pnl}{pnl:.2f}%\n"
    
    text += f"\n📊 Total: {sign}{total_unrealized:.2f}"
    return send_telegram_message(text)

def alert_error(error_msg):
    """Alert when an error occurs"""
    text = f"""⚠️ <b>Tempo-Bet - ERRO</b>

❌ <b>Erro:</b> {error_msg}

🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
    return send_telegram_message(text)

def alert_bot_started():
    """Alert when bot starts"""
    text = f"""🚀 <b>Tempo-Bet INICIADO</b>

🌤 Bot de Apostas Meteorológicas
📊 Polymarket Weather Trading
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ Monitoramento ATIVO"""
    return send_telegram_message(text)

def alert_daily_report(wins, losses, total_pnl, balance, start_balance):
    """Daily summary report"""
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    ret = (balance - start_balance) / start_balance * 100
    
    text = f"""📊 <b>Tempo-Bet - RELATÓRIO DIÁRIO</b>

🗓 Data: {datetime.now().strftime('%Y-%m-%d')}

📈 <b>Trades:</b> {total}
✅ <b>Wins:</b> {wins}
❌ <b>Losses:</b> {losses}
📊 <b>Win Rate:</b> {wr:.0f}%

💰 <b>P&L Total:</b> {format_currency(total_pnl)}
💵 <b>Saldo:</b> ${balance:.2f}
📈 <b>Retorno:</b> {ret:+.1f}%

⏰ {datetime.now().strftime('%H:%M:%S')}"""
    return send_telegram_message(text)

if __name__ == "__main__":
    # Test
    print("Testing Telegram alerts...")
    alert_bot_started()

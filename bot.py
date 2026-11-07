
import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

# SHADOW FX BOT
# ICT GOLD SIGNAL ENGINE - TEST VERSION

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "GC=F"  # Gold Futures proxy, NOT broker XAUUSD


def get_candles(interval, period):
    data = yf.download(
        SYMBOL,
        interval=interval,
        period=period,
        progress=False,
        auto_adjust=False
    )

    if data is None or data.empty:
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in required):
        return None

    return data.dropna()


def market_bias(df):
    if df is None or len(df) < 25:
        return None

    ema = df["Close"].ewm(span=20).mean()

    if df["Close"].iloc[-1] > ema.iloc[-1]:
        return "BUY"

    if df["Close"].iloc[-1] < ema.iloc[-1]:
        return "SELL"

    return None


def liquidity_sweep(df):
    if df is None or len(df) < 22:
        return None

    previous = df.iloc[-21:-1]
    candle = df.iloc[-1]

    if (
        candle["Low"] < previous["Low"].min()
        and candle["Close"] > previous["Low"].min()
    ):
        return "BUY", float(candle["Low"])

    if (
        candle["High"] > previous["High"].max()
        and candle["Close"] < previous["High"].max()
    ):
        return "SELL", float(candle["High"])

    return None


def has_fvg(df, direction):
    if df is None or len(df) < 3:
        return False

    a = df.iloc[-3]
    c = df.iloc[-1]

    if direction == "BUY":
        return float(c["Low"]) > float(a["High"])

    return float(c["High"]) < float(a["Low"])


def confirmation(df, direction):
    if df is None or len(df) < 3:
        return False

    previous = df.iloc[-2]
    current = df.iloc[-1]

    if direction == "BUY":
        return (
            current["Close"] > current["Open"]
            and current["Close"] > previous["High"]
        )

    return (
        current["Close"] < current["Open"]
        and current["Close"] < previous["Low"]
    )


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()


def analyze():
    print("Starting Shadow FX Bot...")

    daily = get_candles("1d", "6mo")
    hourly = get_candles("1h", "30d")
    fifteen = get_candles("15m", "30d")
    five = get_candles("5m", "5d")

    if any(x is None for x in [daily, hourly, fifteen, five]):
        print("Market data unavailable. No signal.")
        return

    four_hour = hourly.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last"
    }).dropna()

    biases = [
        market_bias(daily),
        market_bias(four_hour),
        market_bias(hourly)
    ]

    if not all(biases) or len(set(biases)) != 1:
        print("Timeframe direction not aligned.")
        return

    direction = biases[0]

    sweep = liquidity_sweep(fifteen)

    if not sweep or sweep[0] != direction:
        print("No matching liquidity sweep.")
        return

    if not has_fvg(fifteen, direction):
        print("No matching 15M FVG.")
        return

    if not confirmation(five, direction):
        print("Waiting for 5M confirmation.")
        return

    entry = float(five["Close"].iloc[-1])
    extreme = sweep[1]

    if direction == "BUY":
        sl = extreme
        risk = entry - sl
        tp = entry + (risk * 2)
    else:
        sl = extreme
        risk = sl - entry
        tp = entry - (risk * 2)

    if risk <= 0:
        print("Invalid risk. No signal.")
        return

    message = f"""
SHADOW FX BOT
ICT MARKET SIGNAL

Instrument: GOLD FUTURES (GC=F)
Direction: {direction}

Entry: {entry:.2f}
Stop Loss: {sl:.2f}
Take Profit: {tp:.2f}

Risk/Reward: 1:2

Timeframes:
D1: {biases[0]}
H4: {biases[1]}
H1: {biases[2]}
M15: Liquidity sweep + FVG
M5: Confirmation

Data: Yahoo Finance
Status: TEST SIGNAL
Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

WARNING:
GC=F is not broker XAUUSD.
Verify price and execution before trading.
This is not guaranteed financial advice.
"""

    send_telegram(message)
    print("Signal sent to Telegram.")


if __name__ == "__main__":
    try:
        analyze()
    except Exception as error:
        print("BOT ERROR:", error)

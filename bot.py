import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

# =================================
# SHADOW FX BOT - ICT SIGNAL ENGINE
# =================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "GC=F"  # Gold Futures market data


def get_candles(interval, period):
    try:
        data = yf.download(
            SYMBOL,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if data is None or data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close"]

        if not all(col in data.columns for col in required):
            return None

        data = data[required].dropna()

        if len(data) < 25:
            return None

        return data

    except Exception as error:
        print(f"Data error ({interval}): {error}")
        return None


def market_bias(df):
    if df is None or len(df) < 50:
        return None

    close = df["Close"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()

    price = float(close.iloc[-2])

    if price > ema20.iloc[-2] > ema50.iloc[-2]:
        return "BUY"

    if price < ema20.iloc[-2] < ema50.iloc[-2]:
        return "SELL"

    return None


def liquidity_sweep(df):
    if df is None or len(df) < 22:
        return None

    # Use closed candles only
    for i in range(len(df) - 2, max(len(df) - 5, 20) - 1, -1):
        previous = df.iloc[i - 20:i]
        candle = df.iloc[i]

        old_low = float(previous["Low"].min())
        old_high = float(previous["High"].max())

        if (
            float(candle["Low"]) < old_low
            and float(candle["Close"]) > old_low
        ):
            return "BUY", float(candle["Low"])

        if (
            float(candle["High"]) > old_high
            and float(candle["Close"]) < old_high
        ):
            return "SELL", float(candle["High"])

    return None


def has_fvg(df, direction):
    if df is None or len(df) < 5:
        return False

    # Search recent closed candles
    for i in range(max(2, len(df) - 7), len(df) - 1):
        first = df.iloc[i - 2]
        third = df.iloc[i]

        if direction == "BUY":
            if float(third["Low"]) > float(first["High"]):
                return True

        if direction == "SELL":
            if float(third["High"]) < float(first["Low"]):
                return True

    return False


def confirmation(df, direction):
    if df is None or len(df) < 3:
        return False

    previous = df.iloc[-3]
    current = df.iloc[-2]

    if direction == "BUY":
        return (
            float(current["Close"]) > float(current["Open"])
            and float(current["Close"]) > float(previous["High"])
        )

    return (
        float(current["Close"]) < float(current["Open"])
        and float(current["Close"]) < float(previous["Low"])
    )


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise ValueError("Telegram secrets are missing!")

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

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")

    print("Telegram signal sent successfully!")


def analyze():
    print("Starting SHADOW FX BOT...")
    print("Downloading market candles...")

    daily = get_candles("1d", "6mo")
    hourly = get_candles("1h", "30d")
    fifteen = get_candles("15m", "60d")
    five = get_candles("5m", "5d")

    if any(x is None for x in [daily, hourly, fifteen, five]):
        print("Market data unavailable. No signal.")
        return

    # Build H4 candles from H1
    four_hour = hourly.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last"
    }).dropna()

    d1 = market_bias(daily)
    h4 = market_bias(four_hour)
    h1 = market_bias(hourly)

    print("D1:", d1)
    print("H4:", h4)
    print("H1:", h1)

    if not all([d1, h4, h1]) or len({d1, h4, h1}) != 1:
        print("Timeframes are not aligned. Waiting.")
        return

    direction = d1

    sweep = liquidity_sweep(fifteen)

    if not sweep or sweep[0] != direction:
        print("No matching liquidity sweep.")
        return

    if not has_fvg(fifteen, direction):
        print("No matching 15M Fair Value Gap.")
        return

    if not confirmation(five, direction):
        print("Waiting for 5M confirmation.")
        return

    entry = float(five["Close"].iloc[-2])
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
        print("Invalid Stop Loss. No signal.")
        return

    message = f"""
SHADOW FX BOT
ICT SIGNAL

Instrument: GOLD FUTURES (GC=F)
Direction: {direction}

ENTRY: {entry:.2f}
STOP LOSS: {sl:.2f}
TAKE PROFIT: {tp:.2f}

Risk Reward: 1:2

MARKET ANALYSIS
D1: {d1}
H4: {h4}
H1: {h1}

M15: Liquidity Sweep + FVG
M5: Confirmation passed

Data Source: Yahoo Finance
Signal Type: ICT-style rule-based analysis

Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

WARNING:
This is Gold Futures data, not a guaranteed
broker XAUUSD execution price.
Verify the setup before trading.
"""

    send_telegram(message)


if __name__ == "__main__":
    try:
        analyze()
    except Exception as error:
        print("BOT ERROR:", error)
        raise

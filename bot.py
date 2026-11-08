import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

# ==========================================
# SHADOW FX BOT - ICT SIGNAL ENGINE
# ==========================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = os.getenv("FOREX_SYMBOL", "GC=F")
RR = 2


def get_data(interval, period):
    try:
        df = yf.download(
            SYMBOL,
            interval=interval,
            period=period,
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df[["Open", "High", "Low", "Close"]].dropna()

        if len(df) < 60:
            return None

        return df

    except Exception as e:
        print(f"DATA ERROR {interval}: {e}")
        return None


def get_bias(df):
    if df is None or len(df) < 55:
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
    if df is None or len(df) < 25:
        return None

    candle = df.iloc[-2]
    previous = df.iloc[-22:-2]

    old_high = float(previous["High"].max())
    old_low = float(previous["Low"].min())

    low = float(candle["Low"])
    high = float(candle["High"])
    close = float(candle["Close"])

    if low < old_low and close > old_low:
        return "BUY", low

    if high > old_high and close < old_high:
        return "SELL", high

    return None


def detect_fvg(df, direction):
    if df is None or len(df) < 5:
        return False

    for i in range(len(df) - 5, len(df) - 2):
        first = df.iloc[i]
        third = df.iloc[i + 2]

        if direction == "BUY":
            if float(third["Low"]) > float(first["High"]):
                return True

        if direction == "SELL":
            if float(third["High"]) < float(first["Low"]):
                return True

    return False


def detect_order_block(df, direction):
    if df is None or len(df) < 10:
        return False

    candles = df.iloc[-10:-2]

    for i in range(len(candles) - 1):
        candle = candles.iloc[i]
        next_candle = candles.iloc[i + 1]

        body = abs(float(next_candle["Close"]) -
                   float(next_candle["Open"]))

        if direction == "BUY":
            if (
                float(candle["Close"]) < float(candle["Open"])
                and float(next_candle["Close"]) > float(candle["High"])
                and body > 0
            ):
                return True

        if direction == "SELL":
            if (
                float(candle["Close"]) > float(candle["Open"])
                and float(next_candle["Close"]) < float(candle["Low"])
                and body > 0
            ):
                return True

    return False


def market_structure(df, direction):
    if df is None or len(df) < 25:
        return False

    previous = df.iloc[-12:-2]
    current = df.iloc[-2]

    if direction == "BUY":
        return float(current["Close"]) > float(previous["High"].max())

    return float(current["Close"]) < float(previous["Low"].min())


def confirmation(df, direction):
    if df is None or len(df) < 5:
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


def calculate_rsi(df):
    close = df["Close"]
    change = close.diff()

    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss.replace(0, 0.000001)
    return 100 - (100 / (1 + rs))


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise ValueError("Telegram secrets are missing!")

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )

    response.raise_for_status()

    if not response.json().get("ok"):
        raise RuntimeError("Telegram message failed")

    print("TELEGRAM SIGNAL SENT!")


def analyze():
    print("================================")
    print("SHADOW FX BOT STARTED")
    print("================================")

    daily = get_data("1d", "6mo")
    hourly = get_data("1h", "30d")
    fifteen = get_data("15m", "60d")
    five = get_data("5m", "5d")

    if any(x is None for x in [daily, hourly, fifteen, five]):
        print("Market data unavailable. NO TRADE.")
        return

    # Build H4 candles from H1 data
    h4 = hourly.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last"
    }).dropna()

    d1_bias = get_bias(daily)
    h4_bias = get_bias(h4)
    h1_bias = get_bias(hourly)

    print("D1:", d1_bias)
    print("H4:", h4_bias)
    print("H1:", h1_bias)

    # Higher timeframe direction
    if not all([d1_bias, h4_bias, h1_bias]):
        print("No clear trend. NO TRADE.")
        return

    if len({d1_bias, h4_bias, h1_bias}) != 1:
        print("Timeframes not aligned. NO TRADE.")
        return

    direction = d1_bias

    # H1 liquidity sweep
    sweep = liquidity_sweep(hourly)

    if not sweep or sweep[0] != direction:
        print("No H1 liquidity sweep. NO TRADE.")
        return

    # H1 Fair Value Gap or Order Block
    fvg = detect_fvg(hourly, direction)
    ob = detect_order_block(hourly, direction)

    if not fvg and not ob:
        print("No H1 FVG or Order Block. NO TRADE.")
        return

    # M15 market structure confirmation
    if not market_structure(fifteen, direction):
        print("M15 BOS confirmation missing. NO TRADE.")
        return

    # M5 entry confirmation
    if not confirmation(five, direction):
        print("Waiting for M5 confirmation.")
        return

    # RSI filter
    rsi = float(calculate_rsi(five).iloc[-2])

    if direction == "BUY" and rsi > 75:
        print("BUY rejected: RSI too high.")
        return

    if direction == "SELL" and rsi < 25:
        print("SELL rejected: RSI too low.")
        return

    entry = float(five["Close"].iloc[-2])
    stop = float(sweep[1])

    if direction == "BUY":
        risk = entry - stop
        if risk <= 0:
            print("Invalid BUY stop loss.")
            return
        tp = entry + (risk * RR)

    else:
        risk = stop - entry
        if risk <= 0:
            print("Invalid SELL stop loss.")
            return
        tp = entry - (risk * RR)

    setup = []
    if fvg:
        setup.append("FVG")
    if ob:
        setup.append("Order Block")

    message = f"""
SHADOW FX BOT
ICT TRADE SIGNAL

SYMBOL: {SYMBOL}
DIRECTION: {direction}

ENTRY: {entry:.2f}
STOP LOSS: {stop:.2f}
TAKE PROFIT: {tp:.2f}

RISK REWARD: 1:{RR}

MULTI-TIMEFRAME ANALYSIS
D1: {d1_bias}
H4: {h4_bias}
H1: {h1_bias}

ICT ANALYSIS
Liquidity Sweep: PASSED
M15 BOS: PASSED
M5 Confirmation: PASSED
Setup: {" + ".join(setup)}
RSI: {rsi:.2f}

Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

Data: Yahoo Finance
Mode: Rule-based ICT analysis

WARNING:
GC=F is Gold Futures, not broker XAUUSD.
Verify prices before trading.
"""

    send_telegram(message)


if __name__ == "__main__":
    try:
        analyze()
    except Exception as error:
        print("BOT ERROR:", error)
        raise


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
RR = 2.0


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("ERROR: Telegram secrets missing")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "text": message},
            timeout=20
        )

        print("Telegram status:", response.status_code)
        print("Telegram response:", response.json())

        response.raise_for_status()
        return response.json().get("ok", False)

    except Exception as error:
        print("Telegram error:", error)
        return False


# ==========================================
# MARKET DATA
# ==========================================

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
            print(f"No data for {interval}")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df[["Open", "High", "Low", "Close"]].dropna()

        if len(df) < 60:
            print(f"Not enough candles: {interval}")
            return None

        return df

    except Exception as error:
        print(f"Data error {interval}: {error}")
        return None


# ==========================================
# H4 DATA
# ==========================================

def make_h4(hourly):
    try:
        h4 = hourly.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last"
        }).dropna()

        return h4 if len(h4) >= 60 else None

    except Exception as error:
        print("H4 error:", error)
        return None


# ==========================================
# TREND ANALYSIS
# ==========================================

def get_bias(df, label):
    if df is None or len(df) < 60:
        print(f"{label}: Insufficient data")
        return None

    close = pd.to_numeric(
        df["Close"], errors="coerce"
    ).dropna()

    closed = close.iloc[:-1]

    if len(closed) < 55:
        return None

    ema20 = closed.ewm(
        span=20, adjust=False
    ).mean()

    ema50 = closed.ewm(
        span=50, adjust=False
    ).mean()

    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    old_e50 = float(ema50.iloc[-6])
    price = float(closed.iloc[-1])

    if e20 > e50 and e50 > old_e50:
        bias = "BUY"
    elif e20 < e50 and e50 < old_e50:
        bias = "SELL"
    else:
        bias = None

    print(
        f"{label}: Price={price:.2f}, "
        f"EMA20={e20:.2f}, EMA50={e50:.2f}, "
        f"Bias={bias}"
    )

    return bias


# ==========================================
# LIQUIDITY SWEEP
# ==========================================

def find_liquidity_sweep(df):
    if df is None or len(df) < 30:
        return None

    candles = df.iloc[:-1]

    # Search recent closed candles
    start = max(20, len(candles) - 10)

    for i in range(len(candles) - 1, start - 1, -1):
        previous = candles.iloc[i-20:i]
        candle = candles.iloc[i]

        old_high = float(previous["High"].max())
        old_low = float(previous["Low"].min())

        high = float(candle["High"])
        low = float(candle["Low"])
        close = float(candle["Close"])

        # Sweep above highs then close back below
        if high > old_high and close < old_high:
            return {
                "direction": "SELL",
                "index": i,
                "level": old_high
            }

        # Sweep below lows then close back above
        if low < old_low and close > old_low:
            return {
                "direction": "BUY",
                "index": i,
                "level": old_low
            }

    return None


# ==========================================
# MARKET STRUCTURE AFTER SWEEP
# ==========================================

def structure_break(df, sweep):
    if sweep is None:
        return False

    candles = df.iloc[:-1]
    i = sweep["index"]

    if i >= len(candles) - 1:
        return False

    previous = candles.iloc[max(0, i-20):i]

    if previous.empty:
        return False

    after = candles.iloc[i+1:]

    if after.empty:
        return False

    if sweep["direction"] == "BUY":
        level = float(previous["High"].max())
        return float(after["Close"].max()) > level

    if sweep["direction"] == "SELL":
        level = float(previous["Low"].min())
        return float(after["Close"].min()) < level

    return False


# ==========================================
# FAIR VALUE GAP
# ==========================================

def detect_fvg(df, direction):
    if df is None or len(df) < 5:
        return False

    candles = df.iloc[:-1]

    for i in range(max(2, len(candles)-8), len(candles)):
        a = candles.iloc[i-2]
        c = candles.iloc[i]

        if direction == "BUY":
            if float(c["Low"]) > float(a["High"]):
                return True

        if direction == "SELL":
            if float(c["High"]) < float(a["Low"]):
                return True

    return False


# ==========================================
# ORDER BLOCK
# ==========================================

def detect_order_block(df, direction):
    if df is None or len(df) < 5:
        return False

    candles = df.iloc[:-1]

    for i in range(len(candles)-2, max(0, len(candles)-10), -1):
        candle = candles.iloc[i]
        next_candle = candles.iloc[i+1]

        if direction == "BUY":
            if (
                float(candle["Close"]) < float(candle["Open"])
                and float(next_candle["Close"]) > float(candle["High"])
            ):
                return True

        if direction == "SELL":
            if (
                float(candle["Close"]) > float(candle["Open"])
                and float(next_candle["Close"]) < float(candle["Low"])
            ):
                return True

    return False


# ==========================================
# M5 ENTRY CONFIRMATION
# ==========================================

def confirmation(df, direction):
    if df is None or len(df) < 5:
        return False

    candles = df.iloc[:-1]

    last = candles.iloc[-1]
    previous = candles.iloc[-2]

    if direction == "BUY":
        return (
            float(last["Close"]) > float(last["Open"])
            and float(last["Close"]) > float(previous["High"])
        )

    if direction == "SELL":
        return (
            float(last["Close"]) < float(last["Open"])
            and float(last["Close"]) < float(previous["Low"])
        )

    return False


# ==========================================
# RSI
# ==========================================

def calculate_rsi(df):
    close = df["Close"].iloc[:-1]
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


# ==========================================
# ENTRY, SL AND TP
# ==========================================

def calculate_levels(df, direction):
    candles = df.iloc[:-1]

    entry = float(candles["Close"].iloc[-1])
    recent = candles.iloc[-10:]

    if direction == "BUY":
        sl = float(recent["Low"].min())

        if sl >= entry:
            return None

        risk = entry - sl
        tp = entry + (risk * RR)

    else:
        sl = float(recent["High"].max())

        if sl <= entry:
            return None

        risk = sl - entry
        tp = entry - (risk * RR)

    return entry, sl, tp


# ==========================================
# MAIN ANALYSIS
# ==========================================

def analyze():
    print("\n==============================")
    print("SHADOW FX BOT STARTED")
    print("==============================")

    daily = get_data("1d", "6mo")
    hourly = get_data("1h", "30d")
    m15 = get_data("15m", "60d")
    m5 = get_data("5m", "5d")

    if any(x is None for x in [daily, hourly, m15, m5]):
        print("Missing market data. NO TRADE.")
        return

    h4 = make_h4(hourly)

    if h4 is None:
        print("H4 data unavailable. NO TRADE.")
        return

    d1 = get_bias(daily, "D1")
    h4_bias = get_bias(h4, "H4")
    h1 = get_bias(hourly, "H1")

    if not d1 or not h4_bias or not h1:
        print("Trend unavailable. NO TRADE.")
        return

    if not (d1 == h4_bias == h1):
        print("Timeframes disagree. NO TRADE.")
        return

    direction = d1

    # M15 liquidity
    sweep = find_liquidity_sweep(m15)

    if sweep is None or sweep["direction"] != direction:
        print("No matching liquidity sweep. NO TRADE.")
        return

    # Market structure
    if not structure_break(m15, sweep):
        print("No BOS after liquidity sweep. NO TRADE.")
        return

    # FVG / Order Block
    fvg = detect_fvg(m15, direction)
    ob = detect_order_block(m15, direction)

    if not (fvg or ob):
        print("No FVG or Order Block. NO TRADE.")
        return

    # M5 confirmation
    if not confirmation(m5, direction):
        print("M5 confirmation missing. NO TRADE.")
        return

    rsi = calculate_rsi(m15)

    if pd.isna(rsi):
        print("RSI unavailable. NO TRADE.")
        return

    if direction == "BUY" and rsi >= 70:
        print("RSI overbought. NO TRADE.")
        return

    if direction == "SELL" and rsi <= 30:
        print("RSI oversold. NO TRADE.")
        return

    levels = calculate_levels(m5, direction)

    if levels is None:
        print("Invalid SL/TP. NO TRADE.")
        return

    entry, sl, tp = levels

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = f"""
🚨 SHADOW FX BOT 🚨

SYMBOL: {SYMBOL}
SIGNAL: {direction}

ENTRY: {entry:.2f}
STOP LOSS: {sl:.2f}
TAKE PROFIT: {tp:.2f}

D1: {d1}
H4: {h4_bias}
H1: {h1}

Liquidity Sweep: YES
BOS: YES
FVG: {"YES" if fvg else "NO"}
Order Block: {"YES" if ob else "NO"}
M5 Confirmation: YES
RSI: {rsi:.2f}

Risk Reward: 1:{RR}
Time: {now}

Data: Yahoo Finance
Signal only - verify before trading.
"""

    print(message)
    send_telegram(message)


# ==========================================
# START
# ==========================================

if __name__ == "__main__":
    analyze()

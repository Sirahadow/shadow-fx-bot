
import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime

# ==========================================
# SHADOW FX BOT - ICT SIGNAL ENGINE
# ==========================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = os.getenv("FOREX_SYMBOL", "GC=F")
RISK_REWARD = 2.0


# ==========================================
# GET MARKET DATA
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
            print(f"No data: {interval}")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        required = ["Open", "High", "Low", "Close"]
        df = df[required].dropna()

        if len(df) < 60:
            print(f"Not enough candles: {interval}")
            return None

        return df

    except Exception as error:
        print(f"Data error {interval}: {error}")
        return None


# ==========================================
# RESAMPLE H1 TO H4
# ==========================================

def make_h4(df):
    if df is None:
        return None

    try:
        h4 = df.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last"
        }).dropna()

        if len(h4) < 55:
            return None

        return h4

    except Exception as error:
        print("H4 error:", error)
        return None


# ==========================================
# MARKET BIAS
# ==========================================

def get_bias(df, label="TF"):
    if df is None or len(df) < 60:
        print(f"{label}: Insufficient candles")
        return None

    close = pd.to_numeric(
        df["Close"], errors="coerce"
    ).dropna()

    if len(close) < 55:
        return None

    # Use closed candles only
    closed = close.iloc[:-1]

    ema20 = closed.ewm(
        span=20, adjust=False
    ).mean()

    ema50 = closed.ewm(
        span=50, adjust=False
    ).mean()

    price = float(closed.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    old_e50 = float(ema50.iloc[-6])

    if e20 > e50 and e50 > old_e50:
        bias = "BUY"

    elif e20 < e50 and e50 < old_e50:
        bias = "SELL"

    else:
        bias = None

    print(
        f"{label}: Close={price:.2f}, "
        f"EMA20={e20:.2f}, EMA50={e50:.2f}, "
        f"Bias={bias}"
    )

    return bias


# ==========================================
# LIQUIDITY SWEEP
# ==========================================

def liquidity_sweep(df):
    if df is None or len(df) < 25:
        return None

    candles = df.iloc[:-1]

    last = candles.iloc[-1]
    previous = candles.iloc[-21:-1]

    previous_high = float(previous["High"].max())
    previous_low = float(previous["Low"].min())

    if (
        float(last["High"]) > previous_high
        and float(last["Close"]) < previous_high
    ):
        return "SELL"

    if (
        float(last["Low"]) < previous_low
        and float(last["Close"]) > previous_low
    ):
        return "BUY"

    return None


# ==========================================
# FAIR VALUE GAP
# ==========================================

def detect_fvg(df, direction):
    if df is None or len(df) < 5:
        return False

    candles = df.iloc[:-1]

    a = candles.iloc[-3]
    c = candles.iloc[-1]

    if direction == "BUY":
        return float(c["Low"]) > float(a["High"])

    if direction == "SELL":
        return float(c["High"]) < float(a["Low"])

    return False


# ==========================================
# ORDER BLOCK
# ==========================================

def detect_order_block(df, direction):
    if df is None or len(df) < 5:
        return False

    candles = df.iloc[:-1]

    for i in range(len(candles) - 2, max(0, len(candles) - 8), -1):
        candle = candles.iloc[i]
        next_candle = candles.iloc[i + 1]

        body = abs(
            float(next_candle["Close"]) -
            float(next_candle["Open"])
        )

        if direction == "BUY":
            if (
                float(candle["Close"]) < float(candle["Open"])
                and float(next_candle["Close"]) > float(next_candle["Open"])
                and float(next_candle["Close"]) > float(candle["High"])
                and body > 0
            ):
                return True

        if direction == "SELL":
            if (
                float(candle["Close"]) > float(candle["Open"])
                and float(next_candle["Close"]) < float(next_candle["Open"])
                and float(next_candle["Close"]) < float(candle["Low"])
                and body > 0
            ):
                return True

    return False


# ==========================================
# MARKET STRUCTURE / BOS
# ==========================================

def market_structure(df, direction):
    if df is None or len(df) < 25:
        return False

    candles = df.iloc[:-1]

    last = candles.iloc[-1]
    previous = candles.iloc[-21:-1]

    if direction == "BUY":
        return float(last["Close"]) > float(previous["High"].max())

    if direction == "SELL":
        return float(last["Close"]) < float(previous["Low"].min())

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
    if df is None or len(df) < 20:
        return None

    close = df["Close"].iloc[:-1]

    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))

    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


# ==========================================
# STOP LOSS AND TAKE PROFIT
# ==========================================

def calculate_levels(df, direction):
    candles = df.iloc[:-1]

    entry = float(candles["Close"].iloc[-1])

    recent = candles.iloc[-10:]

    if direction == "BUY":
        stop_loss = float(recent["Low"].min())

        if stop_loss >= entry:
            return None

        risk = entry - stop_loss
        take_profit = entry + (risk * RISK_REWARD)

    else:
        stop_loss = float(recent["High"].max())

        if stop_loss <= entry:
            return None

        risk = stop_loss - entry
        take_profit = entry - (risk * RISK_REWARD)

    return entry, stop_loss, take_profit


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return False

    try:
        url = (
            f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        )

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
            print("Telegram rejected message:", result)
            return False

        print("Telegram message sent successfully.")
        return True

    except Exception as error:
        print("Telegram error:", error)
        return False


# ==========================================
# MAIN ANALYSIS
# ==========================================

def analyze():

    print("\n================================")
    print("SHADOW FX BOT STARTED")
    print("================================")

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

    # Higher timeframe direction
    d1_bias = get_bias(daily, "D1")
    h4_bias = get_bias(h4, "H4")
    h1_bias = get_bias(hourly, "H1")

    print("D1:", d1_bias)
    print("H4:", h4_bias)
    print("H1:", h1_bias)

    if not d1_bias or not h4_bias or not h1_bias:
        print("No clear higher-timeframe trend. NO TRADE.")
        return

    if not (d1_bias == h4_bias == h1_bias):
        print("Timeframes disagree. NO TRADE.")
        return

    direction = d1_bias

    # Liquidity sweep on M15
    sweep = liquidity_sweep(m15)

    if sweep != direction:
        print("No matching liquidity sweep. NO TRADE.")
        return

    # ICT confluence
    fvg = detect_fvg(m15, direction)
    ob = detect_order_block(m15, direction)
    bos = market_structure(m15, direction)

    if not (fvg or ob):
        print("No Order Block or Fair Value Gap. NO TRADE.")
        return

    if not bos:
        print("No market structure break. NO TRADE.")
        return

    # M5 confirmation
    if not confirmation(m5, direction):
        print("M5 confirmation missing. NO TRADE.")
        return

    rsi = calculate_rsi(m15)

    if rsi is None:
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
        print("Invalid risk levels. NO TRADE.")
        return

    entry, stop_loss, take_profit = levels

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    message = f"""
🚨 SHADOW FX BOT 🚨

📊 SYMBOL: {SYMBOL}
🎯 SIGNAL: {direction}

💰 ENTRY: {entry:.2f}
🛑 STOP LOSS: {stop_loss:.2f}
🏆 TAKE PROFIT: {take_profit:.2f}

📈 D1: {d1_bias}
📈 H4: {h4_bias}
📈 H1: {h1_bias}

💧 Liquidity Sweep: YES
📦 FVG: {"YES" if fvg else "NO"}
📦 Order Block: {"YES" if ob else "NO"}
📊 BOS: YES
⏱ M5 Confirmation: YES
📉 RSI: {rsi:.2f}

⚖️ Risk Reward: 1:{RISK_REWARD}
🕒 Time: {now}

⚠️ Signal only. Confirm spread,
execution price and risk before trading.
Data source: Yahoo Finance.
"""

    print(message)
    send_telegram(message)


# ==========================================
# START BOT
# ==========================================

if __name__ == "__main__":
    analyze()

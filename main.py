"""
Forex Setup Alert Bot
=====================
Monitors forex pairs for a specific multi-timeframe EMA + ATR overextension
strategy and sends a Telegram push notification the moment a setup forms.

Strategy recap:
  4H trend filter:
    - BULLISH if 4H close > EMA9(4H) and close > EMA21(4H) and EMA9(4H) > EMA21(4H)
    - BEARISH if 4H close < EMA9(4H) and close < EMA21(4H) and EMA9(4H) < EMA21(4H)

  15m trigger (only evaluated when a 4H trend exists):
    - distance = abs(15m close - EMA21(15m))
    - overextended = distance >= ATR_MULTIPLIER * ATR(96) on 15m
    - If 4H BEARISH and the 15m candle just closed BULLISH (close > open) and overextended
        -> SELL setup
    - If 4H BULLISH and the 15m candle just closed BEARISH (close < open) and overextended
        -> BUY setup

  Only the most recently CLOSED 15m candle is evaluated each run, and a small
  state file prevents sending the same alert twice.

This script is designed to be run every 15 minutes (e.g. via GitHub Actions
cron). It fetches 15-minute candles from Twelve Data and builds 4H candles
locally by resampling, which keeps everything perfectly in sync and uses
only ONE API call per pair per run.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

# --------------------------------------------------------------------------
# CONFIG - tune these freely
# --------------------------------------------------------------------------

PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "USD/CHF",
    "USD/CAD",
    "AUD/USD",
    "NZD/USD",
]

EMA_FAST = 9
EMA_SLOW = 21
ATR_PERIOD = 96          # on the 15m chart
ATR_MULTIPLIER = 1.0     # how many ATRs away from EMA21(15m) counts as "overextended"
FOUR_H_BARS_PER_CANDLE = 16   # 16 x 15m = 4H

OUTPUT_SIZE = 1500  # number of 15m candles to pull per request (1 API credit regardless of size)
INTERVAL = "15min"

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("forex-alert-bot")


# --------------------------------------------------------------------------
# STATE (dedup so we only alert once per new setup)
# --------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


# --------------------------------------------------------------------------
# DATA FETCH
# --------------------------------------------------------------------------

def fetch_15m_candles(pair: str) -> pd.DataFrame:
    """Fetch recent 15m candles for a pair from Twelve Data."""
    params = {
        "symbol": pair,
        "interval": INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "timezone": "UTC",
        "order": "ASC",
        "apikey": TWELVEDATA_API_KEY,
    }
    resp = requests.get(TWELVEDATA_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error for {pair}: {data.get('message')}")

    values = data.get("values")
    if not values:
        raise RuntimeError(f"No data returned for {pair}")

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)
    return df[["datetime", "open", "high", "low", "close"]]


# --------------------------------------------------------------------------
# INDICATORS
# --------------------------------------------------------------------------

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def resample_to_4h(df15: pd.DataFrame) -> pd.DataFrame:
    """Build 4H candles from 15m candles, anchored to 00:00 UTC boundaries."""
    df = df15.set_index("datetime")
    ohlc = df.resample("4h", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    ohlc = ohlc.dropna()
    return ohlc.reset_index()


# --------------------------------------------------------------------------
# STRATEGY
# --------------------------------------------------------------------------

def get_4h_trend(df4h: pd.DataFrame) -> str:
    """Return 'BULLISH', 'BEARISH', or 'NONE' based on the last CLOSED 4H candle."""
    if len(df4h) < EMA_SLOW + 5:
        return "NONE"

    # Drop the last row if it's still an in-progress (incomplete) 4H bar.
    # A 4H bar is complete once we have 16 fifteen-minute bars inside it;
    # resample already only creates bars from data we have, so the LAST
    # bar may be partial. We conservatively drop it and use the prior one.
    closed = df4h.iloc[:-1] if len(df4h) > 1 else df4h

    ema9 = ema(closed["close"], EMA_FAST)
    ema21 = ema(closed["close"], EMA_SLOW)

    last_close = closed["close"].iloc[-1]
    last_ema9 = ema9.iloc[-1]
    last_ema21 = ema21.iloc[-1]

    if last_close > last_ema9 and last_close > last_ema21 and last_ema9 > last_ema21:
        return "BULLISH"
    if last_close < last_ema9 and last_close < last_ema21 and last_ema9 < last_ema21:
        return "BEARISH"
    return "NONE"


def check_15m_setup(df15: pd.DataFrame, trend: str):
    """
    Evaluate the most recently CLOSED 15m candle for an overextension setup.
    Returns (signal or None, candle_timestamp_iso, details_dict)
    """
    if trend == "NONE" or len(df15) < max(ATR_PERIOD, EMA_SLOW) + 5:
        return None, None, {}

    # The very last row from the API may still be forming; use the one
    # before it as the "last closed" candle to be safe.
    closed = df15.iloc[:-1] if len(df15) > 1 else df15

    ema21_15 = ema(closed["close"], EMA_SLOW)
    atr96_15 = atr(closed, ATR_PERIOD)

    last = closed.iloc[-1]
    last_ema21 = ema21_15.iloc[-1]
    last_atr = atr96_15.iloc[-1]

    distance = abs(last["close"] - last_ema21)
    overextended = distance >= ATR_MULTIPLIER * last_atr
    candle_is_bullish = last["close"] > last["open"]
    candle_is_bearish = last["close"] < last["open"]

    details = {
        "close": round(float(last["close"]), 5),
        "ema21_15m": round(float(last_ema21), 5),
        "atr96_15m": round(float(last_atr), 5),
        "distance": round(float(distance), 5),
        "distance_in_atr": round(float(distance / last_atr), 2) if last_atr else None,
    }

    ts = last["datetime"].isoformat()

    if trend == "BEARISH" and candle_is_bullish and overextended:
        return "SELL", ts, details
    if trend == "BULLISH" and candle_is_bearish and overextended:
        return "BUY", ts, details

    return None, ts, details


# --------------------------------------------------------------------------
# TELEGRAM
# --------------------------------------------------------------------------

def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured; skipping send. Message was:\n%s", text)
        return
    url = TELEGRAM_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        log.error("Telegram send failed: %s", resp.text)
    else:
        log.info("Telegram alert sent.")


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    if not TWELVEDATA_API_KEY:
        log.error("TWELVEDATA_API_KEY is not set. Aborting.")
        sys.exit(1)

    state = load_state()
    run_started = datetime.now(timezone.utc).isoformat()
    log.info("Run started at %s | pairs=%s", run_started, ", ".join(PAIRS))

    for pair in PAIRS:
        pair_key = pair.replace("/", "")
        try:
            df15 = fetch_15m_candles(pair)
            df4h = resample_to_4h(df15)

            trend = get_4h_trend(df4h)
            signal, candle_ts, details = check_15m_setup(df15, trend)

            log.info(
                "%s | 4H trend=%s | 15m signal=%s | details=%s",
                pair, trend, signal, details,
            )

            if signal is None:
                continue

            dedup_key = f"{pair_key}_{signal}"
            last_alerted_ts = state.get(dedup_key)

            if last_alerted_ts == candle_ts:
                log.info("%s: already alerted for candle %s, skipping.", pair, candle_ts)
                continue

            # New qualifying setup -> notify
            msg = (
                f"🚨 *{signal} SETUP* — `{pair}`\n\n"
                f"4H trend: {trend}\n"
                f"15m close: {details['close']}\n"
                f"15m EMA21: {details['ema21_15m']}\n"
                f"ATR(96,15m): {details['atr96_15m']}\n"
                f"Distance: {details['distance']} ({details['distance_in_atr']}x ATR)\n"
                f"Candle: {candle_ts}\n\n"
                f"_This is an alert only — no trade was placed._"
            )
            send_telegram_message(msg)
            state[dedup_key] = candle_ts

        except Exception as e:
            log.error("Error processing %s: %s", pair, e)
            continue

        # Be gentle on the free-tier rate limit (8 req/min)
        time.sleep(2)

    save_state(state)
    log.info("Run complete.")


if __name__ == "__main__":
    main()

"""
Offline test: builds synthetic 15m candle data that should trigger a SELL
setup (4H bearish trend + 15m bullish overextension) and a BUY setup, then
runs it through the real strategy functions from main.py to confirm the
logic behaves as expected. No network calls / no API keys needed.
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

import main as bot


def build_synthetic_df(direction: str) -> pd.DataFrame:
    """
    direction = 'bearish_trend_sell_setup' or 'bullish_trend_buy_setup'
    Builds ~10 days of 15m candles: a strong directional drift (to establish
    a clean 4H EMA trend) followed by a sharp counter-move on the final
    15m candle big enough to clear 1x ATR(96) from EMA21(15m).
    """
    n = 900  # ~9.4 days of 15m candles, plenty for EMA21/ATR96/EMA9(4H) to stabilize
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=15 * i) for i in range(n)]

    rng = np.random.default_rng(42)
    base_price = 1.1000
    drift_per_bar = -0.00004 if direction == "bearish_trend_sell_setup" else 0.00004
    noise = rng.normal(0, 0.00006, n)

    closes = base_price + np.cumsum(np.full(n, drift_per_bar) + noise)

    opens = np.empty(n)
    opens[0] = base_price
    opens[1:] = closes[:-1]

    highs = np.maximum(opens, closes) + rng.uniform(0.00002, 0.00008, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.00002, 0.00008, n)

    # Force a strong counter-move on the SECOND-TO-LAST candle, since main.py
    # treats the very last row returned by the API as possibly still-forming
    # and evaluates the candle before it as the "last closed" one.
    idx = -2
    prev_close = closes[idx - 1]
    if direction == "bearish_trend_sell_setup":
        # trend is down -> make this candle spike UP strongly (bullish 15m candle)
        this_close = prev_close + 0.0060
    else:
        # trend is up -> make this candle spike DOWN strongly (bearish 15m candle)
        this_close = prev_close - 0.0060

    opens[idx] = prev_close
    closes[idx] = this_close
    highs[idx] = max(prev_close, this_close) + 0.0002
    lows[idx] = min(prev_close, this_close) - 0.0002
    # Keep the final (dropped/"forming") candle as ordinary noise continuing from this_close.
    opens[-1] = this_close
    closes[-1] = this_close + noise[-1]
    highs[-1] = max(opens[-1], closes[-1]) + 0.00005
    lows[-1] = min(opens[-1], closes[-1]) - 0.00005

    df = pd.DataFrame({
        "datetime": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    })
    return df


def run_case(direction, expected_signal):
    df15 = build_synthetic_df(direction)
    df4h = bot.resample_to_4h(df15)
    trend = bot.get_4h_trend(df4h)
    signal, ts, details = bot.check_15m_setup(df15, trend)

    print(f"--- case: {direction} ---")
    print(f"4H bars built: {len(df4h)} | 4H trend detected: {trend}")
    print(f"15m signal: {signal} | candle_ts: {ts}")
    print(f"details: {details}")
    ok = signal == expected_signal
    print("RESULT:", "PASS" if ok else "FAIL")
    print()
    return ok


def run_no_signal_case():
    """Flat/choppy market -> expect trend NONE or no overextension -> signal None."""
    n = 900
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(minutes=15 * i) for i in range(n)]
    rng = np.random.default_rng(7)
    closes = 1.1000 + np.cumsum(rng.normal(0, 0.00003, n))
    opens = np.empty(n)
    opens[0] = 1.1000
    opens[1:] = closes[:-1]
    highs = np.maximum(opens, closes) + rng.uniform(0.00001, 0.00003, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.00001, 0.00003, n)
    df15 = pd.DataFrame({"datetime": timestamps, "open": opens, "high": highs, "low": lows, "close": closes})

    df4h = bot.resample_to_4h(df15)
    trend = bot.get_4h_trend(df4h)
    signal, ts, details = bot.check_15m_setup(df15, trend)
    print("--- case: choppy/no-trend market ---")
    print(f"4H trend: {trend} | signal: {signal}")
    ok = signal is None
    print("RESULT:", "PASS" if ok else "FAIL")
    print()
    return ok


if __name__ == "__main__":
    results = []
    results.append(run_case("bearish_trend_sell_setup", "SELL"))
    results.append(run_case("bullish_trend_buy_setup", "BUY"))
    results.append(run_no_signal_case())

    print("=" * 40)
    if all(results):
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)

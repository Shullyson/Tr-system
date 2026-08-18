"""
TA (technical analysis) agent — mostly rule-based, LLM only for the
plain-language summary.

Pattern/level detection (support, resistance, swing structure) is pure
math on price history — deterministic and backtestable, same as the
indicator agent. The LLM's only job here is turning that structured
output into a readable paragraph. It never computes a level itself.
"""
from dataclasses import dataclass, field
import pandas as pd
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__)))
from llm_client import LLMClient

SYSTEM_PROMPT = """You are a technical analysis summarizer inside an \
automated crypto trading advisory system. You are given ALREADY-COMPUTED \
support/resistance levels and swing structure data. Your only job is to \
explain what this structure means in plain language — you do NOT \
recalculate, adjust, or invent any price level. Every number in your \
summary must come directly from the data given to you.

Respond in this exact JSON structure:
{
  "structure_bias": "bullish" | "bearish" | "neutral",
  "summary": "<2-3 sentence plain-language explanation of the price structure>"
}"""


@dataclass
class TAReading:
    symbol: str
    swing_high: float
    swing_low: float
    nearest_resistance: float
    nearest_support: float
    higher_highs: bool
    higher_lows: bool
    structure_bias: str
    summary: str = ""


class TAAgent:
    def __init__(self, llm_client: LLMClient = None, swing_window: int = 10):
        self.llm = llm_client or LLMClient()
        self.swing_window = swing_window

    def _find_swing_points(self, ohlcv: pd.DataFrame):
        """
        Local maxima/minima over a rolling window — a simple, deterministic
        definition of swing highs/lows. window=10 means a candle must be
        the highest/lowest point within 10 candles on each side.
        """
        w = self.swing_window
        highs = ohlcv["high"]
        lows = ohlcv["low"]

        is_swing_high = (highs == highs.rolling(w * 2 + 1, center=True).max())
        is_swing_low = (lows == lows.rolling(w * 2 + 1, center=True).min())

        swing_highs = ohlcv.loc[is_swing_high, "high"].dropna()
        swing_lows = ohlcv.loc[is_swing_low, "low"].dropna()
        return swing_highs, swing_lows

    def analyze(self, symbol: str, ohlcv: pd.DataFrame) -> TAReading:
        current_price = ohlcv["close"].iloc[-1]
        swing_highs, swing_lows = self._find_swing_points(ohlcv)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            raise ValueError("Not enough swing points detected — need more candles or a smaller swing_window")

        # Structure: are recent swings trending up or down?
        recent_highs = swing_highs.tail(3).values
        recent_lows = swing_lows.tail(3).values
        higher_highs = len(recent_highs) >= 2 and recent_highs[-1] > recent_highs[0]
        higher_lows = len(recent_lows) >= 2 and recent_lows[-1] > recent_lows[0]

        # Nearest resistance = closest swing high ABOVE current price
        # Nearest support = closest swing low BELOW current price
        above = swing_highs[swing_highs > current_price]
        below = swing_lows[swing_lows < current_price]
        nearest_resistance = above.min() if len(above) > 0 else swing_highs.max()
        nearest_support = below.max() if len(below) > 0 else swing_lows.min()

        if higher_highs and higher_lows:
            structure_bias_raw = "bullish"
        elif not higher_highs and not higher_lows:
            structure_bias_raw = "bearish"
        else:
            structure_bias_raw = "neutral"

        # LLM only explains — every number below is already computed
        user_prompt = f"""Symbol: {symbol}
Current price: {current_price:.2f}
Recent swing highs: {[round(x, 2) for x in recent_highs]}
Recent swing lows: {[round(x, 2) for x in recent_lows]}
Higher highs forming: {higher_highs}
Higher lows forming: {higher_lows}
Nearest resistance above price: {nearest_resistance:.2f}
Nearest support below price: {nearest_support:.2f}
Computed structure bias: {structure_bias_raw}

Explain this price structure in plain language."""

        result = self.llm.call_json(SYSTEM_PROMPT, user_prompt)

        return TAReading(
            symbol=symbol,
            swing_high=round(float(recent_highs[-1]), 2),
            swing_low=round(float(recent_lows[-1]), 2),
            nearest_resistance=round(float(nearest_resistance), 2),
            nearest_support=round(float(nearest_support), 2),
            higher_highs=higher_highs,
            higher_lows=higher_lows,
            structure_bias=structure_bias_raw,  # trust the computed value, not the LLM's echo
            summary=result.get("summary", ""),
        )


if __name__ == "__main__":
    import numpy as np
    dates = pd.date_range("2026-01-01", periods=100, freq="1h")
    np.random.seed(7)
    trend = np.linspace(0, 2000, 100)  # clear uptrend
    price = 60000 + trend + np.cumsum(np.random.randn(100) * 30)
    df = pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.randn(100) * 40),
        "low": price - np.abs(np.random.randn(100) * 40),
        "close": price + np.random.randn(100) * 15,
        "volume": np.abs(np.random.randn(100) * 100 + 500),
    })
    agent = TAAgent()
    reading = agent.analyze("BTCUSDT_TEST", df)
    print(reading)

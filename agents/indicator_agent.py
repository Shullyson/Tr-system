"""
Indicator agent — fully rule-based, no LLM involved.
Deterministic by design: same input always produces same output, which
means it's backtestable and auditable. This is the layer where "accuracy"
actually gets validated, not narrated.
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "config"))
from settings import INDICATOR_CONFIG as CFG


@dataclass
class IndicatorReading:
    symbol: str
    rsi: float
    rsi_signal: str          # 'overbought' | 'oversold' | 'neutral'
    macd_line: float
    macd_signal_line: float
    macd_histogram: float
    macd_signal: str         # 'bullish_cross' | 'bearish_cross' | 'no_cross'
    atr: float
    atr_pct: float           # ATR as % of price — normalizes across BTC/ETH price scales
    sma_20: float
    sma_50: float
    sma_200: float
    trend_signal: str        # 'uptrend' | 'downtrend' | 'mixed'
    volume_ratio: float      # current volume / volume MA
    volume_signal: str       # 'spike' | 'normal'
    confluence_score: float  # -1.0 (strong bearish) to +1.0 (strong bullish)
    confluence_direction: str  # 'bullish' | 'bearish' | 'neutral'
    agreeing_signals: list
    conflicting_signals: list


class IndicatorAgent:
    def __init__(self, config: dict = None):
        self.cfg = config or CFG

    def _rsi(self, close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def _macd(self, close: pd.Series, fast: int, slow: int, signal: int):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    def analyze(self, symbol: str, ohlcv: pd.DataFrame) -> IndicatorReading:
        """
        ohlcv must have columns: open, high, low, close, volume — at least
        ~210 rows so the 200-period SMA has enough data to be meaningful.
        """
        if len(ohlcv) < max(self.cfg["sma_periods"]) + 10:
            raise ValueError(
                f"Need at least {max(self.cfg['sma_periods']) + 10} candles, got {len(ohlcv)}"
            )

        close = ohlcv["close"]
        current_price = close.iloc[-1]

        # RSI
        rsi_series = self._rsi(close, self.cfg["rsi_period"])
        rsi = rsi_series.iloc[-1]
        if rsi >= self.cfg["rsi_overbought"]:
            rsi_signal = "overbought"
        elif rsi <= self.cfg["rsi_oversold"]:
            rsi_signal = "oversold"
        else:
            rsi_signal = "neutral"

        # MACD
        macd_line, signal_line, hist = self._macd(
            close, self.cfg["macd_fast"], self.cfg["macd_slow"], self.cfg["macd_signal"]
        )
        prev_hist = hist.iloc[-2]
        curr_hist = hist.iloc[-1]
        if prev_hist <= 0 < curr_hist:
            macd_signal = "bullish_cross"
        elif prev_hist >= 0 > curr_hist:
            macd_signal = "bearish_cross"
        else:
            macd_signal = "no_cross"

        # ATR
        atr_series = self._atr(ohlcv, self.cfg["atr_period"])
        atr = atr_series.iloc[-1]
        atr_pct = (atr / current_price) * 100

        # Trend via SMAs
        smas = {p: close.rolling(p).mean().iloc[-1] for p in self.cfg["sma_periods"]}
        sma_20, sma_50, sma_200 = smas[20], smas[50], smas[200]
        if current_price > sma_20 > sma_50 > sma_200:
            trend_signal = "uptrend"
        elif current_price < sma_20 < sma_50 < sma_200:
            trend_signal = "downtrend"
        else:
            trend_signal = "mixed"

        # Volume
        vol = ohlcv["volume"]
        vol_ma = vol.rolling(self.cfg["volume_ma_period"]).mean().iloc[-1]
        volume_ratio = vol.iloc[-1] / vol_ma if vol_ma > 0 else 1.0
        volume_signal = "spike" if volume_ratio >= self.cfg["volume_spike_multiplier"] else "normal"

        # Confluence: tally directional votes from independent signals
        bullish_votes, bearish_votes = [], []
        if rsi_signal == "oversold":
            bullish_votes.append("RSI oversold")
        elif rsi_signal == "overbought":
            bearish_votes.append("RSI overbought")

        if macd_signal == "bullish_cross":
            bullish_votes.append("MACD bullish cross")
        elif macd_signal == "bearish_cross":
            bearish_votes.append("MACD bearish cross")

        if trend_signal == "uptrend":
            bullish_votes.append("Price above rising SMA stack")
        elif trend_signal == "downtrend":
            bearish_votes.append("Price below falling SMA stack")

        total_votes = len(bullish_votes) + len(bearish_votes)
        if total_votes == 0:
            confluence_score = 0.0
        else:
            confluence_score = (len(bullish_votes) - len(bearish_votes)) / 3.0  # 3 = max possible votes

        if confluence_score > 0.2:
            confluence_direction = "bullish"
            agreeing, conflicting = bullish_votes, bearish_votes
        elif confluence_score < -0.2:
            confluence_direction = "bearish"
            agreeing, conflicting = bearish_votes, bullish_votes
        else:
            confluence_direction = "neutral"
            agreeing, conflicting = [], bullish_votes + bearish_votes

        return IndicatorReading(
            symbol=symbol,
            rsi=round(rsi, 2),
            rsi_signal=rsi_signal,
            macd_line=round(macd_line.iloc[-1], 4),
            macd_signal_line=round(signal_line.iloc[-1], 4),
            macd_histogram=round(curr_hist, 4),
            macd_signal=macd_signal,
            atr=round(atr, 4),
            atr_pct=round(atr_pct, 3),
            sma_20=round(sma_20, 2),
            sma_50=round(sma_50, 2),
            sma_200=round(sma_200, 2),
            trend_signal=trend_signal,
            volume_ratio=round(volume_ratio, 2),
            volume_signal=volume_signal,
            confluence_score=round(confluence_score, 3),
            confluence_direction=confluence_direction,
            agreeing_signals=agreeing,
            conflicting_signals=conflicting,
        )


if __name__ == "__main__":
    # Quick self-test with synthetic data (no network needed)
    dates = pd.date_range("2026-01-01", periods=250, freq="1h")
    np.random.seed(42)
    price = 60000 + np.cumsum(np.random.randn(250) * 50)
    df = pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.randn(250) * 20),
        "low": price - np.abs(np.random.randn(250) * 20),
        "close": price + np.random.randn(250) * 10,
        "volume": np.abs(np.random.randn(250) * 100 + 500),
    })
    agent = IndicatorAgent()
    reading = agent.analyze("BTCUSDT_TEST", df)
    print(reading)

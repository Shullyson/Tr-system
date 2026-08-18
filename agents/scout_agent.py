"""
Scout agent — fully rule-based, no LLM involved.
Two-stage gate, cheap to run on every tick:

  Stage 1: is anything unusual happening right now? (volatility or volume
           spike, relative to recent conditions — not a fixed number)
  Stage 2: if yes, does the indicator agent's confluence score actually
           agree on a direction, clearing a real conviction bar?

Only Stage-2 passes should trigger the full pipeline (FA/TA/risk agents).
Most ticks should exit at Stage 1 with nothing happening — that's the
point: rare, high-conviction alerts instead of constant noise.
"""
from dataclasses import dataclass
import pandas as pd
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "config"))
from settings import SCOUT_CONFIG as CFG

from indicator_agent import IndicatorAgent, IndicatorReading


@dataclass
class ScoutSignal:
    symbol: str
    atr_spike: bool
    atr_ratio: float           # current ATR / rolling ATR average
    volume_spike: bool
    volume_ratio: float
    stage1_triggered: bool     # something unusual is happening
    confluence_direction: str
    confluence_score: float
    alertable: bool            # cleared BOTH stages — worth full pipeline
    reason: str


class ScoutAgent:
    def __init__(self, config: dict = None):
        self.cfg = config or CFG
        self._indicator_agent = IndicatorAgent()

    def _atr_series(self, ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    def scan(self, symbol: str, ohlcv: pd.DataFrame,
              indicator_reading: IndicatorReading = None) -> ScoutSignal:
        """
        indicator_reading is optional — if not supplied, the scout computes
        it itself. Pass it in if you've already run the indicator agent
        elsewhere, to avoid recomputing.
        """
        if indicator_reading is None:
            indicator_reading = self._indicator_agent.analyze(symbol, ohlcv)

        # Stage 1a: volatility spike relative to its own recent history
        atr = self._atr_series(ohlcv)
        atr_avg = atr.rolling(self.cfg["atr_lookback_period"]).mean().iloc[-1]
        atr_ratio = atr.iloc[-1] / atr_avg if atr_avg > 0 else 1.0
        atr_spike = atr_ratio >= self.cfg["atr_spike_multiplier"]

        # Stage 1b: volume spike (reuse indicator agent's own ratio — no
        # need to recompute the same thing twice)
        volume_spike = indicator_reading.volume_ratio >= self.cfg["volume_spike_multiplier"]

        stage1_triggered = atr_spike or volume_spike

        if not stage1_triggered:
            return ScoutSignal(
                symbol=symbol,
                atr_spike=False,
                atr_ratio=round(atr_ratio, 2),
                volume_spike=False,
                volume_ratio=indicator_reading.volume_ratio,
                stage1_triggered=False,
                confluence_direction=indicator_reading.confluence_direction,
                confluence_score=indicator_reading.confluence_score,
                alertable=False,
                reason="No volatility or volume spike — nothing unusual, not investigating further.",
            )

        # Stage 2: confluence has to actually agree on a direction, not
        # just lean slightly. A spike with neutral/weak confluence is
        # noise, not an opportunity.
        confluence_clears_bar = (
            abs(indicator_reading.confluence_score) >= self.cfg["min_confluence_for_alert"]
            and indicator_reading.confluence_direction != "neutral"
        )

        if confluence_clears_bar:
            reason = (
                f"Spike detected (ATR {atr_ratio:.2f}x avg, volume {indicator_reading.volume_ratio:.2f}x avg) "
                f"AND confluence agrees: {indicator_reading.confluence_direction} "
                f"(score {indicator_reading.confluence_score:.2f}). Worth full analysis."
            )
        else:
            reason = (
                f"Spike detected (ATR {atr_ratio:.2f}x avg, volume {indicator_reading.volume_ratio:.2f}x avg) "
                f"but confluence doesn't confirm a direction (score {indicator_reading.confluence_score:.2f}). "
                f"Likely noise — not alerting."
            )

        return ScoutSignal(
            symbol=symbol,
            atr_spike=atr_spike,
            atr_ratio=round(atr_ratio, 2),
            volume_spike=volume_spike,
            volume_ratio=indicator_reading.volume_ratio,
            stage1_triggered=True,
            confluence_direction=indicator_reading.confluence_direction,
            confluence_score=indicator_reading.confluence_score,
            alertable=confluence_clears_bar,
            reason=reason,
        )


if __name__ == "__main__":
    import numpy as np

    # Synthetic test: calm market (should NOT trigger stage 1)
    dates = pd.date_range("2026-01-01", periods=250, freq="1h")
    np.random.seed(1)
    price = 60000 + np.cumsum(np.random.randn(250) * 20)  # low volatility
    calm_df = pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.randn(250) * 8),
        "low": price - np.abs(np.random.randn(250) * 8),
        "close": price + np.random.randn(250) * 4,
        "volume": np.abs(np.random.randn(250) * 50 + 500),  # steady volume
    })

    scout = ScoutAgent()
    signal = scout.scan("BTCUSDT_CALM", calm_df)
    print("Calm market test:")
    print(signal)
    print()

    # Synthetic test: volatility spike with trending direction at the end
    price2 = 60000 + np.cumsum(np.random.randn(250) * 20)
    price2[-15:] = price2[-16] + np.cumsum(np.abs(np.random.randn(15) * 150) + 100)  # sharp move up
    spike_df = pd.DataFrame({
        "open": price2,
        "high": price2 + np.abs(np.random.randn(250) * 8),
        "low": price2 - np.abs(np.random.randn(250) * 8),
        "close": price2 + np.random.randn(250) * 4,
        "volume": np.abs(np.random.randn(250) * 50 + 500),
    })
    spike_df.loc[spike_df.index[-10:], "volume"] *= 3  # volume spike too

    signal2 = scout.scan("BTCUSDT_SPIKE", spike_df)
    print("Volatility + volume spike test:")
    print(signal2)

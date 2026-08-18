"""
Live integration check — pulls real BTC/ETH data through the full
deterministic chain: pipeline -> indicator agent -> risk agent.

This is NOT the orchestrator yet (no scout threshold, no LLM layer). It's
a manual "does the whole pipe work end to end on real data" check.

Run from the project root: python3 run_live_check.py
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "data"))
sys.path.append(os.path.join(os.path.dirname(__file__), "agents"))
sys.path.append(os.path.join(os.path.dirname(__file__), "config"))

from pipeline import DataPipeline
from indicator_agent import IndicatorAgent
from risk_agent import RiskAgent
from scout_agent import ScoutAgent

# --- adjust these for your own test ---
ACCOUNT_SIZE_USD = 10000
MARKET_TYPE = "spot"  # or "leverage"
# ---------------------------------------


def main():
    pipeline = DataPipeline()
    indicator_agent = IndicatorAgent()
    risk_agent = RiskAgent()
    scout_agent = ScoutAgent()

    print("Fetching live snapshots for BTCUSDT and ETHUSDT...\n")
    snapshots = pipeline.get_all_snapshots()

    correlated_risk_used = 0.0  # tracks combined BTC+ETH risk budget across this run

    for symbol, snap in snapshots.items():
        print(f"{'=' * 50}")
        print(f"{symbol}  —  price: {snap.current_price}")
        print(f"{'=' * 50}")

        # Indicator agent needs enough candles for the 200-SMA
        reading = indicator_agent.analyze(symbol, snap.ohlcv_1h)
        print(f"RSI: {reading.rsi} ({reading.rsi_signal})")
        print(f"MACD: {reading.macd_signal} (hist: {reading.macd_histogram})")
        print(f"Trend: {reading.trend_signal}")
        print(f"ATR: {reading.atr} ({reading.atr_pct}% of price)")
        print(f"Volume: {reading.volume_signal} (ratio: {reading.volume_ratio}x)")
        print(f"Confluence: {reading.confluence_direction} (score: {reading.confluence_score})")
        print(f"  Agreeing signals: {reading.agreeing_signals}")
        print(f"  Conflicting signals: {reading.conflicting_signals}")

        # Scout gate: this is what actually decides whether the system
        # would alert you, in the real pipeline. Everything above is
        # context; this line is the verdict.
        scout_signal = scout_agent.scan(symbol, snap.ohlcv_1h, indicator_reading=reading)
        print(f"\nScout: {scout_signal.reason}")

        if not scout_signal.alertable:
            print("-> Not alertable. Skipping risk agent.\n")
            continue

        direction = "long" if reading.confluence_direction == "bullish" else "short"
        if MARKET_TYPE == "spot" and direction == "short":
            print("\n-> Bearish confluence but spot can't short. Skipping.\n")
            continue

        assessment = risk_agent.assess(
            symbol=symbol,
            direction=direction,
            entry_price=snap.current_price,
            atr=reading.atr,
            account_size=ACCOUNT_SIZE_USD,
            market_type=MARKET_TYPE,
            correlated_open_risk_pct=correlated_risk_used,
        )

        print(f"\n-> Proposed {direction} setup:")
        print(f"   Entry: {assessment.entry_price}")
        print(f"   Stop loss: {assessment.stop_loss}")
        print(f"   Take profit: {assessment.take_profit}")
        print(f"   R:R: {assessment.reward_risk_ratio}")
        print(f"   Position size: {assessment.position_size_units} {symbol[:3]} "
              f"(${assessment.position_size_usd}, {assessment.position_pct_of_account}% of account)")
        print(f"   Risk amount: ${assessment.risk_amount} ({assessment.risk_pct_used}% of account)")
        print(f"   Tradeable: {risk_agent.is_tradeable(assessment)}")
        if assessment.rejection_reasons:
            print(f"   Notes: {assessment.rejection_reasons}")
        print()

        if risk_agent.is_tradeable(assessment):
            correlated_risk_used += assessment.risk_pct_used

    print(f"{'=' * 50}")
    print("This run used the scout agent's real threshold — if nothing")
    print("above says 'alertable', that's correct behavior: no clear")
    print("opportunity right now, not a bug.")


if __name__ == "__main__":
    main()

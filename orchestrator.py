"""
Full end-to-end orchestrator — the actual system described in the
architecture diagram: data -> scout gate -> parallel FA/TA/indicator ->
risk -> decision -> email alert. Advisory only: never places a trade.

Requires ANTHROPIC_API_KEY (see .env.example) for the FA/TA/decision
agents. Email alerting requires ALERT_EMAIL_* vars in .env — optional,
the system still runs and prints to console without them.

The deterministic layer (pipeline, indicator, scout, risk) runs
regardless — if the scout doesn't trigger, no API calls happen at all,
keeping this cheap to run frequently (e.g. via cron every 15-60 min).

Run from the project root: python3 orchestrator.py
"""
import sys
import os
import json
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), "data"))
sys.path.append(os.path.join(os.path.dirname(__file__), "agents"))
sys.path.append(os.path.join(os.path.dirname(__file__), "config"))

from pipeline import DataPipeline
from indicator_agent import IndicatorAgent
from scout_agent import ScoutAgent
from risk_agent import RiskAgent
from notifier import EmailNotifier

ACCOUNT_SIZE_USD = 10000
MARKET_TYPE = "spot"
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "alerts.jsonl")


def log_alert(decision, risk_assessment):
    """Appends a JSON line per alert — this becomes your track record for
    reviewing accuracy later and eventually feeding Kelly Criterion sizing
    once you have ~50+ logged trades."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": decision.symbol,
        "direction": decision.direction,
        "verdict": decision.verdict,
        "entry_price": decision.entry_price,
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "reward_risk_ratio": decision.reward_risk_ratio,
        "position_size_usd": decision.position_size_usd,
        "risk_amount": decision.risk_amount,
        "explanation": decision.explanation,
        # outcome fields — fill these in manually (or build a review
        # script later) once the trade plays out, to build a track record
        "outcome": None,          # "win" | "loss" | "not_taken" | None
        "outcome_notes": "",
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_full_pipeline(symbol, snap, indicator_agent, scout_agent, risk_agent, correlated_risk_used):
    """Runs the deterministic chain; only reaches the LLM layer if alertable."""
    reading = indicator_agent.analyze(symbol, snap.ohlcv_1h)
    scout_signal = scout_agent.scan(symbol, snap.ohlcv_1h, indicator_reading=reading)

    print(f"\n{'=' * 50}\n{symbol} — price: {snap.current_price}\n{'=' * 50}")
    print(f"Scout: {scout_signal.reason}")

    if not scout_signal.alertable:
        return None

    direction = "long" if reading.confluence_direction == "bullish" else "short"
    if MARKET_TYPE == "spot" and direction == "short":
        print("-> Bearish confluence but spot can't short. Skipping.")
        return None

    risk_assessment = risk_agent.assess(
        symbol=symbol, direction=direction, entry_price=snap.current_price,
        atr=reading.atr, account_size=ACCOUNT_SIZE_USD, market_type=MARKET_TYPE,
        correlated_open_risk_pct=correlated_risk_used,
    )
    if not risk_agent.is_tradeable(risk_assessment):
        print(f"-> Risk agent rejected: {risk_assessment.rejection_reasons}")
        return None

    print("-> Scout + risk both clear. Running FA/TA/decision agents (LLM calls)...")

    # Import lazily so the deterministic-only path above never requires
    # ANTHROPIC_API_KEY to be set.
    from fa_agent import FAAgent
    from ta_agent import TAAgent
    from decision_agent import DecisionAgent

    fa_reading, ta_reading = None, None
    try:
        fa_reading = FAAgent().analyze(symbol, snap.market_context)
    except Exception as e:
        print(f"   FA agent failed ({e}) — continuing without it.")
    try:
        ta_reading = TAAgent().analyze(symbol, snap.ohlcv_1h)
    except Exception as e:
        print(f"   TA agent failed ({e}) — continuing without it.")

    decision = None
    try:
        decision = DecisionAgent().decide(
            symbol=symbol, direction=direction, indicator_reading=reading,
            risk_assessment=risk_assessment, fa_reading=fa_reading,
            ta_reading=ta_reading, scout_reason=scout_signal.reason,
        )
    except Exception as e:
        print(f"   Decision agent failed ({e}) — no verdict this run, nothing logged or emailed.")
        return None

    print(f"\n>>> VERDICT: {decision.verdict.upper()} <<<")
    print(f"{direction.upper()} {symbol} @ {decision.entry_price}")
    print(f"Stop: {decision.stop_loss}  Target: {decision.take_profit}  R:R: {decision.reward_risk_ratio}")
    print(f"Size: {decision.position_size_units} units (${decision.position_size_usd}, "
          f"risking ${decision.risk_amount})")
    print(f"\nReasoning: {decision.explanation}")
    print(f"Agreements: {decision.key_agreements}")
    print(f"Conflicts: {decision.key_conflicts}")
    print(f"Caveats: {decision.caveats}")

    log_alert(decision, risk_assessment)

    notifier = EmailNotifier()
    if notifier.enabled:
        sent = notifier.send_decision_alert(decision)
        print(f"\nEmail alert {'sent' if sent else 'FAILED to send'}.")
    else:
        print("\nEmail not configured (set ALERT_EMAIL_* in .env) — "
              "printed to console only.")

    return decision, risk_assessment.risk_pct_used


def main():
    pipeline = DataPipeline()
    indicator_agent = IndicatorAgent()
    scout_agent = ScoutAgent()
    risk_agent = RiskAgent()

    snapshots = pipeline.get_all_snapshots()
    correlated_risk_used = 0.0
    any_alert = False

    for symbol, snap in snapshots.items():
        result = run_full_pipeline(
            symbol, snap, indicator_agent, scout_agent, risk_agent, correlated_risk_used
        )
        if result:
            any_alert = True
            _, risk_pct = result
            correlated_risk_used += risk_pct

    if not any_alert:
        print(f"\n{'=' * 50}\nNo alertable setups this run. This is expected "
              "most of the time — no API calls were made.")


if __name__ == "__main__":
    main()
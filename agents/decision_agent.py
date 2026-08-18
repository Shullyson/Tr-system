"""
Decision agent — the final synthesis layer. LLM-based, but constrained:

  - It receives ALREADY-COMPUTED entry/stop/target/position-size numbers
    from the risk agent and ALREADY-COMPUTED indicator/scout/FA/TA readings.
  - Its job is ONLY to explain: which signals agreed, which conflicted, and
    why the numbers are what they are.
  - It NEVER generates a price, size, or stop level itself. If you find
    yourself wanting the LLM to "decide" a number, that's a bug — the
    number should already exist before this agent is called.

This is the layer that makes the earlier design principle concrete:
LLMs synthesize and explain, they don't do the math.
"""
from dataclasses import dataclass
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__)))
from llm_client import LLMClient

SYSTEM_PROMPT = """You are the final decision-explanation agent in an \
automated crypto trading advisory system. You are given the outputs of \
four independent agents (scout, indicator/confluence, fundamental \
analysis, technical analysis) plus an already-computed risk assessment \
(entry, stop-loss, take-profit, position size — all final, already \
calculated by a separate rule-based system).

Your ONLY job is to explain, in plain language, why this setup is or \
isn't worth the person's attention:
- Which signals agree with each other, and which conflict
- Whether the fundamental and technical pictures reinforce or contradict \
each other
- Any caveats the person should weigh before acting

STRICT RULES:
- You MUST use the exact entry/stop/target/position-size numbers given to \
you. Never alter, round differently, or recompute them.
- Never state a price, level, or size that was not explicitly given to you.
- Be honest about disagreement between agents — do not paper over \
conflicting signals to make the setup sound more convincing than it is.
- If confidence is genuinely mixed, say so plainly rather than picking a \
side for the sake of a clean narrative.

Respond in this exact JSON structure:
{
  "verdict": "high_conviction" | "moderate_conviction" | "low_conviction",
  "explanation": "<3-5 sentence plain-language explanation>",
  "key_agreements": [<string>, ...],
  "key_conflicts": [<string>, ...],
  "caveats": [<string>, ...]
}"""


@dataclass
class DecisionOutput:
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_risk_ratio: float
    position_size_units: float
    position_size_usd: float
    risk_amount: float
    verdict: str
    explanation: str
    key_agreements: list
    key_conflicts: list
    caveats: list


class DecisionAgent:
    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    def decide(self, symbol: str, direction: str, indicator_reading,
               risk_assessment, fa_reading=None, ta_reading=None,
               scout_reason: str = "") -> DecisionOutput:
        """
        All *_reading / *_assessment objects come from the earlier agents.
        fa_reading and ta_reading are optional — the system can still
        produce a decision from indicator + risk alone if the LLM layer
        for FA/TA isn't available or failed.
        """
        fa_block = (
            f"FA agent — bias: {fa_reading.bias}, confidence: {fa_reading.confidence}, "
            f"drivers: {fa_reading.key_drivers}, summary: {fa_reading.summary}"
            if fa_reading else "FA agent: not available for this run."
        )
        ta_block = (
            f"TA agent — structure bias: {ta_reading.structure_bias}, "
            f"resistance: {ta_reading.nearest_resistance}, support: {ta_reading.nearest_support}, "
            f"summary: {ta_reading.summary}"
            if ta_reading else "TA agent: not available for this run."
        )

        user_prompt = f"""Symbol: {symbol}
Scout trigger reason: {scout_reason}

Indicator agent — confluence: {indicator_reading.confluence_direction} \
(score {indicator_reading.confluence_score}), RSI: {indicator_reading.rsi} \
({indicator_reading.rsi_signal}), MACD: {indicator_reading.macd_signal}, \
trend: {indicator_reading.trend_signal}
  Agreeing signals: {indicator_reading.agreeing_signals}
  Conflicting signals: {indicator_reading.conflicting_signals}

{fa_block}

{ta_block}

FINAL RISK ASSESSMENT (already computed, do not alter):
  Direction: {direction}
  Entry: {risk_assessment.entry_price}
  Stop-loss: {risk_assessment.stop_loss}
  Take-profit: {risk_assessment.take_profit}
  Reward:risk ratio: {risk_assessment.reward_risk_ratio}
  Position size: {risk_assessment.position_size_units} units \
(${risk_assessment.position_size_usd}, {risk_assessment.position_pct_of_account}% of account)
  Risk amount: ${risk_assessment.risk_amount} ({risk_assessment.risk_pct_used}% of account)
  Market type: {risk_assessment.market_type}

Explain this setup."""

        result = self.llm.call_json(SYSTEM_PROMPT, user_prompt, max_tokens=800)

        return DecisionOutput(
            symbol=symbol,
            direction=direction,
            entry_price=risk_assessment.entry_price,
            stop_loss=risk_assessment.stop_loss,
            take_profit=risk_assessment.take_profit,
            reward_risk_ratio=risk_assessment.reward_risk_ratio,
            position_size_units=risk_assessment.position_size_units,
            position_size_usd=risk_assessment.position_size_usd,
            risk_amount=risk_assessment.risk_amount,
            verdict=result.get("verdict", "low_conviction"),
            explanation=result.get("explanation", ""),
            key_agreements=result.get("key_agreements", []),
            key_conflicts=result.get("key_conflicts", []),
            caveats=result.get("caveats", []),
        )

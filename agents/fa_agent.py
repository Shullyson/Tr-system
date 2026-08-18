"""
FA (fundamental analysis) agent — LLM-based.
Fundamentals are inherently narrative (news, macro, on-chain context), so
this is one of the few places an LLM is the right tool. But output is
constrained to structured JSON (bias + confidence + key_drivers), not
freeform prose, so the decision agent downstream can reason over it
reliably rather than re-parsing paragraphs.

This agent NEVER outputs a price, entry, or trade recommendation — that
would blur the line into the risk agent's territory. It only assesses
directional bias and how confident that bias is.
"""
from dataclasses import dataclass, field
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "data"))
sys.path.append(os.path.join(os.path.dirname(__file__)))

from llm_client import LLMClient
from news_fetcher import get_recent_headlines

SYSTEM_PROMPT = """You are a fundamental analysis agent inside an automated \
crypto trading advisory system. Your job is to assess directional bias \
based on fundamentals ONLY — news sentiment, macro context, market \
structure (market cap, dominance, distance from ATH). You do NOT analyze \
price charts or technical indicators; another agent handles that.

Rules:
- Never state a price target, entry price, or specific trade recommendation.
- Base your bias strictly on the data provided. If the data is thin or \
ambiguous, say so and lower your confidence accordingly — do not \
compensate for missing data with speculation.
- confidence must reflect how much the provided data actually supports \
your bias, not how confident you feel in general.
- key_drivers must be specific to the data given, not generic market \
commentary.

Respond in this exact JSON structure:
{
  "bias": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0 to 1.0>,
  "key_drivers": [<string>, ...],
  "summary": "<1-2 sentence plain-language summary>"
}"""


@dataclass
class FAReading:
    symbol: str
    bias: str
    confidence: float
    key_drivers: list = field(default_factory=list)
    summary: str = ""
    headlines_used: int = 0


class FAAgent:
    def __init__(self, llm_client: LLMClient = None):
        self.llm = llm_client or LLMClient()

    def analyze(self, symbol: str, market_context: dict) -> FAReading:
        """
        market_context: the dict returned by CoinGeckoClient.get_coin_market_data()
        — market cap, 24h/7d/30d price change, ATH distance, etc.
        """
        headlines = get_recent_headlines(symbol)
        headlines_text = (
            "\n".join(f"- {h['title']}" for h in headlines)
            if headlines else "No recent relevant headlines found."
        )

        mc = market_context
        user_prompt = f"""Symbol: {symbol}

Market context (from CoinGecko):
- Market cap: {mc.get('market_cap_usd', 'N/A')}
- Market cap rank: {mc.get('market_cap_rank', 'N/A')}
- 24h price change: {mc.get('price_change_pct_24h', 'N/A')}%
- 7d price change: {mc.get('price_change_pct_7d', 'N/A')}%
- 30d price change: {mc.get('price_change_pct_30d', 'N/A')}%
- Distance from ATH: {mc.get('ath_change_pct', 'N/A')}%

Recent headlines:
{headlines_text}

Assess fundamental bias based on this data."""

        result = self.llm.call_json(SYSTEM_PROMPT, user_prompt)

        return FAReading(
            symbol=symbol,
            bias=result.get("bias", "neutral"),
            confidence=float(result.get("confidence", 0.0)),
            key_drivers=result.get("key_drivers", []),
            summary=result.get("summary", ""),
            headlines_used=len(headlines),
        )


if __name__ == "__main__":
    agent = FAAgent()
    mock_context = {
        "market_cap_usd": 1264764194638,
        "market_cap_rank": 1,
        "price_change_pct_24h": 0.04,
        "price_change_pct_7d": -2.95,
        "price_change_pct_30d": -0.07,
        "ath_change_pct": -50.02,
    }
    reading = agent.analyze("BTCUSDT", mock_context)
    print(reading)

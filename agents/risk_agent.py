"""
Risk agent — fully rule-based, no LLM involved.
Takes a proposed direction from the indicator/confluence layer and turns it
into concrete numbers: stop-loss, take-profit, position size, and a pass/
fail on whether the setup even clears your minimum reward-to-risk bar.

This agent NEVER invents a price level from narrative reasoning — every
number here is computed directly from ATR and account size. The decision
agent (LLM layer, built later) explains these numbers; it doesn't generate them.
"""
from dataclasses import dataclass
from typing import Optional
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "config"))
from settings import RISK_CONFIG as CFG


@dataclass
class RiskAssessment:
    symbol: str
    direction: str              # 'long' | 'short'
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_risk_ratio: float
    passes_min_rr: bool
    account_size: float
    risk_amount: float           # $ amount risked if stop is hit
    position_size_units: float   # e.g. how much BTC/ETH to buy
    position_size_usd: float
    risk_pct_used: float
    market_type: str             # 'spot' | 'leverage'
    position_pct_of_account: float
    position_capped_by_market_type: bool
    rejection_reasons: list


class RiskAgent:
    def __init__(self, config: dict = None):
        self.cfg = config or CFG

    def assess(
        self,
        symbol: str,
        direction: str,           # 'long' or 'short'
        entry_price: float,
        atr: float,
        account_size: float,
        market_type: str = "spot",  # 'spot' or 'leverage'
        take_profit: Optional[float] = None,
        correlated_open_risk_pct: float = 0.0,
    ) -> RiskAssessment:
        """
        If take_profit isn't supplied, it's derived from the stop distance
        using the minimum required reward:risk ratio — i.e. the smallest
        target that would still clear your bar, not a guess.

        market_type matters because risk-based position sizing (risk_amount
        / stop_distance) can imply a notional position larger than your
        account holds. On spot that's impossible — you can't buy more than
        you have. On leverage it's possible but should stay bounded by a
        deliberate cap, not whatever the stop distance happens to imply.
        """
        direction = direction.lower()
        if direction not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")
        market_type = market_type.lower()
        if market_type not in ("spot", "leverage"):
            raise ValueError("market_type must be 'spot' or 'leverage'")
        if market_type == "spot" and direction == "short":
            raise ValueError("Spot mode can't short — that needs margin/leverage")

        rejection_reasons = []

        stop_distance = atr * self.cfg["atr_stop_multiplier"]
        if direction == "long":
            stop_loss = entry_price - stop_distance
        else:
            stop_loss = entry_price + stop_distance

        if take_profit is None:
            reward_distance = stop_distance * self.cfg["min_reward_risk_ratio"]
            take_profit = (
                entry_price + reward_distance if direction == "long"
                else entry_price - reward_distance
            )

        reward = abs(take_profit - entry_price)
        risk = abs(entry_price - stop_loss)
        rr_ratio = reward / risk if risk > 0 else 0.0
        passes_min_rr = rr_ratio >= self.cfg["min_reward_risk_ratio"]
        if not passes_min_rr:
            rejection_reasons.append(
                f"R:R {rr_ratio:.2f} below minimum {self.cfg['min_reward_risk_ratio']}"
            )

        # Position sizing off fixed-fractional risk cap
        available_risk_pct = self.cfg["max_risk_per_trade_pct"]
        # If BTC/ETH already have correlated exposure open, shrink what's left
        remaining_correlated_budget = max(
            0.0, self.cfg["max_correlated_risk_pct"] - correlated_open_risk_pct
        )
        risk_pct_used = min(available_risk_pct, remaining_correlated_budget)
        if risk_pct_used <= 0:
            rejection_reasons.append("Correlated risk budget (BTC+ETH) already exhausted")

        risk_amount = account_size * (risk_pct_used / 100)
        position_size_units = risk_amount / risk if risk > 0 else 0.0
        position_size_usd = position_size_units * entry_price

        # Cap notional position size by market type — risk-based sizing
        # alone doesn't know spot has no leverage.
        max_position_pct = (
            self.cfg["spot_max_position_pct"] if market_type == "spot"
            else self.cfg["leverage_max_position_pct"]
        )
        max_position_usd = account_size * (max_position_pct / 100)
        position_capped = position_size_usd > max_position_usd
        if position_capped:
            position_size_usd = max_position_usd
            position_size_units = position_size_usd / entry_price
            # Actual $ at risk is now bounded by the capped position, not
            # the original risk_pct target — recompute honestly.
            risk_amount = position_size_units * risk
            risk_pct_used = (risk_amount / account_size) * 100
            # NOTE: this is a resize, not a rejection — the trade is still
            # valid, just smaller than the risk-based math wanted. It does
            # NOT go into rejection_reasons (which gates is_tradeable()).

        position_pct_of_account = (position_size_usd / account_size) * 100 if account_size > 0 else 0.0

        return RiskAssessment(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            reward_risk_ratio=round(rr_ratio, 2),
            passes_min_rr=passes_min_rr,
            account_size=account_size,
            risk_amount=round(risk_amount, 2),
            position_size_units=round(position_size_units, 6),
            position_size_usd=round(position_size_usd, 2),
            risk_pct_used=round(risk_pct_used, 3),
            market_type=market_type,
            position_pct_of_account=round(position_pct_of_account, 2),
            position_capped_by_market_type=position_capped,
            rejection_reasons=rejection_reasons,
        )

    def is_tradeable(self, assessment: RiskAssessment) -> bool:
        """Final gate: only true if it cleared every check with no rejections."""
        return assessment.passes_min_rr and len(assessment.rejection_reasons) == 0


if __name__ == "__main__":
    agent = RiskAgent()

    # Spot mode: tight ATR relative to price means risk-based sizing wants
    # a bigger position than the account can actually fund — should get
    # capped at 100% of account, not silently allowed to exceed it.
    result = agent.assess(
        symbol="BTCUSDT",
        direction="long",
        entry_price=63000,
        atr=500,
        account_size=10000,
        market_type="spot",
    )
    print("Spot BTC setup (tight stop, sizing should be capped):")
    print(result)
    print("Tradeable:", agent.is_tradeable(result))
    print("Was position capped by spot rule?", result.position_capped_by_market_type)

    # Same setup in leverage mode — same risk $ amount, but the position
    # cap is higher (300% of account) so more of the risk-implied size
    # actually gets used before hitting the ceiling.
    result_lev = agent.assess(
        symbol="BTCUSDT",
        direction="long",
        entry_price=63000,
        atr=500,
        account_size=10000,
        market_type="leverage",
    )
    print("\nSame setup in leverage mode:")
    print(result_lev)
    print("Tradeable:", agent.is_tradeable(result_lev))

    # Spot mode attempting a short — should raise, spot can't short
    print("\nAttempting a spot short (should raise):")
    try:
        agent.assess(
            symbol="BTCUSDT", direction="short", entry_price=63000,
            atr=500, account_size=10000, market_type="spot",
        )
    except ValueError as e:
        print(f"Correctly rejected: {e}")

    # Correlated risk example: ETH setup after BTC risk budget already used
    result2 = agent.assess(
        symbol="ETHUSDT",
        direction="long",
        entry_price=1880,
        atr=25,
        account_size=10000,
        market_type="spot",
        correlated_open_risk_pct=2.0,  # already at the cap from the BTC trade
    )
    print("\nCorrelated setup after BTC+ETH risk budget exhausted (should be rejected):")
    print(result2)
    print("Tradeable:", agent.is_tradeable(result2))

"""
Central config for risk and indicator parameters.
Defaults are grounded in commonly cited retail risk-management research —
see comments below for reasoning. All values are meant to be tuned once you
have real paper-trading data, not treated as gospel.
"""

RISK_CONFIG = {
    # Fixed-fractional risk cap: % of total account equity risked on ONE trade.
    # 2% is the commonly cited "optimal" ceiling for retail traders in
    # position-sizing literature. Using 1.5% here since this system has zero
    # track record yet — start slightly more conservative, raise later if
    # backtests/paper trading justify it.
    "max_risk_per_trade_pct": 1.5,

    # Minimum reward-to-risk ratio required to flag a setup as a valid
    # opportunity at all. 1:2 is the standard baseline — at this ratio a
    # ~40-50% win rate is already profitable, so you don't need to win most
    # trades to come out ahead over time.
    "min_reward_risk_ratio": 2.0,

    # ATR multiplier for stop-loss distance. 1.5x ATR is a common starting
    # point: tight enough to cap losses, wide enough to not get stopped out
    # by normal noise. Tune per-symbol once you have real trade data.
    "atr_stop_multiplier": 1.5,

    # If BTC and ETH both trigger a setup in the same direction at the same
    # time, treat them as correlated exposure rather than two independent
    # bets — cap combined risk rather than letting risk double.
    "max_correlated_risk_pct": 2.0,

    # Kelly Criterion becomes available once you have this many closed
    # trades logged — smaller samples carry too much estimation error to
    # trust a Kelly-derived position size.
    "min_trades_for_kelly": 50,
    "kelly_fraction": 0.5,  # half-Kelly: most of the growth, less drawdown

    # Spot has no leverage — you cannot deploy more capital than you hold,
    # full stop. This caps position notional as a % of account size
    # regardless of what the risk-based sizing math would otherwise suggest
    # (a tight stop can imply a large position; spot can't fund that).
    "spot_max_position_pct": 100.0,   # never more than 100% of account in one spot position

    # Leverage mode: still capped, but allows using borrowed capital up to
    # a multiple of account size. Keep conservative — this isn't a
    # recommendation to use high leverage, just a ceiling if you choose to.
    "leverage_max_position_pct": 300.0,  # e.g. 3x max notional exposure
    "leverage_max_multiplier": 3.0,
}

INDICATOR_CONFIG = {
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "sma_periods": [20, 50, 200],
    "volume_ma_period": 20,
    "volume_spike_multiplier": 1.5,  # volume > 1.5x its own MA = notable
}

SCOUT_CONFIG = {
    # Volatility spike: current ATR vs its own recent average, not a fixed
    # number — ATR itself drifts (we saw ~0.1% of price in a calm market),
    # so "notable" has to be relative to recent conditions, not absolute.
    "atr_lookback_period": 20,       # rolling window ATR is compared against
    "atr_spike_multiplier": 1.3,     # current ATR > 1.3x its own 20-period average

    # Volume spike reuses the indicator agent's own volume_ratio field —
    # no need to recompute, just apply a scout-level threshold to it.
    "volume_spike_multiplier": 1.5,

    # Once a spike triggers a closer look, confluence must clear this bar
    # to count as a real, alertable opportunity (not just noise on a
    # volatile tick). Deliberately stricter than "any lean" — 0.5 requires
    # at least 2 of 3 indicator signals agreeing with no contradiction, or
    # all 3 partially aligned.
    "min_confluence_for_alert": 0.5,
}

LLM_CONFIG = {
    # Balanced model for structured reasoning tasks — FA synthesis, TA
    # summary, decision explanation. Requires ANTHROPIC_API_KEY in your
    # project-root .env file.
    "model": "claude-sonnet-5",
    "max_tokens": 1000,
    "temperature": 0.2,  # low temperature: consistency matters more than
                          # creativity for financial reasoning output
}

EMAIL_CONFIG = {
    # Gmail SMTP — requires a Gmail App Password (not your normal
    # password): https://myaccount.google.com/apppasswords
    # All values below are read from environment variables (.env), never
    # hardcoded here.
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_env_var": "ALERT_EMAIL_SENDER",
    "app_password_env_var": "ALERT_EMAIL_APP_PASSWORD",
    "recipient_env_var": "ALERT_EMAIL_RECIPIENT",
}

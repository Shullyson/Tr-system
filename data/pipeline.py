"""
Unified market data pipeline.
Combines Binance (price/execution data) + CoinGecko (context data) into
a single snapshot per symbol, ready to hand to the agent layer.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import pandas as pd

from binance_client import BinanceClient
from coingecko_client import CoinGeckoClient

PAIRS = ["BTCUSDT", "ETHUSDT"]


@dataclass
class MarketSnapshot:
    symbol: str
    timestamp: datetime
    current_price: float
    ohlcv_1h: pd.DataFrame
    ohlcv_4h: pd.DataFrame
    ticker_24h: dict
    order_book: dict
    market_context: dict = field(default_factory=dict)


class DataPipeline:
    def __init__(self, coingecko_api_key: str = None):
        self.binance = BinanceClient()
        self.coingecko = CoinGeckoClient(api_key=coingecko_api_key)

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        """
        Pull everything the agent layer needs for one symbol in one call.
        Binance gives execution-quality price data; CoinGecko fills in
        market cap / dominance / broader context the FA agent wants.
        """
        # 250, not 200: the indicator agent needs a buffer above its longest
        # lookback (200-period SMA) or the SMA has no valid data at the
        # start of its own window and the whole calculation is invalid.
        current_price = self.binance.get_current_price(symbol)
        ohlcv_1h = self.binance.get_klines(symbol, interval="1h", limit=250)
        ohlcv_4h = self.binance.get_klines(symbol, interval="4h", limit=250)
        ticker_24h = self.binance.get_ticker_24h(symbol)
        order_book = self.binance.get_order_book(symbol, limit=20)

        try:
            market_context = self.coingecko.get_coin_market_data(symbol)
        except Exception as e:
            # CoinGecko is supplementary context, not execution-critical —
            # don't let a rate limit or outage kill the whole snapshot.
            market_context = {"error": str(e)}

        return MarketSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            current_price=current_price,
            ohlcv_1h=ohlcv_1h,
            ohlcv_4h=ohlcv_4h,
            ticker_24h=ticker_24h,
            order_book=order_book,
            market_context=market_context,
        )

    def get_all_snapshots(self, symbols: list = None) -> dict:
        symbols = symbols or PAIRS
        return {sym: self.get_snapshot(sym) for sym in symbols}

    def get_global_context(self) -> dict:
        """One-off macro call — call this less often than per-symbol snapshots."""
        return self.coingecko.get_global_market_data()


if __name__ == "__main__":
    pipeline = DataPipeline()
    snapshots = pipeline.get_all_snapshots()
    for sym, snap in snapshots.items():
        print(f"\n=== {sym} ===")
        print(f"Price: {snap.current_price}")
        print(f"24h change: {snap.ticker_24h.get('priceChangePercent')}%")
        print(f"Market context: {snap.market_context}")
        print(snap.ohlcv_1h.tail(3))

    print("\n=== Global ===")
    print(pipeline.get_global_context())

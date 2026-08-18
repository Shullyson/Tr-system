"""
Binance public REST API client.
No API key needed for market data endpoints (klines, ticker, depth).
Docs: https://developers.binance.com/docs/binance-spot-api-docs
"""
import requests
import pandas as pd
from datetime import datetime, timezone

BASE_URL = "https://api.binance.com"


class BinanceClient:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame:
        """
        Fetch OHLCV candles.
        symbol: e.g. 'BTCUSDT', 'ETHUSDT'
        interval: '1m','5m','15m','1h','4h','1d', etc.
        limit: max 1000 per call
        """
        raw = self._get("/api/v3/klines", {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        })
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "num_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ]
        df = pd.DataFrame(raw, columns=cols)
        for c in ["open", "high", "low", "close", "volume", "quote_asset_volume"]:
            df[c] = df[c].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        # The last row is the currently-forming candle — its close_time is
        # still in the future, meaning its volume/OHLC are partial (e.g. 5
        # minutes into a 1h candle). Every indicator that reads volume or
        # the latest close assumes a COMPLETE candle, so an in-progress one
        # silently corrupts volume ratios (this is why you saw 0.03x-0.06x
        # instead of a plausible number) and can shift RSI/MACD/ATR too.
        # Drop it — the last row returned is always the most recent CLOSED
        # candle.
        now = pd.Timestamp.now(tz="UTC")
        df = df[df["close_time"] <= now].reset_index(drop=True)

        return df[["open_time", "open", "high", "low", "close", "volume", "num_trades", "close_time"]]

    def get_ticker_24h(self, symbol: str) -> dict:
        """24h rolling stats: price change %, volume, high/low."""
        return self._get("/api/v3/ticker/24hr", {"symbol": symbol.upper()})

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Top-of-book depth snapshot. limit: 5,10,20,50,100,500,1000."""
        return self._get("/api/v3/depth", {"symbol": symbol.upper(), "limit": limit})

    def get_current_price(self, symbol: str) -> float:
        data = self._get("/api/v3/ticker/price", {"symbol": symbol.upper()})
        return float(data["price"])

    def server_time(self) -> datetime:
        data = self._get("/api/v3/time")
        return datetime.fromtimestamp(data["serverTime"] / 1000, tz=timezone.utc)


if __name__ == "__main__":
    client = BinanceClient()
    print("Server time:", client.server_time())
    for sym in ["BTCUSDT", "ETHUSDT"]:
        price = client.get_current_price(sym)
        print(f"{sym} price: {price}")
        df = client.get_klines(sym, interval="1h", limit=5)
        print(df.tail())

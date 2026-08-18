"""
CoinGecko public REST API client.
Free tier: 50 calls/min, no key required (some endpoints need a demo key
for higher limits — see https://www.coingecko.com/en/api/pricing).
Used here for context data that Binance doesn't provide: market cap,
dominance, broader sentiment signals — NOT for price execution data.
"""
import requests
import time

BASE_URL = "https://api.coingecko.com/api/v3"

# Binance symbols -> CoinGecko coin ids
SYMBOL_TO_ID = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
}


class CoinGeckoClient:
    def __init__(self, api_key: str = None, timeout: int = 10):
        self.timeout = timeout
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"x-cg-demo-api-key": api_key})

    def _get(self, path: str, params: dict = None, retries: int = 2) -> dict:
        url = f"{BASE_URL}{path}"
        for attempt in range(retries + 1):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 429 and attempt < retries:
                time.sleep(2 ** attempt)  # simple backoff on rate limit
                continue
            resp.raise_for_status()
            return resp.json()

    def get_coin_market_data(self, symbol: str) -> dict:
        """Market cap, volume, price change %, ATH/ATL, circulating supply."""
        coin_id = SYMBOL_TO_ID.get(symbol.upper())
        if not coin_id:
            raise ValueError(f"No CoinGecko mapping for {symbol}")
        data = self._get(f"/coins/{coin_id}", {
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
        })
        md = data["market_data"]
        return {
            "id": coin_id,
            "market_cap_usd": md["market_cap"].get("usd"),
            "market_cap_rank": data.get("market_cap_rank"),
            "total_volume_usd": md["total_volume"].get("usd"),
            "price_change_pct_24h": md.get("price_change_percentage_24h"),
            "price_change_pct_7d": md.get("price_change_percentage_7d"),
            "price_change_pct_30d": md.get("price_change_percentage_30d"),
            "ath_usd": md["ath"].get("usd"),
            "ath_change_pct": md["ath_change_percentage"].get("usd"),
            "circulating_supply": md.get("circulating_supply"),
        }

    def get_global_market_data(self) -> dict:
        """Total crypto market cap, BTC/ETH dominance — useful macro context."""
        data = self._get("/global")["data"]
        return {
            "total_market_cap_usd": data["total_market_cap"].get("usd"),
            "market_cap_change_pct_24h": data.get("market_cap_change_percentage_24h_usd"),
            "btc_dominance_pct": data["market_cap_percentage"].get("btc"),
            "eth_dominance_pct": data["market_cap_percentage"].get("eth"),
        }

    def get_trending(self) -> list:
        """Top trending coins on CoinGecko right now — soft sentiment signal."""
        data = self._get("/search/trending")
        return [item["item"]["symbol"] for item in data.get("coins", [])]


if __name__ == "__main__":
    client = CoinGeckoClient()
    print("Global market:", client.get_global_market_data())
    for sym in ["BTCUSDT", "ETHUSDT"]:
        print(f"\n{sym}:", client.get_coin_market_data(sym))

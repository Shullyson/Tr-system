"""
Lightweight news fetcher for FA agent context.
Uses public RSS feeds — no API key required. Filters headlines by keyword
relevance to BTC/ETH so the FA agent isn't fed unrelated crypto noise.
"""
import feedparser

FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

KEYWORDS = {
    "BTCUSDT": ["bitcoin", "btc"],
    "ETHUSDT": ["ethereum", "eth"],
}


def get_recent_headlines(symbol: str, max_items: int = 8) -> list:
    """
    Returns a list of {title, published, source} dicts relevant to the
    given symbol, most recent first. Best-effort: if a feed fails to
    fetch, it's skipped rather than raising — news is context, not
    execution-critical, so one dead feed shouldn't break the FA agent.
    """
    keywords = KEYWORDS.get(symbol.upper(), [])
    if not keywords:
        return []

    headlines = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", feed_url)
            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                if any(kw in title.lower() for kw in keywords):
                    headlines.append({
                        "title": title,
                        "published": entry.get("published", ""),
                        "source": source,
                    })
        except Exception:
            continue  # one dead feed shouldn't break the whole fetch

    return headlines[:max_items]


if __name__ == "__main__":
    for sym in ["BTCUSDT", "ETHUSDT"]:
        print(f"\n=== {sym} headlines ===")
        for h in get_recent_headlines(sym):
            print(f"- {h['title']} ({h['source']})")

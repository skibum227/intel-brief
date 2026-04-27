"""News connector — RSS regulatory feeds, NewsAPI, and SEC EDGAR 8-K filings."""
import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

log = logging.getLogger("intel_brief")


_REGULATORY_FEEDS = [
    ("CFPB",            "https://www.consumerfinance.gov/about-us/newsroom/feed/"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("OCC",             "https://www.occ.gov/news-issuances/news-releases/rss.xml"),
    ("FDIC",            "https://www.fdic.gov/bank/individual/failed/banklist.rss"),
]

_EDGAR_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={ticker}&type=8-K&dateb=&owner=include&count=10&output=atom"
)

_NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _parse_date(entry) -> datetime | None:
    """Try to extract a timezone-aware datetime from a feed entry."""
    for field in ("published", "updated"):
        val = getattr(entry, field, None)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def _fetch_rss(name: str, url: str, since: datetime) -> list[dict]:
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries:
            pub = _parse_date(entry)
            if pub and pub < since:
                continue
            items.append({
                "source": name,
                "title": entry.get("title", "").strip(),
                "summary": entry.get("summary", entry.get("description", "")).strip()[:400],
                "url": entry.get("link", ""),
                "published_at": pub.isoformat() if pub else None,
                "type": "regulatory",
            })
        return items
    except Exception as e:
        log.warning(f"[News] RSS fetch failed for {name}: {e}")
        return []


def _fetch_edgar(ticker: str, since: datetime) -> list[dict]:
    try:
        url = _EDGAR_URL.format(ticker=ticker)
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries:
            pub = _parse_date(entry)
            if pub and pub < since:
                continue
            items.append({
                "source": f"SEC EDGAR ({ticker})",
                "title": entry.get("title", "").strip(),
                "summary": entry.get("summary", "").strip()[:400],
                "url": entry.get("link", ""),
                "published_at": pub.isoformat() if pub else None,
                "type": "sec_filing",
            })
        return items
    except Exception as e:
        log.warning(f"[News] EDGAR fetch failed for {ticker}: {e}")
        return []


def _fetch_newsapi(keywords: list[str], since: datetime) -> list[dict]:
    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        return []
    try:
        query = " OR ".join(f'"{k}"' if " " in k else k for k in keywords)
        resp = requests.get(
            _NEWSAPI_URL,
            params={
                "q": query,
                "from": since.strftime("%Y-%m-%dT%H:%M:%S"),
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = []
        for article in resp.json().get("articles", []):
            items.append({
                "source": article.get("source", {}).get("name", "News"),
                "title": article.get("title", "").strip(),
                "summary": (article.get("description") or "").strip()[:400],
                "url": article.get("url", ""),
                "published_at": article.get("publishedAt"),
                "type": "news",
            })
        return items
    except Exception as e:
        log.warning(f"[News] NewsAPI fetch failed: {e}")
        return []


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    news_cfg = config.get("news", {})
    if not news_cfg.get("enabled", True):
        return []

    results = []

    # Regulatory RSS feeds
    for name, url in _REGULATORY_FEEDS:
        results.extend(_fetch_rss(name, url, since))

    # Custom RSS feeds from config
    for feed in news_cfg.get("rss_feeds", []):
        results.extend(_fetch_rss(feed["name"], feed["url"], since))

    # SEC EDGAR 8-K filings
    for ticker in news_cfg.get("edgar_tickers", ["AFRM", "SQ", "PYPL"]):
        results.extend(_fetch_edgar(ticker, since))

    # NewsAPI
    keywords = news_cfg.get("keywords", [
        "Affirm", "Afterpay", "Klarna", "BNPL",
        "buy now pay later", "consumer credit", "fintech regulation",
    ])
    results.extend(_fetch_newsapi(keywords, since))

    return results

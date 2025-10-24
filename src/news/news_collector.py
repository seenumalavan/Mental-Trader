"""
News collection and aggregation system for market sentiment analysis.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp
import feedparser
from dataclasses import dataclass
from enum import Enum

from src.config import settings
from src.utils.time_utils import IST

logger = logging.getLogger("news_collector")

class NewsSource(Enum):
    ALPHA_VANTAGE = "alpha_vantage"
    NEWSAPI = "newsapi"
    YAHOO_FINANCE = "yahoo_finance"
    SEEKING_ALPHA = "seeking_alpha"
    TWITTER = "twitter"
    REDDIT = "reddit"

@dataclass
class NewsItem:
    """Represents a news item with metadata."""
    title: str
    content: str
    source: str
    symbol: str
    published_at: datetime
    url: Optional[str] = None
    sentiment_score: Optional[float] = None
    confidence: Optional[float] = None
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

class NewsCollector:
    """Collects news from multiple sources for market sentiment analysis."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.sources = {
            NewsSource.ALPHA_VANTAGE: self._fetch_alpha_vantage,
            NewsSource.NEWSAPI: self._fetch_newsapi,
            NewsSource.YAHOO_FINANCE: self._fetch_yahoo_finance,
            NewsSource.TWITTER: self._fetch_twitter,
            NewsSource.REDDIT: self._fetch_reddit,
        }

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def collect_news(self, symbols: List[str], hours_back: int = 24) -> List[NewsItem]:
        """Collect news from all configured sources."""
        if not self.session:
            self.session = aiohttp.ClientSession()

        cutoff_time = datetime.now(IST) - timedelta(hours=hours_back)
        all_news = []

        # Collect from enabled sources
        enabled_sources = self._get_enabled_sources()

        for source in enabled_sources:
            try:
                logger.debug(f"Collecting news from {source.value}")
                news_items = await self.sources[source](symbols, cutoff_time)
                all_news.extend(news_items)
                logger.info(f"Collected {len(news_items)} items from {source.value}")
            except Exception as e:
                logger.warning(f"Failed to collect from {source.value}: {e}")

        # Deduplicate and sort by published time
        deduplicated = self._deduplicate_news(all_news)
        sorted_news = sorted(deduplicated, key=lambda x: x.published_at, reverse=True)

        logger.info(f"Total news items collected: {len(sorted_news)}")
        return sorted_news

    def _get_enabled_sources(self) -> List[NewsSource]:
        """Get list of enabled news sources based on configuration."""
        enabled = []

        if getattr(settings, 'ALPHA_VANTAGE_API_KEY', None):
            enabled.append(NewsSource.ALPHA_VANTAGE)

        if getattr(settings, 'NEWSAPI_KEY', None):
            enabled.append(NewsSource.NEWSAPI)

        if getattr(settings, 'TWITTER_BEARER_TOKEN', None):
            enabled.append(NewsSource.TWITTER)

        # Always enable Yahoo Finance and Reddit as they don't require API keys
        enabled.extend([NewsSource.YAHOO_FINANCE, NewsSource.REDDIT])

        return enabled

    async def _fetch_alpha_vantage(self, symbols: List[str], cutoff_time: datetime) -> List[NewsItem]:
        """Fetch news from Alpha Vantage API."""
        news_items = []
        api_key = getattr(settings, 'ALPHA_VANTAGE_API_KEY', None)

        if not api_key:
            return news_items

        base_url = "https://www.alphavantage.co/query"

        for symbol in symbols:
            try:
                params = {
                    "function": "NEWS_SENTIMENT",
                    "tickers": symbol,
                    "apikey": api_key,
                    "limit": 50
                }

                async with self.session.get(base_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        if "feed" in data:
                            for item in data["feed"]:
                                published_at = datetime.fromisoformat(item["time_published"][:19])

                                if published_at >= cutoff_time:
                                    news_item = NewsItem(
                                        title=item["title"],
                                        content=item["summary"],
                                        source="Alpha Vantage",
                                        symbol=symbol,
                                        published_at=published_at,
                                        url=item.get("url"),
                                        sentiment_score=float(item.get("overall_sentiment_score", 0)),
                                        confidence=float(item.get("overall_sentiment_label", 0))
                                    )
                                    news_items.append(news_item)

            except Exception as e:
                logger.warning(f"Error fetching Alpha Vantage news for {symbol}: {e}")

        return news_items

    async def _fetch_newsapi(self, symbols: List[str], cutoff_time: datetime) -> List[NewsItem]:
        """Fetch news from NewsAPI."""
        news_items = []
        api_key = getattr(settings, 'NEWSAPI_KEY', None)

        if not api_key:
            return news_items

        base_url = "https://newsapi.org/v2/everything"

        for symbol in symbols:
            try:
                # Search for company news
                query = f'"{symbol}" AND (stock OR shares OR market OR trading)'
                params = {
                    "q": query,
                    "apiKey": api_key,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 20,
                    "from": cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
                }

                async with self.session.get(base_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()

                        if "articles" in data:
                            for article in data["articles"]:
                                published_at = datetime.fromisoformat(article["publishedAt"].replace('Z', '+00:00'))

                                if published_at >= cutoff_time:
                                    news_item = NewsItem(
                                        title=article["title"],
                                        content=article.get("description", ""),
                                        source="NewsAPI",
                                        symbol=symbol,
                                        published_at=published_at,
                                        url=article.get("url")
                                    )
                                    news_items.append(news_item)

            except Exception as e:
                logger.warning(f"Error fetching NewsAPI news for {symbol}: {e}")

        return news_items

    async def _fetch_yahoo_finance(self, symbols: List[str], cutoff_time: datetime) -> List[NewsItem]:
        """Fetch news from Yahoo Finance RSS feeds."""
        news_items = []

        for symbol in symbols:
            try:
                # Yahoo Finance RSS feed for company news
                rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"

                async with self.session.get(rss_url) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)

                        for entry in feed.entries[:10]:  # Limit to 10 most recent
                            published_at = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else datetime.now(IST)

                            if published_at >= cutoff_time:
                                news_item = NewsItem(
                                    title=entry.title,
                                    content=getattr(entry, 'summary', ''),
                                    source="Yahoo Finance",
                                    symbol=symbol,
                                    published_at=published_at,
                                    url=entry.link
                                )
                                news_items.append(news_item)

            except Exception as e:
                logger.warning(f"Error fetching Yahoo Finance news for {symbol}: {e}")

        return news_items

    async def _fetch_twitter(self, symbols: List[str], cutoff_time: datetime) -> List[NewsItem]:
        """Fetch Twitter mentions (placeholder - requires Twitter API v2)."""
        # This would require Twitter API v2 Bearer Token
        # Implementation would use Twitter API v2 recent search endpoint
        logger.debug("Twitter news collection not implemented (requires API setup)")
        return []

    async def _fetch_reddit(self, symbols: List[str], cutoff_time: datetime) -> List[NewsItem]:
        """Fetch Reddit mentions from relevant subreddits."""
        news_items = []
        subreddits = ["r/india", "r/IndianStreetBets", "r/stocks"]

        for subreddit in subreddits:
            try:
                # Reddit API doesn't require authentication for basic access
                api_url = f"https://www.reddit.com/{subreddit}/search.json"
                params = {
                    "q": " OR ".join(symbols),
                    "sort": "new",
                    "limit": 25,
                    "t": "day"  # Last 24 hours
                }

                async with self.session.get(api_url, params=params, headers={'User-Agent': 'Mental-Trader/1.0'}) as response:
                    if response.status == 200:
                        data = await response.json()

                        if "data" in data and "children" in data["data"]:
                            for post in data["data"]["children"]:
                                post_data = post["data"]
                                created_at = datetime.fromtimestamp(post_data["created_utc"])

                                if created_at >= cutoff_time:
                                    # Check if post mentions any of our symbols
                                    text = f"{post_data['title']} {post_data.get('selftext', '')}"
                                    mentioned_symbols = [s for s in symbols if s.lower() in text.lower()]

                                    if mentioned_symbols:
                                        news_item = NewsItem(
                                            title=post_data["title"],
                                            content=post_data.get("selftext", "")[:500],  # Limit content length
                                            source=f"Reddit {subreddit}",
                                            symbol=mentioned_symbols[0],  # Use first mentioned symbol
                                            published_at=created_at,
                                            url=f"https://reddit.com{post_data['permalink']}",
                                            tags=["social", "reddit"]
                                        )
                                        news_items.append(news_item)

            except Exception as e:
                logger.warning(f"Error fetching Reddit news from {subreddit}: {e}")

        return news_items

    def _deduplicate_news(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """Remove duplicate news items based on title similarity."""
        seen_titles = set()
        deduplicated = []

        for item in news_items:
            # Simple deduplication based on title
            title_key = item.title.lower().strip()

            if title_key not in seen_titles:
                seen_titles.add(title_key)
                deduplicated.append(item)

        return deduplicated

    async def get_latest_news(self, symbols: List[str], limit: int = 50) -> List[NewsItem]:
        """Get latest news items across all sources."""
        all_news = await self.collect_news(symbols, hours_back=6)  # Last 6 hours
        return all_news[:limit]
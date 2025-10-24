"""
Sentiment processing service that coordinates news collection, analysis, and integration.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.config import settings
from src.news.news_collector import NewsCollector, NewsItem
from src.news.sentiment_analyzer import SentimentAnalyzer, SentimentResult
from src.news.impact_analyzer import MarketImpactAnalyzer, ImpactAssessment
from src.persistence.db import Database
from src.utils.time_utils import IST

logger = logging.getLogger("sentiment_service")

@dataclass
class SentimentSnapshot:
    """Current sentiment state for a symbol."""
    symbol: str
    current_sentiment: float
    confidence: float
    news_count: int
    last_update: datetime
    trend: str  # improving, deteriorating, stable

class SentimentService:
    """Main service for sentiment analysis and news processing."""

    def __init__(self):
        self.db = Database(settings.DATABASE_URL)
        self.news_collector = NewsCollector()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.impact_analyzer = MarketImpactAnalyzer()

        # In-memory cache
        self._sentiment_cache: Dict[str, SentimentSnapshot] = {}
        self._last_update = datetime.now(IST)

        # Background task
        self._running = False
        self._update_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the sentiment service."""
        if self._running:
            return

        await self.db.connect()
        self._running = True
        self._update_task = asyncio.create_task(self._background_update_loop())

        logger.info("Sentiment service started")

    async def stop(self):
        """Stop the sentiment service."""
        if not self._running:
            return

        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        await self.db.disconnect()
        logger.info("Sentiment service stopped")

    async def _background_update_loop(self):
        """Background loop to update sentiment data."""
        while self._running:
            try:
                await self._update_sentiment_data()
                await asyncio.sleep(300)  # Update every 5 minutes
            except Exception as e:
                logger.error(f"Error in sentiment update loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry

    async def _update_sentiment_data(self):
        """Update sentiment data for tracked symbols."""
        # Get symbols from current trading services
        # This would integrate with the main app to get active symbols
        symbols = await self._get_active_symbols()

        if not symbols:
            return

        # Collect recent news
        async with self.news_collector:
            news_items = await self.news_collector.collect_news(symbols, hours_back=6)

        if not news_items:
            return

        # Analyze sentiment
        sentiment_results = await self.sentiment_analyzer.analyze_sentiment(news_items)

        # Store in database
        await self._store_news_and_sentiment(news_items, sentiment_results)

        # Update cache
        self._update_sentiment_cache(symbols, news_items)

        logger.info(f"Updated sentiment data for {len(symbols)} symbols with {len(news_items)} news items")

    async def _get_active_symbols(self) -> List[str]:
        """Get currently active trading symbols."""
        # This would query the main app or services to get active symbols
        # For now, return some default symbols
        return ["RELIANCE", "TCS", "INFY", "HDFC", "ICICIBANK"]

    async def _store_news_and_sentiment(self, news_items: List[NewsItem], sentiment_results: Dict[str, SentimentResult]):
        """Store news and sentiment data in database."""
        try:
            # Create news tables if they don't exist
            await self._ensure_news_tables()

            # Store news items
            for item in news_items:
                await self.db.execute("""
                    INSERT INTO news_items
                    (symbol, title, content, source, url, published_at, collected_at,
                     sentiment_score, sentiment_confidence, sentiment_model)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (symbol, title, published_at) DO NOTHING
                """, (
                    item.symbol,
                    item.title,
                    item.content,
                    item.source,
                    item.url,
                    item.published_at,
                    datetime.now(IST),
                    item.sentiment_score,
                    item.confidence,
                    sentiment_results.get(f"{item.symbol}_{item.published_at.isoformat()}", SentimentResult(0, 0, "none")).model
                ))

            # Store sentiment history
            for symbol in set(item.symbol for item in news_items):
                symbol_news = [item for item in news_items if item.symbol == symbol]
                if symbol_news:
                    avg_sentiment = sum(item.sentiment_score or 0 for item in symbol_news) / len(symbol_news)
                    avg_confidence = sum(item.confidence or 0 for item in symbol_news) / len(symbol_news)

                    await self.db.execute("""
                        INSERT INTO sentiment_history
                        (symbol, timeframe, sentiment_score, news_count, confidence, timestamp)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, (
                        symbol,
                        "1h",  # Hourly sentiment
                        avg_sentiment,
                        len(symbol_news),
                        avg_confidence,
                        datetime.now(IST)
                    ))

        except Exception as e:
            logger.error(f"Failed to store news and sentiment data: {e}")

    async def _ensure_news_tables(self):
        """Ensure news-related tables exist."""
        try:
            # News items table
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS news_items (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    source VARCHAR(100),
                    url TEXT,
                    published_at TIMESTAMP NOT NULL,
                    collected_at TIMESTAMP DEFAULT NOW(),
                    sentiment_score FLOAT,
                    sentiment_confidence FLOAT,
                    sentiment_model VARCHAR(50),
                    price_impact FLOAT,
                    volatility_impact FLOAT,
                    impact_confidence FLOAT,
                    tags TEXT[],
                    relevance_score FLOAT,
                    UNIQUE(symbol, title, published_at)
                )
            """)

            # Sentiment history table
            await self.db.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_history (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    timeframe VARCHAR(10) NOT NULL,
                    sentiment_score FLOAT NOT NULL,
                    news_count INTEGER NOT NULL,
                    confidence FLOAT NOT NULL,
                    timestamp TIMESTAMP NOT NULL
                )
            """)

            # Create indexes
            await self.db.execute("CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_items(symbol)")
            await self.db.execute("CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at)")
            await self.db.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_symbol ON sentiment_history(symbol)")
            await self.db.execute("CREATE INDEX IF NOT EXISTS idx_sentiment_timestamp ON sentiment_history(timestamp)")

        except Exception as e:
            logger.error(f"Failed to create news tables: {e}")

    def _update_sentiment_cache(self, symbols: List[str], news_items: List[NewsItem]):
        """Update in-memory sentiment cache."""
        for symbol in symbols:
            symbol_news = [item for item in news_items if item.symbol == symbol]
            if symbol_news:
                avg_sentiment = sum(item.sentiment_score or 0 for item in symbol_news) / len(symbol_news)
                avg_confidence = sum(item.confidence or 0 for item in symbol_news) / len(symbol_news)

                # Determine trend
                previous = self._sentiment_cache.get(symbol)
                if previous:
                    if avg_sentiment > previous.current_sentiment + 0.1:
                        trend = "improving"
                    elif avg_sentiment < previous.current_sentiment - 0.1:
                        trend = "deteriorating"
                    else:
                        trend = "stable"
                else:
                    trend = "stable"

                self._sentiment_cache[symbol] = SentimentSnapshot(
                    symbol=symbol,
                    current_sentiment=avg_sentiment,
                    confidence=avg_confidence,
                    news_count=len(symbol_news),
                    last_update=datetime.now(IST),
                    trend=trend
                )

        self._last_update = datetime.now(IST)

    async def get_symbol_sentiment(self, symbol: str) -> Optional[SentimentSnapshot]:
        """Get current sentiment for a symbol."""
        # Check cache first
        if symbol in self._sentiment_cache:
            snapshot = self._sentiment_cache[symbol]
            # Check if cache is still fresh (within 10 minutes)
            if (datetime.now(IST) - snapshot.last_update).total_seconds() < 600:
                return snapshot

        # Query database for recent sentiment
        try:
            result = await self.db.fetch("""
                SELECT sentiment_score, news_count, confidence, timestamp
                FROM sentiment_history
                WHERE symbol = $1 AND timestamp >= $2
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol, datetime.now(IST) - timedelta(hours=1)))

            if result:
                row = result[0]
                return SentimentSnapshot(
                    symbol=symbol,
                    current_sentiment=row['sentiment_score'],
                    confidence=row['confidence'],
                    news_count=row['news_count'],
                    last_update=row['timestamp'],
                    trend="unknown"  # Would need historical comparison
                )

        except Exception as e:
            logger.warning(f"Failed to get sentiment for {symbol}: {e}")

        return None

    async def get_market_sentiment(self) -> float:
        """Get overall market sentiment across major indices."""
        # This would aggregate sentiment across NIFTY, SENSEX, etc.
        # For now, return average of major stocks
        major_symbols = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

        sentiments = []
        for symbol in major_symbols:
            snapshot = await self.get_symbol_sentiment(symbol)
            if snapshot:
                sentiments.append(snapshot.current_sentiment)

        if sentiments:
            return sum(sentiments) / len(sentiments)

        return 0.0  # Neutral sentiment

    async def analyze_news_impact(self, symbol: str, news_title: str, news_content: str) -> ImpactAssessment:
        """Analyze the market impact of specific news."""
        news_item = NewsItem(
            title=news_title,
            content=news_content,
            source="manual",
            symbol=symbol,
            published_at=datetime.now(IST)
        )

        return await self.impact_analyzer.assess_impact(news_item)

    async def get_recent_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        """Get recent news for a symbol."""
        try:
            results = await self.db.fetch("""
                SELECT symbol, title, content, source, url, published_at,
                       sentiment_score, sentiment_confidence, sentiment_model
                FROM news_items
                WHERE symbol = $1
                ORDER BY published_at DESC
                LIMIT $2
            """, (symbol, limit))

            news_items = []
            for row in results:
                news_items.append(NewsItem(
                    title=row['title'],
                    content=row['content'],
                    source=row['source'],
                    symbol=row['symbol'],
                    published_at=row['published_at'],
                    url=row['url'],
                    sentiment_score=row['sentiment_score'],
                    confidence=row['sentiment_confidence']
                ))

            return news_items

        except Exception as e:
            logger.error(f"Failed to get recent news for {symbol}: {e}")
            return []

    async def get_sentiment_alerts(self) -> List[Dict]:
        """Get sentiment-based alerts."""
        alerts = []

        for symbol, snapshot in self._sentiment_cache.items():
            # Check for extreme sentiment
            if abs(snapshot.current_sentiment) > 0.7 and snapshot.confidence > 0.6:
                alerts.append({
                    "type": "extreme_sentiment",
                    "symbol": symbol,
                    "sentiment": snapshot.current_sentiment,
                    "confidence": snapshot.confidence,
                    "message": f"Extreme {'bullish' if snapshot.current_sentiment > 0 else 'bearish'} sentiment detected"
                })

            # Check for sentiment trend changes
            if snapshot.trend in ["improving", "deteriorating"]:
                alerts.append({
                    "type": "sentiment_trend",
                    "symbol": symbol,
                    "trend": snapshot.trend,
                    "sentiment": snapshot.current_sentiment,
                    "message": f"Sentiment {snapshot.trend} for {symbol}"
                })

        return alerts
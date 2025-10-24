"""
Sentiment-based signal filtering for enhanced trading decisions.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from src.services.sentiment_service import SentimentService, SentimentSnapshot
from src.utils.time_utils import IST

logger = logging.getLogger("sentiment_filter")

class SentimentFilter:
    """Filter trading signals based on market sentiment analysis."""

    def __init__(self, sentiment_service: SentimentService):
        self.sentiment_service = sentiment_service

        # Configuration
        self.min_confidence = 0.6  # Minimum sentiment confidence to apply filter
        self.sentiment_threshold = 0.3  # Minimum absolute sentiment score to consider
        self.enable_extreme_sentiment_block = True  # Block signals when extreme sentiment detected
        self.enable_sentiment_alignment = True  # Require sentiment alignment with signal direction

    async def filter_signal(self, symbol: str, side: str, price: float) -> Dict:
        """Filter a trading signal based on sentiment analysis.

        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            price: Current price

        Returns:
            Dict with 'allowed', 'reasons', 'sentiment_score', 'confidence'
        """
        try:
            # Get current sentiment
            sentiment = await self.sentiment_service.get_symbol_sentiment(symbol)

            if not sentiment:
                # No sentiment data available, allow signal
                return {
                    "allowed": True,
                    "reasons": ["No sentiment data available"],
                    "sentiment_score": 0.0,
                    "confidence": 0.0
                }

            reasons = []
            allowed = True

            # Check sentiment confidence
            if sentiment.confidence < self.min_confidence:
                reasons.append(f"Low sentiment confidence: {sentiment.confidence:.2f}")
                # Allow but note low confidence
            else:
                # Check for extreme sentiment blocking
                if self.enable_extreme_sentiment_block:
                    if abs(sentiment.current_sentiment) > 0.8:
                        allowed = False
                        direction = "bullish" if sentiment.current_sentiment > 0 else "bearish"
                        reasons.append(f"Extreme {direction} sentiment detected ({sentiment.current_sentiment:.2f})")

                # Check sentiment alignment
                if self.enable_sentiment_alignment and abs(sentiment.current_sentiment) > self.sentiment_threshold:
                    sentiment_direction = "bullish" if sentiment.current_sentiment > 0 else "bearish"
                    signal_direction = "bullish" if side == "BUY" else "bearish"

                    if sentiment_direction != signal_direction:
                        # Sentiment opposes signal direction
                        if abs(sentiment.current_sentiment) > 0.5:
                            allowed = False
                            reasons.append(f"Sentiment opposes signal: {sentiment_direction} vs {signal_direction}")
                        else:
                            reasons.append(f"Weak sentiment alignment: {sentiment.current_sentiment:.2f}")

            return {
                "allowed": allowed,
                "reasons": reasons,
                "sentiment_score": sentiment.current_sentiment,
                "confidence": sentiment.confidence,
                "news_count": sentiment.news_count,
                "trend": sentiment.trend
            }

        except Exception as e:
            logger.error(f"Error in sentiment filtering for {symbol}: {e}")
            return {
                "allowed": True,  # Allow on error to not block trading
                "reasons": [f"Sentiment filter error: {str(e)}"],
                "sentiment_score": 0.0,
                "confidence": 0.0
            }

    async def get_sentiment_context(self, symbol: str) -> Dict:
        """Get comprehensive sentiment context for decision making."""
        try:
            sentiment = await self.sentiment_service.get_symbol_sentiment(symbol)
            recent_news = await self.sentiment_service.get_recent_news(symbol, limit=5)

            if not sentiment:
                return {
                    "available": False,
                    "sentiment_score": 0.0,
                    "confidence": 0.0,
                    "news_count": 0,
                    "recent_news": []
                }

            # Analyze news sentiment distribution
            news_sentiments = [news.sentiment_score for news in recent_news if news.sentiment_score is not None]
            sentiment_distribution = {
                "positive": len([s for s in news_sentiments if s > 0.1]),
                "negative": len([s for s in news_sentiments if s < -0.1]),
                "neutral": len([s for s in news_sentiments if -0.1 <= s <= 0.1])
            }

            return {
                "available": True,
                "sentiment_score": sentiment.current_sentiment,
                "confidence": sentiment.confidence,
                "news_count": sentiment.news_count,
                "trend": sentiment.trend,
                "last_update": sentiment.last_update.isoformat(),
                "sentiment_distribution": sentiment_distribution,
                "recent_news": [
                    {
                        "title": news.title,
                        "sentiment": news.sentiment_score,
                        "source": news.source,
                        "published_at": news.published_at.isoformat()
                    }
                    for news in recent_news[:3]  # Top 3 most recent
                ]
            }

        except Exception as e:
            logger.error(f"Error getting sentiment context for {symbol}: {e}")
            return {
                "available": False,
                "error": str(e)
            }

    async def should_wait_for_better_sentiment(self, symbol: str, side: str) -> Dict:
        """Check if we should wait for better sentiment alignment."""
        try:
            sentiment = await self.sentiment_service.get_symbol_sentiment(symbol)

            if not sentiment or sentiment.confidence < self.min_confidence:
                return {
                    "should_wait": False,
                    "reason": "Insufficient sentiment data"
                }

            signal_direction = 1 if side == "BUY" else -1
            sentiment_alignment = sentiment.current_sentiment * signal_direction

            # If sentiment strongly opposes the signal, suggest waiting
            if sentiment_alignment < -0.3 and abs(sentiment.current_sentiment) > 0.4:
                return {
                    "should_wait": True,
                    "reason": f"Strong opposing sentiment ({sentiment.current_sentiment:.2f})",
                    "suggested_wait_minutes": 30
                }

            # If sentiment is neutral but trending in wrong direction
            if abs(sentiment.current_sentiment) < 0.2 and sentiment.trend == "deteriorating":
                return {
                    "should_wait": True,
                    "reason": "Neutral sentiment trending negatively",
                    "suggested_wait_minutes": 15
                }

            return {
                "should_wait": False,
                "reason": "Sentiment conditions acceptable"
            }

        except Exception as e:
            logger.error(f"Error checking sentiment wait conditions for {symbol}: {e}")
            return {
                "should_wait": False,
                "reason": f"Error: {str(e)}"
            }

    def update_config(self, **kwargs):
        """Update filter configuration."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.info(f"Updated sentiment filter config: {key} = {value}")

class SentimentAwareSignalConfirmation:
    """Enhanced signal confirmation that includes sentiment analysis."""

    def __init__(self, sentiment_service: SentimentService):
        self.sentiment_filter = SentimentFilter(sentiment_service)

    async def confirm_signal_with_sentiment(
        self,
        symbol: str,
        side: str,
        price: float,
        ema_state,
        recent_bars: List[Dict],
        daily_ref: Dict,
        rsi_period: int = 14,
        require_cpr: bool = False
    ) -> Dict:
        """Confirm signal with both technical and sentiment analysis.

        This wraps the existing confirm_signal function and adds sentiment filtering.
        """
        # First get technical confirmation (would import and call existing function)
        # For now, simulate basic technical checks
        technical_ok = True
        technical_reasons = []
        technical_scores = {}

        # Add basic RSI check
        if recent_bars:
            closes = [b.get("close", 0) for b in recent_bars[-rsi_period:]]
            if len(closes) >= rsi_period:
                # Simple RSI calculation
                gains = []
                losses = []
                for i in range(1, len(closes)):
                    change = closes[i] - closes[i-1]
                    gains.append(max(change, 0))
                    losses.append(max(-change, 0))

                avg_gain = sum(gains) / len(gains) if gains else 0
                avg_loss = sum(losses) / len(losses) if losses else 0

                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                    technical_scores["rsi"] = rsi

                    if side == "BUY" and rsi > 70:
                        technical_ok = False
                        technical_reasons.append("RSI overbought")
                    elif side == "SELL" and rsi < 30:
                        technical_ok = False
                        technical_reasons.append("RSI oversold")

        # Get sentiment confirmation
        sentiment_result = await self.sentiment_filter.filter_signal(symbol, side, price)

        # Combine results
        overall_confirmed = technical_ok and sentiment_result["allowed"]

        reasons = technical_reasons + sentiment_result["reasons"]

        result = {
            "confirmed": overall_confirmed,
            "reasons": reasons,
            "technical_scores": technical_scores,
            "sentiment_score": sentiment_result["sentiment_score"],
            "sentiment_confidence": sentiment_result["confidence"],
            "sentiment_allowed": sentiment_result["allowed"],
            "news_count": sentiment_result.get("news_count", 0),
            "sentiment_trend": sentiment_result.get("trend", "unknown")
        }

        logger.info(f"Sentiment-aware confirmation for {symbol} {side}: {overall_confirmed} - {reasons}")
        return result
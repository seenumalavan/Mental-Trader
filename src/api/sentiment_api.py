"""
API endpoints for sentiment analysis and news features.
"""

import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.services.sentiment_service import SentimentService
from src.engine.sentiment_filter import SentimentFilter

logger = logging.getLogger("sentiment_api")

# Create router
router = APIRouter(prefix="/sentiment", tags=["sentiment"])

# Global service instances (would be initialized in main app)
sentiment_service: Optional[SentimentService] = None
sentiment_filter: Optional[SentimentFilter] = None

def init_sentiment_services(service: SentimentService, filter_instance: SentimentFilter):
    """Initialize sentiment services for the API."""
    global sentiment_service, sentiment_filter
    sentiment_service = service
    sentiment_filter = filter_instance

# Request/Response models
class SentimentAnalysisRequest(BaseModel):
    symbol: str
    side: str  # "BUY" or "SELL"
    price: float

class NewsImpactRequest(BaseModel):
    symbol: str
    title: str
    content: str

class SentimentContextResponse(BaseModel):
    available: bool
    sentiment_score: float
    confidence: float
    news_count: int
    trend: str
    last_update: Optional[str]
    sentiment_distribution: Optional[Dict[str, int]]
    recent_news: List[Dict]

class SentimentFilterResponse(BaseModel):
    allowed: bool
    reasons: List[str]
    sentiment_score: float
    confidence: float
    news_count: int
    trend: str

class NewsItemResponse(BaseModel):
    title: str
    content: Optional[str]
    source: str
    symbol: str
    published_at: str
    sentiment_score: Optional[float]
    confidence: Optional[float]
    url: Optional[str]

class MarketSentimentResponse(BaseModel):
    sentiment_score: float
    confidence: float
    news_count: int
    timestamp: str

class SentimentAlertResponse(BaseModel):
    type: str
    symbol: Optional[str]
    severity: str
    message: str
    sentiment_score: Optional[float]
    confidence: Optional[float]
    news_count: Optional[int]
    timestamp: str

@router.get("/health")
async def sentiment_health():
    """Check sentiment service health."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    return {
        "status": "healthy",
        "service": "sentiment_analysis",
        "features": ["news_collection", "sentiment_analysis", "impact_assessment", "signal_filtering"]
    }

@router.get("/symbol/{symbol}", response_model=SentimentContextResponse)
async def get_symbol_sentiment(symbol: str):
    """Get current sentiment context for a symbol."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        context = await sentiment_service.get_sentiment_context(symbol)
        return SentimentContextResponse(**context)
    except Exception as e:
        logger.error(f"Error getting sentiment for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get sentiment: {str(e)}")

@router.post("/filter", response_model=SentimentFilterResponse)
async def filter_signal(request: SentimentAnalysisRequest):
    """Filter a trading signal based on sentiment analysis."""
    if not sentiment_filter:
        raise HTTPException(status_code=503, detail="Sentiment filter not initialized")

    try:
        result = await sentiment_filter.filter_signal(request.symbol, request.side, request.price)
        return SentimentFilterResponse(**result)
    except Exception as e:
        logger.error(f"Error filtering signal for {request.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to filter signal: {str(e)}")

@router.get("/news/{symbol}")
async def get_symbol_news(
    symbol: str,
    limit: int = Query(10, ge=1, le=50, description="Number of news items to return")
):
    """Get recent news for a symbol."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        news_items = await sentiment_service.get_recent_news(symbol, limit)

        response = []
        for item in news_items:
            response.append({
                "title": item.title,
                "content": item.content,
                "source": item.source,
                "symbol": item.symbol,
                "published_at": item.published_at.isoformat(),
                "sentiment_score": item.sentiment_score,
                "confidence": item.confidence,
                "url": item.url
            })

        return {"symbol": symbol, "news_count": len(response), "news": response}

    except Exception as e:
        logger.error(f"Error getting news for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get news: {str(e)}")

@router.post("/impact")
async def analyze_news_impact(request: NewsImpactRequest):
    """Analyze the market impact of specific news."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        impact = await sentiment_service.analyze_news_impact(
            request.symbol, request.title, request.content
        )

        return {
            "symbol": request.symbol,
            "title": request.title,
            "impact_assessment": {
                "price_direction": impact.price_direction,
                "price_impact_percent": impact.price_impact_percent,
                "volatility_change": impact.volatility_change,
                "confidence": impact.confidence,
                "time_horizon": impact.time_horizon,
                "trading_recommendations": impact.trading_recommendations,
                "key_factors": impact.key_factors
            }
        }

    except Exception as e:
        logger.error(f"Error analyzing news impact: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze impact: {str(e)}")

@router.get("/market")
async def get_market_sentiment():
    """Get overall market sentiment."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        sentiment_score = await sentiment_service.get_market_sentiment()

        return {
            "market_sentiment": sentiment_score,
            "interpretation": "bullish" if sentiment_score > 0.2 else "bearish" if sentiment_score < -0.2 else "neutral",
            "timestamp": sentiment_service._last_update.isoformat() if sentiment_service._last_update else None
        }

    except Exception as e:
        logger.error(f"Error getting market sentiment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get market sentiment: {str(e)}")

@router.get("/alerts")
async def get_sentiment_alerts():
    """Get current sentiment-based alerts."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        alerts = await sentiment_service.get_sentiment_alerts()

        response_alerts = []
        for alert in alerts:
            response_alerts.append({
                "type": alert["type"],
                "symbol": alert.get("symbol"),
                "severity": "high" if abs(alert.get("sentiment_score", 0)) > 0.7 else "medium",
                "message": alert["message"],
                "sentiment_score": alert.get("sentiment_score"),
                "confidence": alert.get("confidence"),
                "news_count": alert.get("news_count"),
                "timestamp": sentiment_service._last_update.isoformat() if sentiment_service._last_update else None
            })

        return {"alerts_count": len(response_alerts), "alerts": response_alerts}

    except Exception as e:
        logger.error(f"Error getting sentiment alerts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get alerts: {str(e)}")

@router.get("/wait-check/{symbol}")
async def check_wait_conditions(
    symbol: str,
    side: str = Query(..., description="BUY or SELL")
):
    """Check if we should wait for better sentiment conditions."""
    if not sentiment_filter:
        raise HTTPException(status_code=503, detail="Sentiment filter not initialized")

    try:
        result = await sentiment_filter.should_wait_for_better_sentiment(symbol, side)
        return result

    except Exception as e:
        logger.error(f"Error checking wait conditions for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check wait conditions: {str(e)}")

@router.get("/stats")
async def get_sentiment_stats():
    """Get sentiment analysis statistics."""
    if not sentiment_service:
        raise HTTPException(status_code=503, detail="Sentiment service not initialized")

    try:
        # Get basic stats from cache
        active_symbols = len(sentiment_service._sentiment_cache)
        total_news_collected = sum(snapshot.news_count for snapshot in sentiment_service._sentiment_cache.values())

        # Get database stats
        db = sentiment_service.db
        news_count = await db.fetchval("SELECT COUNT(*) FROM news_items")
        sentiment_records = await db.fetchval("SELECT COUNT(*) FROM sentiment_history")

        return {
            "active_symbols": active_symbols,
            "cached_news_count": total_news_collected,
            "total_news_in_db": news_count or 0,
            "sentiment_records": sentiment_records or 0,
            "last_update": sentiment_service._last_update.isoformat() if sentiment_service._last_update else None,
            "service_running": sentiment_service._running
        }

    except Exception as e:
        logger.error(f"Error getting sentiment stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
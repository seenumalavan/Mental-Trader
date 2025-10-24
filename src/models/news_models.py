"""
Pydantic models for news and sentiment data structures.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class NewsSource(str, Enum):
    ALPHA_VANTAGE = "alpha_vantage"
    NEWSAPI = "newsapi"
    YAHOO_FINANCE = "yahoo_finance"
    SEEKING_ALPHA = "seeking_alpha"
    TWITTER = "twitter"
    REDDIT = "reddit"
    MANUAL = "manual"

class SentimentModel(str, Enum):
    FINBERT = "finbert"
    TWITTER = "twitter"
    OPENAI = "openai"
    HYBRID = "hybrid"
    BASIC = "basic"

class NewsItemModel(BaseModel):
    """News item data model."""
    id: Optional[int] = None
    symbol: str = Field(..., description="Trading symbol (e.g., RELIANCE, NIFTY)")
    title: str = Field(..., description="News headline")
    content: str = Field(..., description="Full news content or summary")
    source: NewsSource = Field(..., description="News source")
    url: Optional[str] = Field(None, description="Original news URL")
    published_at: datetime = Field(..., description="Publication timestamp")
    collected_at: Optional[datetime] = Field(None, description="When we collected this news")

    # Sentiment analysis results
    sentiment_score: Optional[float] = Field(None, ge=-1, le=1, description="Sentiment score (-1 to +1)")
    sentiment_confidence: Optional[float] = Field(None, ge=0, le=1, description="Confidence in sentiment analysis")
    sentiment_model: Optional[SentimentModel] = Field(None, description="Model used for sentiment analysis")

    # Impact analysis
    price_impact: Optional[float] = Field(None, ge=-1, le=1, description="Expected price impact")
    volatility_impact: Optional[float] = Field(None, ge=-1, le=1, description="Expected volatility change")
    impact_confidence: Optional[float] = Field(None, ge=0, le=1, description="Confidence in impact assessment")

    # Metadata
    tags: List[str] = Field(default_factory=list, description="News tags/categories")
    relevance_score: Optional[float] = Field(None, ge=0, le=1, description="Relevance to trading")

    class Config:
        from_attributes = True

class SentimentHistoryModel(BaseModel):
    """Historical sentiment data for symbols."""
    id: Optional[int] = None
    symbol: str
    timeframe: str = Field(..., description="Timeframe (1m, 5m, 1h, 1d)")
    sentiment_score: float = Field(ge=-1, le=1)
    news_count: int = Field(ge=0, description="Number of news items analyzed")
    confidence: float = Field(ge=0, le=1, description="Average confidence score")
    timestamp: datetime

    class Config:
        from_attributes = True

class MarketSentimentModel(BaseModel):
    """Overall market sentiment snapshot."""
    id: Optional[int] = None
    market_index: str = Field(..., description="Market index (NIFTY, SENSEX, etc.)")
    sentiment_score: float = Field(ge=-1, le=1)
    volatility_index: Optional[float] = Field(None, description="VIX or similar")
    news_volume: int = Field(ge=0, description="Total news items in period")
    timestamp: datetime

    class Config:
        from_attributes = True

class NewsCollectionRequest(BaseModel):
    """Request model for news collection."""
    symbols: List[str] = Field(..., description="List of symbols to collect news for")
    hours_back: int = Field(24, ge=1, le=168, description="Hours of historical news to collect")
    sources: Optional[List[NewsSource]] = Field(None, description="Specific sources to use")
    include_sentiment: bool = Field(True, description="Whether to analyze sentiment")

class SentimentAnalysisRequest(BaseModel):
    """Request model for sentiment analysis."""
    news_items: List[int] = Field(..., description="News item IDs to analyze")
    model: SentimentModel = Field(SentimentModel.FINBERT, description="Sentiment model to use")
    force_reanalysis: bool = Field(False, description="Re-analyze already processed items")

class ImpactAnalysisRequest(BaseModel):
    """Request model for impact analysis."""
    news_item_id: int = Field(..., description="News item to analyze")
    current_price: Optional[float] = Field(None, description="Current market price for context")
    include_trading_recommendation: bool = Field(True, description="Include AI trading recommendation")

class NewsFilterRequest(BaseModel):
    """Request model for filtering news."""
    symbols: Optional[List[str]] = None
    sources: Optional[List[NewsSource]] = None
    sentiment_min: Optional[float] = Field(None, ge=-1, le=1)
    sentiment_max: Optional[float] = Field(None, ge=-1, le=1)
    impact_min: Optional[float] = Field(None, ge=-1, le=1)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    limit: int = Field(100, ge=1, le=1000)
    sort_by: str = Field("published_at", description="Sort field")
    sort_order: str = Field("desc", description="Sort order (asc/desc)")

class NewsAlertConfig(BaseModel):
    """Configuration for news alerts."""
    enabled: bool = True
    symbols: List[str] = Field(..., description="Symbols to monitor")
    sentiment_threshold: float = Field(0.5, ge=0, le=1, description="Minimum sentiment score for alerts")
    impact_threshold: float = Field(0.3, ge=0, le=1, description="Minimum impact score for alerts")
    keywords: List[str] = Field(default_factory=list, description="Keywords to trigger alerts")
    alert_channels: List[str] = Field(["email"], description="Alert channels (email, webhook, etc.)")

# Response models
class NewsResponse(BaseModel):
    """Response model for news queries."""
    items: List[NewsItemModel]
    total_count: int
    filtered_count: int
    sentiment_summary: Optional[dict] = None

class SentimentResponse(BaseModel):
    """Response model for sentiment analysis."""
    analyzed_count: int
    success_count: int
    errors: List[str] = Field(default_factory=list)
    average_sentiment: Optional[float] = None
    average_confidence: Optional[float] = None

class ImpactResponse(BaseModel):
    """Response model for impact analysis."""
    news_item: NewsItemModel
    impact_assessment: dict
    trading_recommendation: Optional[dict] = None
    circuit_breaker_triggered: bool = False
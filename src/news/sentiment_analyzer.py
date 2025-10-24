"""
Sentiment analysis system using multiple NLP models for market news.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np

try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
    from openai import OpenAI
    import torch
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    print("WARNING: transformers not available, sentiment analysis will be limited")

from src.config import settings
from src.news.news_collector import NewsItem

logger = logging.getLogger("sentiment_analyzer")

@dataclass
class SentimentResult:
    """Result of sentiment analysis."""
    score: float  # -1 (bearish) to +1 (bullish)
    confidence: float  # 0 to 1
    model: str
    raw_scores: Optional[Dict[str, float]] = None

@dataclass
class MarketImpact:
    """Market impact assessment."""
    price_impact: float  # Expected price movement (-1 to +1)
    volatility_impact: float  # Expected volatility change
    confidence: float  # Confidence in assessment
    reasoning: str

class SentimentAnalyzer:
    """Multi-model sentiment analysis for financial news."""

    def __init__(self):
        self.models = {}
        self.openai_client = None

        if TRANSFORMERS_AVAILABLE:
            self._load_models()
        else:
            logger.warning("Transformers not available, using fallback sentiment analysis")

        # Initialize OpenAI if API key is available
        if getattr(settings, 'OPENAI_API_KEY', None):
            try:
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info("OpenAI client initialized for sentiment analysis")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")

    def _load_models(self):
        """Load pre-trained sentiment analysis models."""
        try:
            # FinBERT - Finance-specific model
            logger.info("Loading FinBERT model...")
            self.models['finbert'] = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                return_all_scores=True
            )

            # Twitter RoBERTa - Social media optimized
            logger.info("Loading Twitter RoBERTa model...")
            self.models['twitter'] = pipeline(
                "sentiment-analysis",
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
                tokenizer="cardiffnlp/twitter-roberta-base-sentiment-latest",
                return_all_scores=True
            )

            # General purpose sentiment
            logger.info("Loading DistilBERT model...")
            self.models['distilbert'] = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                return_all_scores=True
            )

            logger.info(f"Loaded {len(self.models)} sentiment models")

        except Exception as e:
            logger.error(f"Failed to load sentiment models: {e}")

    async def analyze_sentiment(self, news_items: List[NewsItem]) -> Dict[str, SentimentResult]:
        """Analyze sentiment for multiple news items."""
        if not news_items:
            return {}

        # Choose analysis method based on configuration
        method = getattr(settings, 'SENTIMENT_MODEL', 'finbert')

        if method == 'openai' and self.openai_client:
            return await self._analyze_with_openai(news_items)
        elif method == 'hybrid' and self.openai_client:
            return await self._analyze_hybrid(news_items)
        else:
            return await self._analyze_with_transformers(news_items, method)

    async def _analyze_with_transformers(self, news_items: List[NewsItem], model_name: str) -> Dict[str, SentimentResult]:
        """Analyze sentiment using transformer models."""
        results = {}

        if model_name not in self.models:
            logger.warning(f"Model {model_name} not available, falling back to basic analysis")
            return await self._basic_sentiment_analysis(news_items)

        model = self.models[model_name]

        for item in news_items:
            try:
                # Combine title and content for analysis
                text = f"{item.title} {item.content}"[:512]  # Limit text length

                # Run inference in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                raw_result = await loop.run_in_executor(None, model, text)

                # Convert to our format
                sentiment_result = self._convert_transformer_result(raw_result, model_name)
                results[f"{item.symbol}_{item.published_at.isoformat()}"] = sentiment_result

                # Update the news item
                item.sentiment_score = sentiment_result.score
                item.confidence = sentiment_result.confidence

            except Exception as e:
                logger.warning(f"Failed to analyze sentiment for news item: {e}")
                # Fallback to neutral sentiment
                results[f"{item.symbol}_{item.published_at.isoformat()}"] = SentimentResult(
                    score=0.0, confidence=0.0, model=model_name
                )

        return results

    async def _analyze_with_openai(self, news_items: List[NewsItem]) -> Dict[str, SentimentResult]:
        """Analyze sentiment using OpenAI GPT models."""
        results = {}

        for item in news_items:
            try:
                prompt = f"""
                Analyze the sentiment of this financial news for trading purposes:

                Title: {item.title}
                Content: {item.content}

                Rate the overall sentiment from -1 (very bearish) to +1 (very bullish).
                Also provide a confidence score from 0 to 1.

                Respond with only: score,confidence
                Example: 0.3,0.8
                """

                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=20,
                        temperature=0.1
                    )
                )

                # Parse response
                content = response.choices[0].message.content.strip()
                score_str, confidence_str = content.split(',')

                score = float(score_str.strip())
                confidence = float(confidence_str.strip())

                sentiment_result = SentimentResult(
                    score=max(-1, min(1, score)),  # Clamp to [-1, 1]
                    confidence=max(0, min(1, confidence)),  # Clamp to [0, 1]
                    model="openai"
                )

                results[f"{item.symbol}_{item.published_at.isoformat()}"] = sentiment_result

                # Update the news item
                item.sentiment_score = sentiment_result.score
                item.confidence = sentiment_result.confidence

            except Exception as e:
                logger.warning(f"Failed to analyze sentiment with OpenAI: {e}")
                results[f"{item.symbol}_{item.published_at.isoformat()}"] = SentimentResult(
                    score=0.0, confidence=0.0, model="openai"
                )

        return results

    async def _analyze_hybrid(self, news_items: List[NewsItem]) -> Dict[str, SentimentResult]:
        """Use both transformer models and OpenAI for hybrid analysis."""
        # Get transformer results
        transformer_results = await self._analyze_with_transformers(news_items, 'finbert')

        # Get OpenAI results
        openai_results = await self._analyze_with_openai(news_items)

        # Combine results
        hybrid_results = {}

        for key in transformer_results.keys():
            transformer_result = transformer_results[key]
            openai_result = openai_results.get(key)

            if openai_result:
                # Weighted combination (70% OpenAI, 30% FinBERT for better accuracy)
                combined_score = 0.7 * openai_result.score + 0.3 * transformer_result.score
                combined_confidence = 0.7 * openai_result.confidence + 0.3 * transformer_result.confidence

                hybrid_results[key] = SentimentResult(
                    score=combined_score,
                    confidence=combined_confidence,
                    model="hybrid",
                    raw_scores={
                        "openai": openai_result.score,
                        "finbert": transformer_result.score
                    }
                )
            else:
                hybrid_results[key] = transformer_result

        return hybrid_results

    async def _basic_sentiment_analysis(self, news_items: List[NewsItem]) -> Dict[str, SentimentResult]:
        """Basic sentiment analysis using keyword matching."""
        positive_words = ['bullish', 'rally', 'surge', 'gain', 'profit', 'rise', 'up', 'growth', 'beat', 'exceed']
        negative_words = ['bearish', 'fall', 'drop', 'loss', 'decline', 'down', 'crash', 'plunge', 'miss', 'below']

        results = {}

        for item in news_items:
            text = f"{item.title} {item.content}".lower()

            positive_count = sum(1 for word in positive_words if word in text)
            negative_count = sum(1 for word in negative_words if word in text)

            if positive_count + negative_count == 0:
                score = 0.0
            else:
                score = (positive_count - negative_count) / (positive_count + negative_count)

            confidence = min(0.5, (positive_count + negative_count) / 10)  # Basic confidence

            results[f"{item.symbol}_{item.published_at.isoformat()}"] = SentimentResult(
                score=score,
                confidence=confidence,
                model="basic"
            )

        return results

    def _convert_transformer_result(self, raw_result: List[Dict], model_name: str) -> SentimentResult:
        """Convert transformer pipeline result to our format."""
        if not raw_result:
            return SentimentResult(score=0.0, confidence=0.0, model=model_name)

        # Handle different model output formats
        if model_name == 'finbert':
            # FinBERT: positive/negative labels
            scores = {item['label']: item['score'] for item in raw_result}
            positive_score = scores.get('positive', 0)
            negative_score = scores.get('negative', 0)

            # Convert to -1 to +1 scale
            score = positive_score - negative_score
            confidence = max(positive_score, negative_score)

        elif model_name == 'twitter':
            # Twitter RoBERTa: LABEL_0 (negative), LABEL_1 (neutral), LABEL_2 (positive)
            scores = {item['label']: item['score'] for item in raw_result}
            negative_score = scores.get('LABEL_0', 0)
            neutral_score = scores.get('LABEL_1', 0)
            positive_score = scores.get('LABEL_2', 0)

            score = (positive_score - negative_score) * (1 - neutral_score)  # Reduce impact of neutral
            confidence = max(positive_score, negative_score, neutral_score)

        elif model_name == 'distilbert':
            # DistilBERT: POSITIVE/NEGATIVE
            scores = {item['label']: item['score'] for item in raw_result}
            positive_score = scores.get('POSITIVE', 0)
            negative_score = scores.get('NEGATIVE', 0)

            score = positive_score - negative_score
            confidence = max(positive_score, negative_score)

        else:
            score = 0.0
            confidence = 0.0

        return SentimentResult(
            score=max(-1, min(1, score)),  # Clamp to [-1, 1]
            confidence=min(1, confidence),  # Clamp to [0, 1]
            model=model_name,
            raw_scores={item['label']: item['score'] for item in raw_result}
        )

    async def get_symbol_sentiment(self, symbol: str, hours_back: int = 24) -> Optional[float]:
        """Get current sentiment score for a symbol."""
        try:
            # This would integrate with the news collector
            # For now, return a placeholder
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get sentiment for {symbol}: {e}")
            return None

    async def get_market_sentiment(self) -> float:
        """Get overall market sentiment."""
        try:
            # This would aggregate sentiment across major indices
            # For now, return neutral
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get market sentiment: {e}")
            return 0.0
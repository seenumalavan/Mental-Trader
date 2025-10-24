"""
Market impact analysis using AI to assess how news affects trading decisions.
"""

import asyncio
import logging
from typing import Dict, Optional
from dataclasses import dataclass

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from src.config import settings
from src.news.news_collector import NewsItem

logger = logging.getLogger("impact_analyzer")

@dataclass
class ImpactAssessment:
    """Assessment of news impact on market/trading."""
    price_direction: float  # -1 (strong sell) to +1 (strong buy)
    volatility_change: float  # Expected volatility change (-1 to +1)
    time_horizon: str  # "short" (minutes), "medium" (hours), "long" (days)
    confidence: float  # 0 to 1
    reasoning: str
    key_factors: list[str]

class MarketImpactAnalyzer:
    """Analyzes market impact of news using AI."""

    def __init__(self):
        self.openai_client = None

        if OPENAI_AVAILABLE and getattr(settings, 'OPENAI_API_KEY', None):
            try:
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info("OpenAI client initialized for impact analysis")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI for impact analysis: {e}")
        else:
            logger.warning("OpenAI not available for impact analysis")

    async def assess_impact(self, news_item: NewsItem, current_price: Optional[float] = None) -> ImpactAssessment:
        """Assess the market impact of a news item."""

        if not self.openai_client:
            # Fallback assessment
            return self._fallback_impact_assessment(news_item)

        try:
            prompt = self._build_impact_prompt(news_item, current_price)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.2
                )
            )

            return self._parse_impact_response(response.choices[0].message.content)

        except Exception as e:
            logger.warning(f"Failed to assess impact with AI: {e}")
            return self._fallback_impact_assessment(news_item)

    def _build_impact_prompt(self, news_item: NewsItem, current_price: Optional[float]) -> str:
        """Build the prompt for impact analysis."""

        price_context = ""
        if current_price:
            price_context = f"Current market price: ₹{current_price:.2f}"

        return f"""
        Analyze the market impact of this financial news for algorithmic trading:

        SYMBOL: {news_item.symbol}
        TITLE: {news_item.title}
        CONTENT: {news_item.content}
        SOURCE: {news_item.source}
        {price_context}

        Assess the impact on:
        1. Price direction (-1 to +1 scale, where -1 is strong downward pressure, +1 is strong upward pressure)
        2. Expected volatility change (-1 to +1, where -1 means much lower volatility, +1 means much higher volatility)
        3. Time horizon (short/medium/long term impact)
        4. Confidence in assessment (0-1)
        5. Key factors driving the impact

        Consider:
        - Is this earnings news, regulatory news, or market-moving event?
        - How significant is the information?
        - What's the typical market reaction to similar news?
        - Are there any caveats or uncertainties?

        Respond in this exact format:
        PRICE_DIRECTION: [number]
        VOLATILITY_CHANGE: [number]
        TIME_HORIZON: [short/medium/long]
        CONFIDENCE: [number]
        KEY_FACTORS: [comma-separated list]
        REASONING: [brief explanation]
        """

    def _parse_impact_response(self, response: str) -> ImpactAssessment:
        """Parse the AI response into an ImpactAssessment object."""

        try:
            lines = response.strip().split('\n')
            data = {}

            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().upper()
                    value = value.strip()

                    if key == 'PRICE_DIRECTION':
                        data['price_direction'] = float(value)
                    elif key == 'VOLATILITY_CHANGE':
                        data['volatility_change'] = float(value)
                    elif key == 'TIME_HORIZON':
                        data['time_horizon'] = value.lower()
                    elif key == 'CONFIDENCE':
                        data['confidence'] = float(value)
                    elif key == 'KEY_FACTORS':
                        data['key_factors'] = [f.strip() for f in value.split(',')]
                    elif key == 'REASONING':
                        data['reasoning'] = value

            # Validate and set defaults
            price_direction = max(-1, min(1, data.get('price_direction', 0)))
            volatility_change = max(-1, min(1, data.get('volatility_change', 0)))
            time_horizon = data.get('time_horizon', 'medium')
            confidence = max(0, min(1, data.get('confidence', 0.5)))
            key_factors = data.get('key_factors', [])
            reasoning = data.get('reasoning', 'AI assessment completed')

            return ImpactAssessment(
                price_direction=price_direction,
                volatility_change=volatility_change,
                time_horizon=time_horizon,
                confidence=confidence,
                reasoning=reasoning,
                key_factors=key_factors
            )

        except Exception as e:
            logger.warning(f"Failed to parse impact response: {e}")
            return self._fallback_impact_assessment(None)

    def _fallback_impact_assessment(self, news_item: Optional[NewsItem]) -> ImpactAssessment:
        """Fallback impact assessment when AI is not available."""

        # Basic keyword-based assessment
        if news_item:
            text = f"{news_item.title} {news_item.content}".lower()

            # Check for high-impact keywords
            high_impact_positive = ['earnings beat', 'profit surge', 'revenue growth', 'upgrade', 'buy rating']
            high_impact_negative = ['earnings miss', 'loss', 'revenue decline', 'downgrade', 'sell rating']

            positive_score = sum(1 for word in high_impact_positive if word in text)
            negative_score = sum(1 for word in high_impact_negative if word in text)

            if positive_score > negative_score:
                price_direction = 0.3
                confidence = 0.6
            elif negative_score > positive_score:
                price_direction = -0.3
                confidence = 0.6
            else:
                price_direction = 0.0
                confidence = 0.3
        else:
            price_direction = 0.0
            confidence = 0.1

        return ImpactAssessment(
            price_direction=price_direction,
            volatility_change=0.1,  # Slight volatility increase
            time_horizon="medium",
            confidence=confidence,
            reasoning="Fallback keyword-based assessment",
            key_factors=["Basic keyword analysis"]
        )

    async def should_trigger_circuit_breaker(self, news_item: NewsItem) -> bool:
        """Determine if news should trigger a trading circuit breaker."""

        if not news_item:
            return False

        # Check for extreme keywords that might indicate market-moving news
        extreme_keywords = [
            'bankruptcy', 'delisting', 'merger', 'acquisition',
            'scandal', 'fraud', 'lawsuit', 'criminal', 'investigation'
        ]

        text = f"{news_item.title} {news_item.content}".lower()

        for keyword in extreme_keywords:
            if keyword in text:
                logger.warning(f"Circuit breaker triggered for {news_item.symbol}: {keyword} detected")
                return True

        return False

    async def get_trading_recommendation(self, news_item: NewsItem, current_sentiment: float) -> Dict:
        """Get AI-powered trading recommendation based on news and sentiment."""

        if not self.openai_client:
            return {"action": "hold", "reason": "AI analysis not available"}

        try:
            prompt = f"""
            Based on this news and current market sentiment ({current_sentiment:.2f}),
            provide a trading recommendation:

            NEWS: {news_item.title} - {news_item.content}

            Consider:
            - News significance and market impact
            - Current sentiment context
            - Risk management principles
            - Typical algorithmic trading responses

            Respond with: ACTION,REASON
            Actions: buy, sell, hold, reduce_position, increase_position
            """

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                    temperature=0.1
                )
            )

            content = response.choices[0].message.content.strip()
            action, reason = content.split(',', 1)

            return {
                "action": action.strip().lower(),
                "reason": reason.strip()
            }

        except Exception as e:
            logger.warning(f"Failed to get trading recommendation: {e}")
            return {"action": "hold", "reason": "Analysis failed"}
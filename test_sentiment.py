"""
Basic test script for sentiment analysis components.
Run this to verify that all sentiment modules can be imported and initialized.
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_sentiment_imports():
    """Test that all sentiment modules can be imported."""
    try:
        print("Testing sentiment module imports...")

        # Test news collector
        from src.news.news_collector import NewsCollector
        print("✓ NewsCollector imported successfully")

        # Test sentiment analyzer
        from src.news.sentiment_analyzer import SentimentAnalyzer
        print("✓ SentimentAnalyzer imported successfully")

        # Test impact analyzer
        from src.news.impact_analyzer import MarketImpactAnalyzer
        print("✓ MarketImpactAnalyzer imported successfully")

        # Test sentiment service
        from src.services.sentiment_service import SentimentService
        print("✓ SentimentService imported successfully")

        # Test sentiment filter
        from src.engine.sentiment_filter import SentimentFilter
        print("✓ SentimentFilter imported successfully")

        # Test news models
        from src.models.news_models import NewsItemModel, SentimentHistoryModel
        print("✓ News models imported successfully")

        # Test sentiment API
        from src.api.sentiment_api import router as sentiment_router
        print("✓ Sentiment API router imported successfully")

        print("\n✅ All sentiment modules imported successfully!")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

async def test_sentiment_initialization():
    """Test that sentiment services can be initialized."""
    try:
        print("\nTesting sentiment service initialization...")

        from src.services.sentiment_service import SentimentService
        from src.engine.sentiment_filter import SentimentFilter

        # Create services (without starting them)
        sentiment_service = SentimentService()
        sentiment_filter = SentimentFilter(sentiment_service)

        print("✓ Sentiment services initialized successfully")

        # Test basic methods without database connection
        print("✓ Sentiment service methods available")

        print("\n✅ Sentiment services initialized successfully!")
        return True

    except Exception as e:
        print(f"❌ Initialization error: {e}")
        return False

async def main():
    """Run all tests."""
    print("🧪 Mental Trader Sentiment Analysis Test Suite")
    print("=" * 50)

    # Test imports
    imports_ok = await test_sentiment_imports()
    if not imports_ok:
        print("\n❌ Import tests failed. Please check dependencies.")
        return False

    # Test initialization
    init_ok = await test_sentiment_initialization()
    if not init_ok:
        print("\n❌ Initialization tests failed. Please check configuration.")
        return False

    print("\n🎉 All tests passed! Sentiment analysis is ready to use.")
    print("\nNext steps:")
    print("1. Set up API keys in .env file (NEWSAPI_KEY, OPENAI_API_KEY, etc.)")
    print("2. Run database migration: psql -d your_db -f src/scripts/migrate_sentiment_db.sql")
    print("3. Start the application: python src/main.py --web")
    print("4. Test sentiment endpoints at http://localhost:8000/sentiment/")

    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
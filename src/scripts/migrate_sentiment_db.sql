-- Migration script for sentiment analysis and news features
-- Run this after the main database setup

-- News items table for storing collected news
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
);

-- Sentiment history table for tracking sentiment over time
CREATE TABLE IF NOT EXISTS sentiment_history (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL, -- 1h, 4h, 1d, etc.
    sentiment_score FLOAT NOT NULL,
    news_count INTEGER NOT NULL,
    confidence FLOAT NOT NULL,
    timestamp TIMESTAMP NOT NULL
);

-- Market sentiment table for overall market sentiment
CREATE TABLE IF NOT EXISTS market_sentiment (
    id SERIAL PRIMARY KEY,
    index_name VARCHAR(50) NOT NULL, -- NIFTY, SENSEX, etc.
    sentiment_score FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    news_count INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL
);

-- Sentiment alerts table for tracking important sentiment events
CREATE TABLE IF NOT EXISTS sentiment_alerts (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50),
    alert_type VARCHAR(50) NOT NULL, -- extreme_sentiment, trend_change, etc.
    severity VARCHAR(20) NOT NULL, -- low, medium, high, critical
    message TEXT NOT NULL,
    sentiment_score FLOAT,
    confidence FLOAT,
    news_count INTEGER,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_items(symbol);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source);
CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news_items(sentiment_score);

CREATE INDEX IF NOT EXISTS idx_sentiment_symbol ON sentiment_history(symbol);
CREATE INDEX IF NOT EXISTS idx_sentiment_timeframe ON sentiment_history(timeframe);
CREATE INDEX IF NOT EXISTS idx_sentiment_timestamp ON sentiment_history(timestamp);

CREATE INDEX IF NOT EXISTS idx_market_sentiment_index ON market_sentiment(index_name);
CREATE INDEX IF NOT EXISTS idx_market_sentiment_timestamp ON market_sentiment(timestamp);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON sentiment_alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON sentiment_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON sentiment_alerts(timestamp);

-- Add sentiment columns to existing signals table if it exists
-- (This would be for storing sentiment context with each signal)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'signals') THEN
        ALTER TABLE signals
        ADD COLUMN IF NOT EXISTS sentiment_score FLOAT,
        ADD COLUMN IF NOT EXISTS sentiment_confidence FLOAT,
        ADD COLUMN IF NOT EXISTS sentiment_filtered BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS sentiment_reasons TEXT[];
    END IF;
END $$;

-- Create a view for recent sentiment summary
CREATE OR REPLACE VIEW sentiment_summary AS
SELECT
    sh.symbol,
    sh.sentiment_score,
    sh.confidence,
    sh.news_count,
    sh.timestamp,
    COUNT(CASE WHEN ni.sentiment_score > 0.1 THEN 1 END) as positive_news,
    COUNT(CASE WHEN ni.sentiment_score < -0.1 THEN 1 END) as negative_news,
    COUNT(CASE WHEN ni.sentiment_score BETWEEN -0.1 AND 0.1 THEN 1 END) as neutral_news
FROM sentiment_history sh
LEFT JOIN news_items ni ON sh.symbol = ni.symbol
    AND ni.published_at >= sh.timestamp - INTERVAL '1 hour'
    AND ni.published_at <= sh.timestamp
WHERE sh.timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY sh.symbol, sh.sentiment_score, sh.confidence, sh.news_count, sh.timestamp
ORDER BY sh.timestamp DESC;

-- Insert sample data for testing (optional)
-- This can be removed in production
INSERT INTO sentiment_history (symbol, timeframe, sentiment_score, news_count, confidence, timestamp)
SELECT
    symbol,
    '1h',
    0.0,
    0,
    0.0,
    NOW()
FROM (VALUES ('RELIANCE'), ('TCS'), ('INFY'), ('HDFCBANK'), ('ICICIBANK')) AS t(symbol)
ON CONFLICT DO NOTHING;</content>
<parameter name="filePath">d:\Trading\Mental-Trader\src\scripts\migrate_sentiment_db.sql
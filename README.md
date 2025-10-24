# Mental Trader - Scalping Service

A production-ready algorithmic trading system built with Python and FastAPI. Features real-time market data processing, EMA-based trading strategies, and comprehensive risk management.

## Features

- **Real-time Market Data**: WebSocket connections for live price feeds
- **Advanced Analytics**: In-memory bar building with incremental EMA calculations
- **Trading Strategies**: EMA crossover scalping strategy with customizable parameters
- **Execution Engine**: Paper trading simulator and live order execution
- **Data Persistence**: PostgreSQL database for candles, trades, and EMA states
- **Risk Management**: Position sizing and daily loss limits
- **Monitoring**: Health endpoints and notification webhooks
- **Web Interface**: FastAPI-based REST API for control and monitoring
- **Sentiment Analysis**: AI-powered news sentiment analysis and market impact assessment
- **News Integration**: Multi-source news collection from financial APIs and social media

## Quick Start

### 1. Environment Setup

1. Copy the environment template:
   ```cmd
   copy .env.example .env
   ```

2. Edit `.env` and configure your settings:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/trading_db
   BROKER_WS_URL=wss://api.broker.com/ws
   BROKER_REST_URL=https://api.broker.com/api/v1
   BROKER_API_KEY=your_api_key_here
   BROKER_API_SECRET=your_api_secret_here
   WATCHLIST=RELIANCE,INFY,ICICIBANK,TCS,HDFC
   ```

### 2. Install Dependencies

```cmd
cd d:\Trading\Mental-Trader
pip install -r requirements.txt
```

### 3. Run the Trading System

**Option A: Command Line Mode (Direct Trading)**
```cmd
python main.py
```

**Option B: Web Interface Mode (API + Monitoring)**
```cmd
python main.py --web
```

Then access the API at: http://localhost:8000

**Option C: Custom Port**
```cmd
python main.py --web --port 9000
```

## Project Structure

```
src/
├── engine/           # Core trading engine components
│   ├── bar_builder.py    # Real-time bar/candle construction
│   ├── ema.py           # Exponential Moving Average calculations
│   └── strategy.py      # Trading strategy implementations
├── execution/        # Order execution and simulation
│   ├── execution.py     # Order execution engine
│   └── simulator.py     # Paper trading simulator
├── persistence/      # Data storage layer
│   ├── db.py           # Database connection and queries
│   ├── models.py       # Data models
│   └── ema_state.py    # EMA state persistence
├── providers/        # External data/broker connections
│   ├── broker_rest.py  # REST API broker interface
│   └── broker_ws.py    # WebSocket broker interface
├── services/         # Application services
│   ├── scalping_service.py  # Main trading service
│   ├── notifier.py          # Notification system
│   ├── risk_manager.py      # Risk management
│   └── metrics.py           # Performance metrics
├── utils/           # Utility functions
│   ├── logging_config.py   # Logging configuration
│   └── time_utils.py       # Time zone utilities
├── scripts/         # Utility scripts
│   └── backfill_historical.py  # Historical data backfill
└── tests/           # Unit tests
    ├── test_bar_builder.py
    └── test_strategy.py
```

## API Endpoints

- `GET /` - System information and available endpoints  
- `GET /health` - System health check
- `GET /status` - Trading system status
- `GET /config` - Current configuration (safe values)
- `POST /control/start` - Start the trading system
- `POST /control/stop` - Stop the trading system
- `GET /docs` - Interactive API documentation

### Sentiment Analysis Endpoints

- `GET /sentiment/health` - Sentiment service health check
- `GET /sentiment/symbol/{symbol}` - Get sentiment context for a symbol
- `POST /sentiment/filter` - Filter trading signals based on sentiment
- `GET /sentiment/news/{symbol}` - Get recent news for a symbol
- `POST /sentiment/impact` - Analyze market impact of specific news
- `GET /sentiment/market` - Get overall market sentiment
- `GET /sentiment/alerts` - Get sentiment-based alerts
- `GET /sentiment/wait-check/{symbol}` - Check if should wait for better sentiment
- `GET /sentiment/stats` - Get sentiment analysis statistics

## Configuration

Key configuration parameters in `.env`:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `WATCHLIST` | Comma-separated list of symbols to trade | `RELIANCE,INFY,ICICIBANK` |
| `WARMUP_BARS` | Number of historical bars for EMA initialization | `300` |
| `EMA_SHORT` | Short EMA period | `8` |
| `EMA_LONG` | Long EMA period | `21` |
| `NOTIFIER_WEBHOOK` | Webhook URL for trade notifications | - |

### Sentiment Analysis Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `SENTIMENT_ENABLE` | Enable sentiment analysis features | `true` |
| `SENTIMENT_UPDATE_INTERVAL_MINUTES` | How often to update sentiment data | `5` |
| `SENTIMENT_NEWS_HOURS_BACK` | Hours of news history to collect | `6` |
| `NEWSAPI_KEY` | NewsAPI key for news collection | - |
| `ALPHA_VANTAGE_KEY` | Alpha Vantage API key | - |
| `REDDIT_CLIENT_ID` | Reddit API client ID | - |
| `REDDIT_CLIENT_SECRET` | Reddit API client secret | - |
| `SENTIMENT_MODEL` | Sentiment analysis model (finbert, openai, hybrid) | `hybrid` |
| `OPENAI_API_KEY` | OpenAI API key for impact analysis | - |
| `SENTIMENT_MIN_CONFIDENCE` | Minimum confidence for sentiment filtering | `0.6` |
| `SENTIMENT_FILTER_ENABLE_EXTREME_BLOCK` | Block signals on extreme sentiment | `true` |
| `SENTIMENT_FILTER_ENABLE_ALIGNMENT` | Require sentiment-signal alignment | `true` |

## Development

### Running Tests

```cmd
cd src
python -m pytest tests/
```

### Adding New Strategies

1. Create a new strategy class in `src/engine/strategy.py`
2. Implement the `on_bar_close` method
3. Register the strategy in the `ScalperService`

### Database Migrations

SQL migrations are located in `src/scripts/migrate_db.sql` and `src/scripts/migrate_sentiment_db.sql`.

## Sentiment Analysis

Mental Trader includes comprehensive sentiment analysis capabilities that enhance trading decisions with market news and social sentiment data.

### Features

- **Multi-Source News Collection**: Aggregates news from financial APIs (Alpha Vantage, NewsAPI), RSS feeds (Yahoo Finance), and social media (Reddit)
- **AI-Powered Sentiment Analysis**: Uses transformer models (FinBERT, Twitter RoBERTa) and OpenAI GPT for accurate sentiment scoring
- **Market Impact Assessment**: Analyzes how news affects price direction, volatility, and trading recommendations
- **Signal Filtering**: Filters trading signals based on sentiment alignment and extreme sentiment conditions
- **Real-time Alerts**: Generates alerts for significant sentiment changes and market events

### Usage Examples

**Check Symbol Sentiment:**
```bash
curl http://localhost:8000/sentiment/symbol/RELIANCE
```

**Filter a Trading Signal:**
```bash
curl -X POST http://localhost:8000/sentiment/filter \
  -H "Content-Type: application/json" \
  -d '{"symbol": "RELIANCE", "side": "BUY", "price": 2500.0}'
```

**Analyze News Impact:**
```bash
curl -X POST http://localhost:8000/sentiment/impact \
  -H "Content-Type: application/json" \
  -d '{"symbol": "RELIANCE", "title": "Reliance Q3 Results Beat Estimates", "content": "Reliance Industries reported better than expected quarterly results..."}'
```

### Integration with Trading Strategies

Sentiment analysis integrates with existing trading strategies through:

1. **Signal Confirmation**: Sentiment filters can veto signals that oppose market sentiment
2. **Position Sizing**: Reduce position sizes when sentiment is uncertain or opposing
3. **Entry Timing**: Wait for sentiment alignment before entering positions
4. **Risk Management**: Increase stops when sentiment indicates potential reversals

### Model Selection

Choose the appropriate sentiment model based on your needs:

- **finbert**: Fast, local transformer model optimized for financial text
- **openai**: Slower but more accurate using GPT models (requires API key)
- **hybrid**: Combines both models for best accuracy with fallback
````
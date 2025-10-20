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

## Configuration

Key configuration parameters in `.env`:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `WATCHLIST` | Comma-separated list of symbols to trade | `RELIANCE,INFY,ICICIBANK` |
| `WARMUP_BARS` | Number of historical bars for EMA initialization | `300` |
| `EMA_SHORT` | Short EMA period | `8` |
| `EMA_LONG` | Long EMA period | `21` |
| `NOTIFIER_WEBHOOK` | Webhook URL for trade notifications | - |

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

SQL migrations are located in `src/scripts/migrate_db.sql`.

## Production Deployment

1. Set up a PostgreSQL database
2. Configure environment variables for production
3. Set up monitoring and alerting
4. Configure webhook notifications
5. Implement proper error handling and logging

## License

This project is for educational and development purposes. Please ensure compliance with all applicable trading regulations and broker terms of service.

## Support

For issues and questions, please check the logs and ensure all environment variables are properly configured.

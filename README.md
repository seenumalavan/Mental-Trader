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



### Execution Flow (Updated)

Below is an updated high-level flow covering the dual-timeframe design and integrated Options Manager.

```
         +----------------+
         |   config.py    |  <-- Settings (EMA, risk, option flags)
         +--------+-------+
          |
         start()  v
 +----------------------------------+    historical + intraday      +--------------------+
 | DualTimeframeService (Scalp/Intraday) +--------------------------->+    BrokerRest      |
 |  - resolve_instruments           |                               +--------------------+
 |  - load/persist warmup candles   |    subscribe ticks             +--------------------+
 |  - build strategy                +------------------------------->+    BrokerWS        |
 |  - init OptionsManager (if enabled)                              +--------------------+
 +---------------+------------------+
         |
         | on_tick(tick)
         v
      +--------------+     closed bars      +------------------+
      |  BarBuilder  +--------------------->+ EMAState primary  |
      +------+-------+                      +------------------+
         |                                  |
         | candle aggregation (pandas)       v
         |                             EMAState confirm
         |                                  |
         |                                  v
         |                           Strategy.on_bar_close()
         |                                  |
         |                          Underlying Signal (BUY/SELL)
         |                                  |
         |                            +-----+------+---------------------------+
         |                            | publish to OptionsManager (if enabled) |
         |                            +-------------+--------------------------+
         |                                          |
         |                                    OptionSignal (ranked strike)
         |                                          |
         |                                          v
         v                                  +------------------+
    Database.persist_candle()                   |    Executor*     |  (*option path TBD)
         |                                  +------------------+
         v                                          |
   Database.upsert_ema_state()                           v
         |                                    BrokerRest.place_order()
         v                                          |
      +------------------+                             v
      |    Notifier      | <---- underlying and option signals (webhook/email)
      +------------------+

OptionSignal selection pipeline:
  Underlying Signal -> OptionsManager -> OptionsChainProvider -> Analyzer.rank_strikes()
  -> PositionSizing.compute_option_position() -> emit OptionSignal

Persistence additions:
  - Trades table (underlying)
  - option_trades table (options) via Database.insert_option_trade()

Time handling: naive local timestamps (IST) stored & compared uniformly.
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `DualTimeframeServiceBase` | Orchestrates data loading, WebSocket ticks, bar construction, EMA updates, and strategy invocation for both timeframes. |
| `BarBuilder` | Accumulates ticks into time-bucketed bars for the primary timeframe. |
| Confirm Aggregation | Resamples primary bars into confirm timeframe using pandas (in-memory). |
| `EMAState` | Maintains rolling EMA calculations for short and long periods. |
| Strategy (`ScalpStrategy` / `IntradayStrategy`) | Applies crossover logic and trend filter; emits underlying signals. |
| `OptionsManager` | Debounce + cooldown; gathers chain, ranks strikes, sizes position, emits OptionSignal. |
| `OptionsChainProvider` | Retrieves (placeholder) option chain & futures quote via `BrokerRest`. |
| Analyzer (`options_chain_analyzer.py`) | Computes OI percentiles, IV qualities, spreads; ranks candidate strikes. |
| Position Sizing (`option_position_sizing.py`) | Determines lot size, premium stop/target per strategy mode. |
| `Executor` | Places underlying orders (option path pending). |
| `Notifier` | Sends webhook/email notifications for underlying and option signals. |
| `Database` | Persists candles, EMA states, trades, and option trades. |

### Future Extensions
1. Implement real broker option chain & futures quote endpoints.
2. Add option order placement & life-cycle management in `Executor`.
3. Enhance risk checks (per-strike OI saturation, max open option positions).
4. Expand test coverage: SELL signals, cooldown, debounce, persistence, IST timestamp assertions.
5. Add PnL attribution per leg (underlying vs derivative). 


Old application flow:


            +----------------+
            |  config.py     |
            +--------+-------+
                     |
        start()      v
+--------------------------+     historical/intraday       +--------------------+
|    ScalperService        +------------------------------->+   BrokerRest       |
|                          |                                +--------------------+
|  resolve_instruments     |     ticks subscribe            +--------------------+
|  seed EMA states         +------------------------------->+    BrokerWS        |
|  set ws.on_tick          |                                +--------------------+
+-------------+------------+
              |
              | on_tick(tick)
              v
       +--------------+     closed bars      +-----------------+
       |  BarBuilder  +--------------------->+  EMAState(1m)   |
       +------+-------+                      +-----------------+
              |                                  |
              |                                  v
              |                             ScalpStrategy
              |                                  |
              |                             Signal (BUY/SELL)
              |                                  v
              |                             Executor -> BrokerRest.place_order()
              |                                  |
              v                                  v
        Database.persist_candle()         Notifier.notify_signal()

## Key Actors & Roles (Summary)

This section reiterates the core moving parts for quick orientation (added without altering previous sections).

| Actor | Layer | Role | Notes |
|-------|-------|------|-------|
| `config.py` | Config | Centralizes runtime settings (EMA periods, feature flags, option params) | Loaded once on startup via Pydantic settings. |
| `DualTimeframeServiceBase` | Service Orchestration | Boots data, subscribes ticks, aggregates bars, manages EMA states, invokes strategies | Parent for scalping/intraday services; houses shared `OptionsManager`. |
| `BarBuilder` | Engine | Converts streaming ticks -> completed bars for primary timeframe | Emits closed bars consumed by service/strategy. |
| Confirm Aggregation (pandas) | Engine | Resamples primary bars to confirm timeframe in-memory | Not persisted unless configured; provides higher-timeframe trend context. |
| `EMAState` | Engine | Maintains rolling short & long EMA values + previous values for crossover detection | Updated on each closed bar. |
| `ScalpStrategy` / `IntradayStrategy` | Strategy | Detect EMA crossovers, apply optional trend filter, generate underlying signals | Publishes to executor + notifier + options layer if enabled. |
| `OptionsManager` | Options Orchestration | Debounce chain fetch, rank strikes, size position, emit `OptionSignal` | Enforces cooldown per side to avoid duplicate rapid trades. |
| `OptionsChainProvider` | Data Provider | Fetch option chain & futures quote; retain last snapshot for OI deltas | Currently uses placeholder REST methods. |
| Analyzer (`options_chain_analyzer.py`) | Analytics | Compute PCR, IV stats, rank candidate strikes with weighted score | Filters by OI percentile, spread, distance, IV quality. |
| Position Sizing (`option_position_sizing.py`) | Risk | Translate premium & risk cap -> lots + stop/target premiums | Different stop/target % for scalper vs intraday mode. |
| `Executor` | Execution | Places underlying (and future option) orders through `BrokerRest` | Option order path still to be implemented. |
| `BrokerWS` | IO | Provides real-time ticks for instruments | Feeds `BarBuilder`. |
| `BrokerRest` | IO | Historical/intraday candles, (future) order placement, option chain, futures quote | Option endpoints currently stubbed. |
| `Database` | Persistence | Stores candles, EMA state, trades, option trades | Ensures warm restart capability & audit trail. |
| `Notifier` | Integration | Sends trade & option signals via webhook/email | Formats both underlying and option signal payloads. |
| `risk_manager.py` | Risk | (If used) Adjusts position sizing for underlying trades | Called inside strategies before creating Signals. |
| `metrics.py` | Monitoring | Collects performance/health metrics (if implemented) | Extensible for dashboards. |
| `time_utils.now_ist` | Utility | Supplies naive IST timestamps | Keeps consistency across persistence and signals. |
| Tests (`tests/`) | QA | Validate bar building, strategy logic, (future) options path | Need expansion for options cooldown/debounce behaviors. |

Use this table as a fast map when navigating or onboarding others.
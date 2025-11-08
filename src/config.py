from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = Field("sqlite:///mental_trader.db", env="DATABASE_URL")
    
    # Upstox API Configuration
    UPSTOX_API_KEY: str = Field("", env="UPSTOX_API_KEY") 
    UPSTOX_API_SECRET: str = Field("", env="UPSTOX_API_SECRET")
    UPSTOX_REDIRECT_URI: str = Field("", env="UPSTOX_REDIRECT_URI")
    UPSTOX_AUTH_URL: str = Field("https://api.upstox.com/index/dialog/authorize", env="UPSTOX_AUTH_URL")

    # Trading Configuration
    WARMUP_BARS: int = Field(2400, env="WARMUP_BARS")
    # Deprecated: Use SCALPER_EMA_SHORT/LONG and INTRADAY_EMA_SHORT/LONG instead
    EMA_SHORT: int = Field(8, env="EMA_SHORT")  # Deprecated
    EMA_LONG: int = Field(21, env="EMA_LONG")   # Deprecated

    # Scalper EMA configuration
    SCALPER_EMA_SHORT: int = Field(8, env="SCALPER_EMA_SHORT")
    SCALPER_EMA_LONG: int = Field(21, env="SCALPER_EMA_LONG")

    # Intraday EMA configuration
    INTRADAY_EMA_SHORT: int = Field(8, env="INTRADAY_EMA_SHORT")
    INTRADAY_EMA_LONG: int = Field(21, env="INTRADAY_EMA_LONG")
    
    # Notifications
    NOTIFIER_WEBHOOK: str = Field("", env="NOTIFIER_WEBHOOK")
    
    # Email / SMTP (Gmail)
    SMTP_ENABLE: bool = Field(False, env="SMTP_ENABLE")
    SMTP_USERNAME: str = Field("", env="SMTP_USERNAME")
    SMTP_PASSWORD: str = Field("", env="SMTP_PASSWORD")
    SMTP_FROM: str = Field("", env="SMTP_FROM")
    SMTP_TO: str = Field("", env="SMTP_TO")

    # Scalper configuration
    SCALP_PRIMARY_TIMEFRAME: str = Field("1m", env="SCALP_PRIMARY_TIMEFRAME")
    SCALP_CONFIRM_TIMEFRAME: str = Field("5m", env="SCALP_CONFIRM_TIMEFRAME")
    SCALP_ENABLE_TREND_CONFIRMATION: bool = Field(True, env="SCALP_ENABLE_TREND_CONFIRMATION")
    SCALP_ENABLE_SIGNAL_CONFIRMATION: bool = Field(True, env="SCALP_ENABLE_SIGNAL_CONFIRMATION")
    
    # Intraday configuration (configurable primary and confirmation timeframes)
    INTRADAY_PRIMARY_TIMEFRAME: str = Field("5m", env="INTRADAY_PRIMARY_TIMEFRAME")
    INTRADAY_CONFIRM_TIMEFRAME: str = Field("15m", env="INTRADAY_CONFIRM_TIMEFRAME")
    INTRADAY_ENABLE_TREND_CONFIRMATION: bool = Field(True, env="INTRADAY_ENABLE_TREND_CONFIRMATION")
    INTRADAY_ENABLE_SIGNAL_CONFIRMATION: bool = Field(True, env="INTRADAY_ENABLE_SIGNAL_CONFIRMATION")
    
    # Intraday trade limits
    INTRADAY_MAX_TRADES_MORNING_MONTHLY: int = Field(40, env="INTRADAY_MAX_TRADES_MORNING_MONTHLY")
    INTRADAY_MAX_TRADES_AFTERNOON_MONTHLY: int = Field(25, env="INTRADAY_MAX_TRADES_AFTERNOON_MONTHLY")
    INTRADAY_RR_RATIO: float = Field(2.5, env="INTRADAY_RR_RATIO")

    # Confirmation pipeline configuration
    CONFIRMATION_RECENT_BARS: int = Field(750, env="CONFIRMATION_RECENT_BARS")

    # Option Trading (Shared Options Manager)
    OPTION_ENABLE: bool = Field(True, env="OPTION_ENABLE")
    OPTION_LOT_SIZE: int = Field(50, env="OPTION_LOT_SIZE")
    OPTION_RISK_CAP_PER_TRADE: float = Field(7500.0, env="OPTION_RISK_CAP_PER_TRADE")
    OPTION_OI_MIN_PERCENTILE: int = Field(60, env="OPTION_OI_MIN_PERCENTILE")
    OPTION_SPREAD_MAX_PCT_SCALPER: float = Field(0.015, env="OPTION_SPREAD_MAX_PCT_SCALPER")
    OPTION_SPREAD_MAX_PCT_INTRADAY: float = Field(0.025, env="OPTION_SPREAD_MAX_PCT_INTRADAY")
    OPTION_DEBOUNCE_SEC: int = Field(30, env="OPTION_DEBOUNCE_SEC")
    OPTION_DEBOUNCE_INTRADAY_SEC: int = Field(60, env="OPTION_DEBOUNCE_INTRADAY_SEC")
    OPTION_COOLDOWN_SEC: int = Field(300, env="OPTION_COOLDOWN_SEC")

    # Opening Range Options Breakout Configuration
    OPENING_RANGE_ENABLED: bool = Field(True, env="OPENING_RANGE_ENABLED")
    OPENING_RANGE_TIMEFRAME: str = Field("5m", env="OPENING_RANGE_TIMEFRAME")
    OPENING_RANGE_RANGE_MINUTES: int = Field(15, env="OPENING_RANGE_RANGE_MINUTES")  # length of opening range collection window
    OPENING_RANGE_LAST_TRADE_TIME: str = Field("09:45", env="OPENING_RANGE_LAST_TRADE_TIME")  # HH:MM local (IST) cutoff for breakout trades
    OPENING_RANGE_REQUIRE_CPR: bool = Field(True, env="OPENING_RANGE_REQUIRE_CPR")
    OPENING_RANGE_REQUIRE_PRICE_ACTION: bool = Field(True, env="OPENING_RANGE_REQUIRE_PRICE_ACTION")
    OPENING_RANGE_REQUIRE_RSI_SLOPE: bool = Field(False, env="OPENING_RANGE_REQUIRE_RSI_SLOPE")
    OPENING_RANGE_MIN_OI_CHANGE_PCT: float = Field(8.0, env="OPENING_RANGE_MIN_OI_CHANGE_PCT")  # % increase in relevant side OI (calls for upside, puts for downside)
    OPENING_RANGE_DEBOUNCE_SEC: int = Field(5, env="OPENING_RANGE_DEBOUNCE_SEC")  # small debounce to avoid duplicate detection same bar
    OPENING_RANGE_MAX_SIGNALS_PER_DAY: int = Field(1, env="OPENING_RANGE_MAX_SIGNALS_PER_DAY")
    
    # Sentiment Analysis Configuration
    SENTIMENT_ENABLE: bool = Field(True, env="SENTIMENT_ENABLE")
    SENTIMENT_UPDATE_INTERVAL_MINUTES: int = Field(5, env="SENTIMENT_UPDATE_INTERVAL_MINUTES")
    SENTIMENT_NEWS_HOURS_BACK: int = Field(6, env="SENTIMENT_NEWS_HOURS_BACK")

    # News API Keys
    NEWSAPI_KEY: str = Field("", env="NEWSAPI_KEY")
    ALPHA_VANTAGE_KEY: str = Field("", env="ALPHA_VANTAGE_KEY")
    REDDIT_CLIENT_ID: str = Field("", env="REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = Field("", env="REDDIT_CLIENT_SECRET")

    # Sentiment Analysis Settings
    SENTIMENT_MODEL: str = Field("hybrid", env="SENTIMENT_MODEL")  # finbert, openai, hybrid
    SENTIMENT_MIN_CONFIDENCE: float = Field(0.6, env="SENTIMENT_MIN_CONFIDENCE")
    SENTIMENT_THRESHOLD: float = Field(0.3, env="SENTIMENT_THRESHOLD")

    # OpenAI Configuration
    OPENAI_API_KEY: str = Field("", env="OPENAI_API_KEY")
    OPENAI_MODEL: str = Field("gpt-4", env="OPENAI_MODEL")

    # Sentiment Filter Configuration
    SENTIMENT_FILTER_ENABLE_EXTREME_BLOCK: bool = Field(True, env="SENTIMENT_FILTER_ENABLE_EXTREME_BLOCK")
    SENTIMENT_FILTER_ENABLE_ALIGNMENT: bool = Field(True, env="SENTIMENT_FILTER_ENABLE_ALIGNMENT")
    SENTIMENT_FILTER_EXTREME_THRESHOLD: float = Field(0.8, env="SENTIMENT_FILTER_EXTREME_THRESHOLD")

    # Data Maintenance Configuration
    DATA_RETENTION_DAYS: int = Field(90, env="DATA_RETENTION_DAYS")
    GAP_FILL_ENABLED: bool = Field(True, env="GAP_FILL_ENABLED")
    CLEANUP_ENABLED: bool = Field(True, env="CLEANUP_ENABLED")
    MAINTENANCE_INTERVAL_HOURS: int = Field(24, env="MAINTENANCE_INTERVAL_HOURS")

    # Application
    APP_PORT: int = Field(8000, env="APP_PORT")
    AUTO_START_SCALPER: bool = Field(False, env="AUTO_START_SCALPER")
    AUTO_START_SCALPER_INSTRUMENTS: str = Field("nifty", env="AUTO_START_SCALPER_INSTRUMENTS")
    AUTO_START_INTRADAY: bool = Field(False, env="AUTO_START_INTRADAY")
    AUTO_START_INTRADAY_INSTRUMENTS: str = Field("indices", env="AUTO_START_INTRADAY_INSTRUMENTS")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }

settings = Settings()

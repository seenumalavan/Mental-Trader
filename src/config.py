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
    EMA_SHORT: int = Field(8, env="EMA_SHORT")
    EMA_LONG: int = Field(21, env="EMA_LONG")
    
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

    # Confirmation pipeline configuration
    CONFIRMATION_RECENT_BARS: int = Field(750, env="CONFIRMATION_RECENT_BARS")
    CONFIRMATION_REQUIRE_CPR: bool = Field(False, env="CONFIRMATION_REQUIRE_CPR")

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
    
    # Application
    APP_PORT: int = Field(8000, env="APP_PORT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }

settings = Settings()

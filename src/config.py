from matplotlib.sankey import UP
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = Field("sqlite:///mental_trader.db", env="DATABASE_URL")
    
    # Upstox API Configuration
    UPSTOX_ACCESS_TOKEN: str = Field("", env="UPSTOX_ACCESS_TOKEN")
    UPSTOX_API_KEY: str = Field("", env="UPSTOX_API_KEY") 
    UPSTOX_API_SECRET: str = Field("", env="UPSTOX_API_SECRET")
    UPSTOX_REDIRECT_URI: str = Field("", env="UPSTOX_REDIRECT_URI")
    UPSTOX_AUTH_URL: str = Field("https://api.upstox.com/index/dialog/authorize", env="UPSTOX_AUTH_URL")

    # Trading Configuration
    WATCHLIST: str = Field("RELIANCE,INFY,ICICIBANK", env="WATCHLIST")
    WARMUP_BARS: int = Field(2400, env="WARMUP_BARS")
    EMA_SHORT: int = Field(8, env="EMA_SHORT")
    EMA_LONG: int = Field(21, env="EMA_LONG")
    
    # Notifications
    NOTIFIER_WEBHOOK: str = Field("", env="NOTIFIER_WEBHOOK")
    # Email / SMTP (Gmail)
    SMTP_HOST: str = Field("smtp.gmail.com", env="SMTP_HOST")
    SMTP_PORT: int = Field(587, env="SMTP_PORT")
    SMTP_USERNAME: str = Field("", env="SMTP_USERNAME")
    SMTP_PASSWORD: str = Field("", env="SMTP_PASSWORD")
    SMTP_FROM: str = Field("", env="SMTP_FROM")
    SMTP_TO: str = Field("", env="SMTP_TO")
    SMTP_ENABLE: bool = Field(False, env="SMTP_ENABLE")

    # Scalper configuration
    SCALP_PRIMARY_TIMEFRAME: str = Field("1m", env="SCALP_PRIMARY_TIMEFRAME")
    SCALP_CONFIRM_TIMEFRAME: str = Field("5m", env="SCALP_CONFIRM_TIMEFRAME")
    SCALP_ENABLE_CONFIRM_FILTER: bool = Field(True, env="SCALP_ENABLE_CONFIRM_FILTER")
    # Intraday configuration (configurable primary and confirmation timeframes)
    INTRADAY_PRIMARY_TIMEFRAME: str = Field("5m", env="INTRADAY_PRIMARY_TIMEFRAME")
    INTRADAY_CONFIRM_TIMEFRAME: str = Field("15m", env="INTRADAY_CONFIRM_TIMEFRAME")
    INTRADAY_ENABLE_CONFIRM_FILTER: bool = Field(True, env="INTRADAY_ENABLE_CONFIRM_FILTER")
    
    # Application
    APP_PORT: int = Field(8000, env="APP_PORT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }

settings = Settings()

def watchlist_symbols() -> List[str]:
    return [s.strip() for s in settings.WATCHLIST.split(",") if s.strip()]

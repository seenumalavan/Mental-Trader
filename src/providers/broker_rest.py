import logging
from typing import List, Dict, Any
import asyncio
import math
import upstox_client
from upstox_client import ApiClient, MarketDataStreamerV3
from src.utils.instruments import get_symbol_to_key_mapping

logger = logging.getLogger("broker_rest")

class BrokerRest:
    def __init__(self, api_key: str, api_secret: str, access_token: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        
        # Load symbol mapping from instruments configuration
        try:
            self.symbol_map = get_symbol_to_key_mapping()
            logger.info(f"Loaded {len(self.symbol_map)} instrument mappings for broker_rest")
        except Exception as e:
            logger.error(f"Failed to load instrument mappings: {e}")
            self.symbol_map = {}
            
        # Initialize Upstox configuration
        try:
            self.configuration = upstox_client.Configuration()
            self.configuration.access_token = access_token or api_key
            
            # Initialize API clients
            api_client = upstox_client.ApiClient(self.configuration)
            self.login_api = upstox_client.LoginApi(api_client)
            self.order_api = upstox_client.OrderApi(api_client)
            self.historical_api = upstox_client.HistoryV3Api(api_client)
            logger.info("Upstox API clients initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Upstox API clients: {e}")
            self.configuration = None
            self.login_api = None
            self.market_data_api = None
            self.order_api = None
            self.historical_api = None

    async def ping(self) -> bool:
        """Test connection to Upstox API."""
        if upstox_client is None:
            logger.warning("Upstox SDK not available")
            return False
            
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.login_api.get_profile()
            )
            logger.info(f"Upstox connection successful: {response.data.user_name}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def fetch_historical(self, symbol: str, timeframe: str = "1m", limit: int = 375) -> List[Dict]:
        """Fetch historical candle data from Upstox."""           
        try:
            # Convert interval format (1m -> interval=1, unit=minute)
            interval, unit = self._convert_interval(timeframe)
            
            # Calculate date range for historical data
            from_date_str, to_date_str = self._calculate_date_range(timeframe, limit)
            
            logger.info(f"Fetching historical data for {symbol} from {from_date_str} to {to_date_str}")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.historical_api.get_historical_candle_data1(
                    symbol,
                    unit,
                    interval,
                    to_date=to_date_str,
                    from_date=from_date_str
                )
            )
            
            candles = []
            if response.data and response.data.candles:
                # for candle in response.data.candles[-limit:] # Get last 'limit' candles
                for candle in response.data.candles:  # Get last 'limit' candles
                    candles.append({
                        "ts": candle[0],  # timestamp
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                        "volume": int(candle[5]) if len(candle) > 5 else 0
                    })
            
            logger.info(f"Fetched {len(candles)} historical candles for {symbol}")
            return candles
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return []

    async def fetch_intraday(self, symbol: str, timeframe: str = "1m") -> List[Dict]:
        """Fetch current day's intraday candles (from today's open until now)."""
        try:
            interval, unit = self._convert_interval(timeframe)
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            # Use today for both from/to to get partial day; API should return up to current time.
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.historical_api.get_intra_day_candle_data(
                    symbol,
                    unit,
                    interval
                )
            )
            candles = []
            if response.data and response.data.candles:
                for candle in response.data.candles:
                    candles.append({
                        "ts": candle[0],
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                        "volume": int(candle[5]) if len(candle) > 5 else 0
                    })
            logger.info(f"Fetched {len(candles)} intraday candles for {symbol}")
            return candles
        except Exception as e:
            logger.error(f"Error fetching intraday data for {symbol}: {e}")
            return []

    async def place_order(self, payload: dict) -> Dict[str, Any]:
        """Place an order using Upstox API."""
        if upstox_client is None:
            logger.warning("Upstox SDK not available")
            return {"error": "SDK not available"}
            
        try:
            # Convert order data to Upstox format
            body = upstox_client.PlaceOrderRequest(
                quantity=payload.get("quantity", 1),
                product=upstox_client.Product.I,  # Intraday
                validity=upstox_client.Validity.DAY,
                price=payload.get("price", 0.0),
                tag="mental-trader",
                instrument_token=self._get_instrument_token(payload.get("symbol")),
                order_type=self._convert_order_type(payload.get("type", "MARKET")),
                transaction_type=self._convert_side(payload.get("side", "BUY")),
                disclosed_quantity=0,
                trigger_price=payload.get("trigger_price", 0.0),
                is_amo=False
            )
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.order_api.place_order(body)
            )
            
            if response.data:
                order_id = response.data.order_id
                logger.info(f"Order placed successfully: {order_id}")
                return {
                    "order_id": order_id,
                    "status": "placed",
                    "symbol": payload.get("symbol"),
                    "side": payload.get("side"),
                    "quantity": payload.get("quantity")
                }
            else:
                logger.error("No order data in response")
                return {"error": "No order data"}
               
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"error": str(e)}

    async def close(self):
        """Close any resources."""
        pass

    def _calculate_date_range(self, timeframe: str, limit: int) -> tuple:
        """Calculate from_date and to_date based on timeframe & desired candles.

        We approximate number of bars per trading day on NSE:
          - Trading session ~ 9:15 to 15:30 => 6h15m => 375 minutes.
          - For minute intervals: bars_per_day = floor(375 / interval_minutes).
          - For hour intervals: bars_per_day = floor(6.25 / interval_hours).
          - For daily timeframe: 1 bar per day.

        If limit exceeds bars_per_day, we extend from_date backwards enough days.
        Always set to_date to yesterday to avoid partial current day data.
        """
        from datetime import datetime, timedelta
        to_date = datetime.now() - timedelta(days=1)

        # Determine bars per day for given timeframe
        tf = timeframe.lower()
        bars_per_day = 1
        if tf.endswith("m"):
            try:
                interval = int(tf[:-1])
                trading_minutes = 375
                bars_per_day = max(1, trading_minutes // interval)
            except ValueError:
                bars_per_day = 375
        elif tf.endswith("h"):
            try:
                interval_h = int(tf[:-1])
                trading_hours = 6.25  # 6h15m session
                bars_per_day = max(1, int(trading_hours // interval_h))
            except ValueError:
                bars_per_day = 6
        elif tf.endswith("d"):
            bars_per_day = 1

        days_needed = max(1, math.ceil(limit / bars_per_day))
        from_date = to_date - timedelta(days=days_needed)

        to_date_str = to_date.strftime("%Y-%m-%d")
        from_date_str = from_date.strftime("%Y-%m-%d")
        logger.debug(
            "Date range calc timeframe=%s limit=%d bars_per_day=%d days_needed=%d from=%s to=%s",
            timeframe, limit, bars_per_day, days_needed, from_date_str, to_date_str
        )
        return from_date_str, to_date_str

    def _convert_interval(self, interval: str) -> tuple:
        """Convert interval format to Upstox interval and unit."""
        interval_map = {
            "1m": (1, "minutes"),
            "5m": (5, "minutes"), 
            "15m": (15, "minutes"),
            "30m": (30, "minutes"),
            "1h": (1, "hours"),
            "1d": (1, "days")
        }
        return interval_map.get(interval, (1, "minutes"))

    def _convert_symbol(self, symbol: str) -> str:
        """Convert symbol to Upstox instrument token format using instruments.py mapping."""
        instrument_key = self.symbol_map.get(symbol)
        if instrument_key:
            return instrument_key
        
        # Fallback for unmapped symbols
        logger.warning(f"Symbol {symbol} not found in instrument mapping, using fallback")
        return f"NSE_EQ|{symbol}"

    def _get_instrument_token(self, symbol: str) -> str:
        """Get instrument token for symbol."""
        return self._convert_symbol(symbol)

    def _convert_order_type(self, order_type: str) -> str:
        """Convert order type to Upstox format."""
        if order_type.upper() == "MARKET":
            return upstox_client.OrderType.MARKET
        elif order_type.upper() == "LIMIT":
            return upstox_client.OrderType.LIMIT
        else:
            return upstox_client.OrderType.MARKET

    def _convert_side(self, side: str) -> str:
        """Convert side to Upstox transaction type."""
        if side.upper() == "BUY":
            return upstox_client.TransactionType.BUY
        else:
            return upstox_client.TransactionType.SELL

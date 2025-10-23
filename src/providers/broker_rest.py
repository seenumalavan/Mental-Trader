import asyncio
import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
import upstox_client
from dateutil import parser

from src.utils.instruments import get_symbol_to_key_mapping
from src.utils.orders_enum import Product, Validity
from src.utils.time_utils import IST

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
            self.options_api = upstox_client.OptionsApi(api_client)
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
                product=Product.I,  # Intraday
                validity=Validity.DAY,
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

    # ---------------- Option / Derivatives Helpers -----------------
    def get_underlying_price(self, underlying_symbol: str) -> Dict[str, Any]:
        """Fetch underlying price using Upstox HistoricalApi."""
        try:
            fut_symbol = self._derive_futures_symbol(underlying_symbol)
            data = self.historical_api.get_intra_day_candle_data(fut_symbol, "minutes", 1)
            
            # Fallback to historical single candle if intraday empty
            if (not data) or (not getattr(data, 'data', None)) or (not data.data.candles):
                from_to_date = pd.Timestamp.now(tz=IST) - timedelta(days=1)
                to_date_str = from_to_date.strftime("%Y-%m-%d")
                from_date_str = from_to_date.strftime("%Y-%m-%d")

                data = self.historical_api.get_historical_candle_data1(
                        fut_symbol,
                        "minutes",
                        1,
                        to_date=to_date_str,
                        from_date=from_date_str
                    )
            last_price = 0.0
            if data and getattr(data, 'data', None) and data.data.candles:
                last_candle = data.data.candles[-1]
                last_price = float(last_candle[4])
            return {"last_price": last_price, "instrument": fut_symbol, "source": source}
        except Exception as e:
            logger.warning("get_underlying_price failed: %s", e)
            return {"last_price": 0.0, "status": "ERROR"}

    def find_nearest_expiry(self, instrument_key: str) -> str:
        """Find the nearest expiry date for the given underlying instrument key."""
        try:
            # Fetch option contracts
            response = self.options_api.get_option_contracts(instrument_key)
            contracts = response.data

            if not contracts:
                logger.warning("No option contracts found for %s", instrument_key)
                return None

            # Extract unique expiry dates
            expiry_dates = set()
            for contract in contracts:
                if hasattr(contract, 'expiry') and contract.expiry:
                    expiry_dates.add(contract.expiry)

            if not expiry_dates:
                logger.warning("No expiry dates found in contracts for %s", instrument_key)
                return None

            # Parse current date and expiry dates
            current_date = datetime.now().date()
            parsed_expiries = []
            for expiry in expiry_dates:
                if isinstance(expiry, str):
                    parsed_expiries.append(parser.parse(expiry).date())
                elif isinstance(expiry, (datetime, date)):
                    parsed_expiries.append(expiry.date() if isinstance(expiry, datetime) else expiry)
                else:
                    logger.warning("Invalid expiry format: %s", expiry)
                    continue

            # Filter future expiries and find the nearest
            future_expiries = [exp for exp in parsed_expiries if exp >= current_date]
            if not future_expiries:
                logger.warning("No future expiry dates found for %s", instrument_key)
                return None

            # Find the nearest expiry
            nearest_expiry = min(future_expiries, key=lambda x: (x - current_date).days)
            return nearest_expiry.strftime('%Y-%m-%d')
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return None

    def get_option_chain(self, instrument_key: str) -> List[Dict[str, Any]]:
        """Fetch option chain for the given underlying instrument key."""
        if upstox_client is None:
            return []
        try:
            # Find nearest expiry
            expiry_date = self.find_nearest_expiry(instrument_key)
            if not expiry_date:
                logger.warning("No expiry found for %s", instrument_key)
                return []
            
            # Fetch option chain for nearest expiry
            response = self.options_api.get_put_call_option_chain(instrument_key, expiry_date)
            
            chain = []
            if response.data:
                for item in response.data:
                    # Extract call option
                    if item.call_options and item.call_options.market_data:
                        call_md = item.call_options.market_data
                        call_greeks = item.call_options.option_greeks
                        chain.append({
                            'symbol': item.call_options.instrument_key,
                            'strike': item.strike_price,
                            'type': 'CALL',
                            'expiry': item.expiry.strftime('%Y-%m-%d') if item.expiry else expiry_date,
                            'oi': call_md.oi or 0,
                            'iv': call_greeks.iv or 0.0,
                            'ltp': call_md.ltp or 0.0,
                            'bid': call_md.bid_price or 0.0,
                            'ask': call_md.ask_price or 0.0,
                            'delta': call_greeks.delta,
                            'gamma': call_greeks.gamma,
                            'theta': call_greeks.theta,
                            'vega': call_greeks.vega
                        })
                    
                    # Extract put option
                    if item.put_options and item.put_options.market_data:
                        put_md = item.put_options.market_data
                        put_greeks = item.put_options.option_greeks
                        chain.append({
                            'symbol': item.put_options.instrument_key,
                            'strike': item.strike_price,
                            'type': 'PUT',
                            'expiry': item.expiry.strftime('%Y-%m-%d') if item.expiry else expiry_date,
                            'oi': put_md.oi or 0,
                            'iv': put_greeks.iv or 0.0,
                            'ltp': put_md.ltp or 0.0,
                            'bid': put_md.bid_price or 0.0,
                            'ask': put_md.ask_price or 0.0,
                            'delta': put_greeks.delta,
                            'gamma': put_greeks.gamma,
                            'theta': put_greeks.theta,
                            'vega': put_greeks.vega
                        })
            
            logger.info(f"Fetched {len(chain)} options from Upstox API for {instrument_key}")
            return chain
        except Exception as e:
            logger.warning("Upstox option chain API failed: %s, falling back to synthetic", e)
            # Fallback to synthetic chain if API fails
            spot_info = self.get_underlying_price(instrument_key)
            spot = spot_info.get('last_price', 0.0)
            if spot <= 0:
                spot = 0.0
            # Determine ATM strike rounding to nearest 50
            atm = int(round(spot / 50.0) * 50) if spot > 0 else 0
            strikes = [atm - 50, atm, atm + 50] if atm > 0 else []
            chain: List[Dict[str, Any]] = []
            for strike in strikes:
                for opt_type in ("CALL", "PUT"):
                    # Synthetic symbol pattern (needs real mapping): e.g. NIFTY24OCT{strike}{CE/PE}
                    suffix = "CE" if opt_type == "CALL" else "PE"
                    symbol = f"{instrument_key.upper()}_OPT_{strike}{suffix}"
                    # Placeholder values (would come from market data api)
                    ltp = max(1.0, abs(atm - strike) * 0.4 + (10 if opt_type == 'CALL' else 9))
                    bid = ltp - 0.5
                    ask = ltp + 0.5
                    oi = 100000 + (strike - atm) * 200 if opt_type == 'CALL' else 95000 + (atm - strike) * 180
                    iv = 12.0 + ((strike - atm) / 1000.0)
                    chain.append({
                        'symbol': symbol,
                        'strike': strike,
                        'type': opt_type,
                        'expiry': datetime.now().strftime('%Y-%m-%d'),
                        'oi': max(int(oi), 1000),
                        'iv': max(iv, 5.0),
                        'ltp': ltp,
                        'bid': bid,
                        'ask': ask
                    })
            return chain

    def _derive_futures_symbol(self, underlying_symbol: str) -> str:
        """Derive a futures symbol token placeholder from an underlying equity/index symbol.

        For NIFTY use an approximate token name pattern; real implementation should map using instrument file.
        """
        # Simple heuristic (to be replaced with actual mapping):
        if underlying_symbol.lower() in ("nifty", "nifty 50", "nifty50"):
            return "NSE_INDEX|Nifty 50"  # Example mapping key
        return underlying_symbol

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

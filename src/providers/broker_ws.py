import asyncio
import logging
from typing import Callable, Dict, List

try:
    import upstox_client
    from google.protobuf.json_format import MessageToDict
    from upstox_client import ApiClient, MarketDataStreamerV3
    print(f"DEBUG: broker_ws successfully imported upstox_client: {upstox_client}")
except ImportError as e:
    print(f"DEBUG: broker_ws failed to import upstox_client: {e}")
    upstox_client = None
    ApiClient = None
    MarketDataStreamerV3 = None
    MessageToDict = None

from src.utils.instruments import (get_instruments, get_symbol_to_key_mapping)
from src.utils.time_utils import parse_timestamp

logger = logging.getLogger("broker_ws")

class BrokerWS:
    """Simplified Upstox WebSocket client for market data streaming."""

    def __init__(self, access_token: str):
        """Initialize WebSocket client with API key."""
        if upstox_client is None:
            logger.error("Upstox SDK not installed. Install with: pip install upstox-python-sdk")
            raise ImportError("Upstox SDK required")

        self.access_token = access_token
        self.streamer = None
        self.on_tick: Callable = None
        self._running = False
        self._loop = None
        self.instrument_to_symbol: Dict[str, str] = {}
        
        # Load symbol mapping from configuration
        try:
            self.symbol_map = get_symbol_to_key_mapping()
            logger.info(f"Loaded {len(self.symbol_map)} instrument mappings")
        except Exception as e:
            logger.error(f"Failed to load instrument mappings: {e}")
            self.symbol_map = {}

    async def connect(self):
        """Connect to Upstox WebSocket feed."""
        if self._running:
            logger.info("WebSocket already connected")
            return
        self._loop = asyncio.get_running_loop()
        self._running = True
        logger.info("Upstox WebSocket connection initiated")

    async def disconnect(self):
        """Disconnect from Upstox WebSocket."""
        if not self._running:
            return
        if self.streamer:
            try:
                self.streamer.disconnect()
                logger.info("Upstox WebSocket disconnected")
            except Exception as e:
                logger.warning(f"Error during WebSocket disconnect: {e}")
        self._running = False

    async def subscribe(self, symbols: List[str]):
        """Subscribe to market data for given symbols or categories."""
        try:
            # Expand symbols/categories to instrument keys
            all_instrument_keys = []
            all_symbols = []
            
            for symbol_or_category in symbols:
                # Check if it's a category (nifty, indices, futures, options, etc.)
                category_instruments = get_instruments(symbol_or_category.lower())
                
                if category_instruments:
                    # It's a category - expand to all instruments in that category
                    logger.info(f"Expanding category '{symbol_or_category}' to {len(category_instruments)} instruments")
                    
                    if isinstance(category_instruments, list):
                        # Handle list format (nifty, banknifty, indices)
                        for item in category_instruments:
                            if isinstance(item, dict):
                                for symbol_desc, key in item.items():
                                    # Keep full symbol format: "ADANIENT(Adani Enterpris)"
                                    all_instrument_keys.append(key)
                                    all_symbols.append(symbol_desc)
                                    self.instrument_to_symbol[key] = symbol_desc
                            else:
                                # Handle direct string items
                                all_instrument_keys.append(item)
                                all_symbols.append(item)
                                self.instrument_to_symbol[item] = item
                    
                    elif isinstance(category_instruments, dict):
                        # Handle dict format (futures, options)
                        for symbol_desc, key in category_instruments.items():
                            all_instrument_keys.append(key)
                            all_symbols.append(symbol_desc)
                            self.instrument_to_symbol[key] = symbol_desc
                else:
                    # It's an individual symbol - convert to instrument key
                    instrument_key = self._symbol_to_key(symbol_or_category)
                    all_instrument_keys.append(instrument_key)
                    all_symbols.append(symbol_or_category)
                    self.instrument_to_symbol[instrument_key] = symbol_or_category

            # Remove duplicates while preserving order
            unique_keys = []
            seen = set()
            for key in all_instrument_keys:
                if key not in seen:
                    unique_keys.append(key)
                    seen.add(key)

            if not unique_keys:
                logger.warning(f"No valid instruments found for: {symbols}")
                return

            # Disconnect any existing streamer before creating a new one
            if self.streamer:
                try:
                    self.streamer.disconnect()
                    logger.info("Disconnected existing WebSocket streamer")
                except Exception as e:
                    logger.warning(f"Error disconnecting existing streamer: {e}")
                self.streamer = None

            # Initialize Upstox streamer
            config = upstox_client.Configuration()
            config.access_token = self.access_token
            api_client = ApiClient(config)
            self.streamer = MarketDataStreamerV3(api_client, unique_keys, "ltpc")
            self.streamer.on("message", self._process_message)
            self.streamer.on("error", self._handle_error)
            self.streamer.on("close", self._handle_close)
            self.streamer.connect()
            
            logger.info(f"Subscribed to {len(unique_keys)} instruments from input: {symbols}")
            logger.info(f"Instruments: {list(set(all_symbols))[:10]}{'...' if len(all_symbols) > 10 else ''}")
            
        except Exception as e:
            logger.error(f"Failed to subscribe to symbols {symbols}: {e}")
            raise

    def _process_message(self, message):
        """Process incoming WebSocket message synchronously."""
        try:
            parsed = MessageToDict(message) if MessageToDict and hasattr(message, 'DESCRIPTOR') else message
            if not isinstance(parsed, dict) or 'feeds' not in parsed:
                logger.warning(f"Invalid message structure: {parsed}")
                return

            for instrument_key, feed_data in parsed['feeds'].items():
                if 'ltpc' not in feed_data:
                    continue

                ltpc = feed_data['ltpc']
                symbol = self.instrument_to_symbol.get(instrument_key, instrument_key.split("|")[-1])
                tick = {
                    "symbol": symbol,
                    "instrument_key": instrument_key,
                    "price": float(ltpc.get('ltp', 0.0)),
                    "volume": int(feed_data.get('vtt', 1)),
                    "ts": parse_timestamp(ltpc.get('ltt', ''))
                }

                if self.on_tick:
                    # Schedule async callback in the event loop
                    if self._loop and not self._loop.is_closed():
                        asyncio.run_coroutine_threadsafe(self.on_tick(tick), self._loop)
                    else:
                        logger.warning("Event loop not available for async callback")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _handle_error(self, error):
        """Handle WebSocket errors."""
        logger.error(f"WebSocket error: {error}")
        self._running = False

    def _handle_close(self, code=None, reason=None):
        """Handle WebSocket connection close."""
        logger.warning(f"WebSocket connection closed: code={code}, reason={reason}")
        self._running = False

    def _symbol_to_key(self, symbol: str) -> str:
        """Convert trading symbol to Upstox instrument key."""
        instrument_key = self.symbol_map.get(symbol)
        if instrument_key:
            return instrument_key
        
        # Fallback for unmapped symbols
        logger.warning(f"Symbol {symbol} not found in instrument mapping, using fallback")
        return f"NSE_EQ|{symbol}"
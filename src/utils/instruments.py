import json
import logging
import os

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '../data/instruments_config.json')

def load_instruments():
    """Load instruments configuration from JSON file."""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Instruments file not found at {CONFIG_FILE}")
        raise FileNotFoundError(f"Instruments file not found at {CONFIG_FILE}")
    
    with open(CONFIG_FILE, 'r') as file:
        data = json.load(file)
    return {key.lower(): value for key, value in data.items()}

def get_instruments(category: str):
    """Get instruments for a specific category."""
    instruments = load_instruments()
    return instruments.get(category.lower(), [])

def resolve_instruments(input_data):
    """
    Resolve instruments from various input formats.
    
    Args:
        input_data: Can be:
            - String: "nifty", "indices", "RELIANCE", or comma-separated symbols
            - List: ["nifty", "indices"] or ["RELIANCE", "TCS"]
    
    Returns:
        List of dicts: [{'symbol': 'RELIANCE', 'instrument_key': 'NSE_EQ|INE002A01018'}, ...]
    """
    if not input_data:
        return []
    
    result = []
    instruments_config = load_instruments()
    
    # Handle list input (multiple categories or symbols)
    if isinstance(input_data, list):
        for item in input_data:
            result.extend(_resolve_single_item(item.strip(), instruments_config))
    else:
        # Handle string input (single category or comma-separated symbols)
        input_str = str(input_data).strip()
        if ',' in input_str:
            # Comma-separated symbols
            symbols = [s.strip() for s in input_str.split(',') if s.strip()]
            for symbol in symbols:
                result.extend(_resolve_single_item(symbol, instruments_config))
        else:
            # Single category or symbol
            result.extend(_resolve_single_item(input_str, instruments_config))
    
    return result

def _resolve_single_item(item: str, instruments_config: dict):
    """Resolve a single item (category or symbol) to instrument list."""
    item_lower = item.lower()
    
    # Check if it's a category (nifty, indices, banknifty, etc.)
    if item_lower in instruments_config:
        category_instruments = instruments_config[item_lower]
        result = []
        
        for instrument_data in category_instruments:
            if isinstance(instrument_data, dict):
                # Handle format: {"ADANIENT(Adani Enterpris)": "NSE_EQ|INE423A01024"}
                # Keep the full symbol with description, don't extract
                for symbol_desc, instrument_key in instrument_data.items():
                    result.append({'symbol': symbol_desc, 'instrument_key': instrument_key})
            else:
                # Handle direct string format (if any)
                result.append({'symbol': str(instrument_data), 'instrument_key': str(instrument_data)})
        
        return result
    else:
        # Not a category, treat as individual symbol
        # Try to find instrument key from symbol mapping
        symbol_map = get_symbol_to_key_mapping()
        instrument_key = symbol_map.get(item, item)  # Use symbol as fallback
        return [{'symbol': item, 'instrument_key': instrument_key}]

# Keep old function for backward compatibility but mark as deprecated
def resolve_instrument_key(input_symbol_category: str):
    """
    DEPRECATED: Use resolve_instruments() instead.
    This function is kept for backward compatibility.
    """
    logger.warning("resolve_instrument_key() is deprecated. Use resolve_instruments() instead.")
    return resolve_instruments(input_symbol_category)

def get_symbol_to_key_mapping():
    """Create a flat mapping of symbol to instrument key for quick lookup."""
    instruments = load_instruments()
    symbol_map = {}
    
    # Process nifty stocks - keep full symbol with description
    for item in instruments.get('nifty', []):
        if isinstance(item, dict):
            for symbol_desc, key in item.items():
                symbol_map[symbol_desc] = key  # Keep full "ADANIENT(Adani Enterpris)" format
    
    # Process banknifty stocks - keep full symbol with description  
    for item in instruments.get('banknifty', []):
        if isinstance(item, dict):
            for symbol_desc, key in item.items():
                symbol_map[symbol_desc] = key  # Keep full format
    
    # Process indices - keep full symbol with description
    for item in instruments.get('indices', []):
        if isinstance(item, dict):
            for symbol_desc, key in item.items():
                symbol_map[symbol_desc] = key  # Keep full format
    
    # Process futures (direct mapping)
    for symbol, key in instruments.get('futures', {}).items():
        symbol_map[symbol] = key
    
    # Process options (direct mapping)
    for symbol, key in instruments.get('options', {}).items():
        symbol_map[symbol] = key
    
    return symbol_map
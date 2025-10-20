# Instruments Usage Guide

This document explains how to use the instruments system in Mental Trader.

## Key Concepts

- **Symbol**: The full trading symbol with description (e.g., "ADANIENT(Adani Enterpris)") - this is the KEY in your JSON config
- **Instrument Key**: The Upstox API identifier (e.g., "NSE_EQ|INE423A01024") - this is the VALUE in your JSON config  
- **Category**: Groups of instruments (e.g., "nifty", "indices", "banknifty")

## JSON Configuration Format

Your `src/data/instruments_config.json` should look like:

```json
{
  "nifty": [
    {"ADANIENT(Adani Enterpris)": "NSE_EQ|INE423A01024"},
    {"RELIANCE(Reliance Industries)": "NSE_EQ|INE002A01018"},
    {"TCS(Tata Consultancy Services)": "NSE_EQ|INE467B01029"},
    {"HDFCBANK(HDFC Bank)": "NSE_EQ|INE040A01034"}
  ],
  "indices": [
    {"NIFTY 50": "NSE_INDEX|Nifty 50"},
    {"BANKNIFTY": "NSE_INDEX|Nifty Bank"}
  ],
  "banknifty": [
    {"HDFCBANK(HDFC Bank)": "NSE_EQ|INE040A01034"},
    {"ICICIBANK(ICICI Bank)": "NSE_EQ|INE090A01021"}
  ]
}
```

## Usage Examples

### 1. Trade All Nifty Stocks
```python
# In code
await service.start("nifty")

# Via API
POST /control/start
{
  "instruments": "nifty"
}
```

### 2. Trade All Indices
```python
# In code  
await service.start("indices")

# Via API
POST /control/start
{
  "instruments": "indices"
}
```

### 3. Trade Both Nifty Stocks and Indices
```python
# In code
await service.start(["nifty", "indices"])

# Via API
POST /control/start
{
  "instruments": ["nifty", "indices"]
}
```

### 4. Trade Specific Stocks (Comma-separated)
```python
# In code
await service.start("ADANIENT(Adani Enterpris),RELIANCE(Reliance Industries),HDFCBANK(HDFC Bank)")

# Via API
POST /control/start
{
  "instruments": "ADANIENT(Adani Enterpris),RELIANCE(Reliance Industries),HDFCBANK(HDFC Bank)"
}
```

### 5. Trade Specific Stocks (Array format)
```python
# In code
await service.start(["ADANIENT(Adani Enterpris)", "RELIANCE(Reliance Industries)", "HDFCBANK(HDFC Bank)"])

# Via API
POST /control/start
{
  "instruments": ["ADANIENT(Adani Enterpris)", "RELIANCE(Reliance Industries)", "HDFCBANK(HDFC Bank)"]
}
```

## Testing Instrument Resolution

Use the resolve endpoint to see what instruments will be used:

```bash
# Test category resolution
curl -X POST "http://localhost:8000/instruments/resolve" \
  -H "Content-Type: application/json" \
  -d '{"instruments": "nifty"}'

# Test mixed resolution
curl -X POST "http://localhost:8000/instruments/resolve" \
  -H "Content-Type: application/json" \
  -d '{"instruments": ["nifty", "indices"]}'

# Test specific symbols
curl -X POST "http://localhost:8000/instruments/resolve" \
  -H "Content-Type: application/json" \
  -d '{"instruments": "ADANIENT(Adani Enterpris),RELIANCE(Reliance Industries)"}'
```

## Response Format

All resolved instruments return this format:
```json
{
  "input": "nifty",
  "resolved_count": 3,
  "instruments": [
    {
      "symbol": "ADANIENT(Adani Enterpris)", 
      "instrument_key": "NSE_EQ|INE423A01024"
    },
    {
      "symbol": "RELIANCE(Reliance Industries)",
      "instrument_key": "NSE_EQ|INE002A01018"  
    },
    {
      "symbol": "HDFCBANK(HDFC Bank)",
      "instrument_key": "NSE_EQ|INE040A01034"
    }
  ]
}
```

## How It Works Internally

1. **Input Processing**: The system accepts string or array inputs
2. **Category Check**: If input matches a category key ("nifty", "indices"), it loads all instruments from that category
3. **Symbol Resolution**: Individual symbols are looked up in the symbol-to-key mapping
4. **Database Storage**: Both symbol and instrument_key are stored for each candle/trade
5. **API Calls**: Upstox APIs use the instrument_key for data fetching
6. **User Display**: Symbols are used for user-facing operations

## Benefits

- ✅ **Flexible Input**: Supports categories, individual symbols, or mixed arrays
- ✅ **Clear Separation**: Symbol (user-facing) vs Instrument Key (API-facing) 
- ✅ **Easy Configuration**: JSON-based instrument mapping
- ✅ **Scalable**: Easy to add new categories or instruments
- ✅ **Testable**: Resolve endpoint for testing configurations
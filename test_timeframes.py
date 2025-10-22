timeframes = ['1m', '5m', '15m', '1h']
for timeframe in timeframes:
    if timeframe.endswith('m'):
        timeframe_minutes = int(timeframe.rstrip('m'))
    elif timeframe.endswith('h'):
        timeframe_minutes = int(timeframe.rstrip('h')) * 60
    else:
        timeframe_minutes = 1
    min_candles_needed = (375 // timeframe_minutes) * 2
    print(f'{timeframe}: {timeframe_minutes} min, need {min_candles_needed} candles')
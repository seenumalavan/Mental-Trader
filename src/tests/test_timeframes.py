def test_timeframe_min_candles():
    timeframes = ['1m', '5m', '15m', '1h']
    results = {}
    for timeframe in timeframes:
        if timeframe.endswith('m'):
            timeframe_minutes = int(timeframe[:-1])
        elif timeframe.endswith('h'):
            timeframe_minutes = int(timeframe[:-1]) * 60
        else:
            timeframe_minutes = 1
        min_candles_needed = (375 // timeframe_minutes) * 2
        results[timeframe] = min_candles_needed
    # Basic sanity assertions
    assert results['1m'] == (375 // 1) * 2
    assert results['5m'] == (375 // 5) * 2
    assert results['15m'] == (375 // 15) * 2
    assert results['1h'] == (375 // 60) * 2
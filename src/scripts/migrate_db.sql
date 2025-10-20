-- Run once to create additional indexes if desired
CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles (ts);
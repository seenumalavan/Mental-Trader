from src.engine.bar_builder import BarBuilder

def test_bar_builder_basic():
    bb = BarBuilder()
    t1 = {'symbol':'T','price':100,'volume':1,'ts':'2025-10-15T09:15:10+00:00'}
    t2 = {'symbol':'T','price':101,'volume':2,'ts':'2025-10-15T09:15:30+00:00'}
    closed = bb.push_tick(t1)
    assert closed == []
    closed = bb.push_tick(t2)
    assert closed == []
    t3 = {'symbol':'T','price':102,'volume':1,'ts':'2025-10-15T09:16:05+00:00'}
    closed = bb.push_tick(t3)
    assert len(closed) >= 1

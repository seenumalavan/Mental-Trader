from prometheus_client import Counter, Histogram

signals_counter = Counter("scalper_signals_total", "Total signals generated")
orders_counter = Counter("scalper_orders_total", "Total orders placed")
order_latency = Histogram("scalper_order_latency_seconds", "Order latency seconds")

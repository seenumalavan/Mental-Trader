import importlib

CRITICAL_IMPORTS = [
    ("src.config", "settings"),
    ("src.engine.bar_builder", "BarBuilder"),
    ("src.engine.ema", "EMAState"),
    ("src.execution.execution", "Executor"),
    ("src.persistence.db", "Database"),
    ("src.services.scalping_service", "ScalperService"),
]

def test_critical_imports():
    missing = []
    for module_name, symbol in CRITICAL_IMPORTS:
        module = importlib.import_module(module_name)
        if not hasattr(module, symbol):
            missing.append(f"{module_name}:{symbol}")
    assert not missing, f"Missing symbols: {missing}"

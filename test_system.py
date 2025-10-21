#!/usr/bin/env python3
"""
Mental Trader - Import Test
Quick test to verify all imports work correctly.
"""
import os
import sys

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test all critical imports."""
    import_tests = [
        # Core config
        ("Config", "from src.config import settings, watchlist_symbols"),
        
        # Engine components
        ("Bar Builder", "from src.engine.bar_builder import BarBuilder, Bar"),
        ("EMA", "from src.engine.ema import EMAState"),
        ("Strategy", "from src.engine.scalping_strategy import ScalpStrategy"),
        
        # Execution
        ("Execution", "from src.execution.execution import Executor, Signal"),
        
        # Persistence
        ("Database", "from src.persistence.db import Database"),
        ("Models", "from src.persistence.models import Candle, Trade, EMAStateRecord"),
        
        # Providers
        ("Broker REST", "from src.providers.broker_rest import BrokerRest"),
        ("Broker WS", "from src.providers.broker_ws import BrokerWS"),
        
        # Services
        ("Scalping Service", "from src.services.scalping_service import ScalperService"),
        ("Notifier", "from src.services.notifier import Notifier"),
        ("Risk Manager", "from src.services.risk_manager import RiskManager"),
        
        # Utils
        ("Logging Config", "from src.utils.logging_config import configure_logging"),
        ("Time Utils", "from src.utils.time_utils import to_ist"),
    ]
    
    results = []
    for name, import_stmt in import_tests:
        try:
            exec(import_stmt)
            results.append((name, "✓", None))
            print(f"✓ {name}")
        except Exception as e:
            results.append((name, "✗", str(e)))
            print(f"✗ {name}: {e}")
    
    # Summary
    print("\n" + "="*50)
    print("IMPORT TEST SUMMARY")
    print("="*50)
    
    successful = sum(1 for _, status, _ in results if status == "✓")
    total = len(results)
    
    print(f"Successful: {successful}/{total}")
    
    if successful == total:
        print("🎉 All imports working correctly!")
        return True
    else:
        print("❌ Some imports failed. Check the errors above.")
        print("\nFailed imports:")
        for name, status, error in results:
            if status == "✗":
                print(f"  - {name}: {error}")
        return False


def test_basic_functionality():
    """Test basic functionality without external dependencies."""
    print("\n" + "="*50)
    print("BASIC FUNCTIONALITY TESTS")
    print("="*50)
    
    try:
        # Test bar builder
        from src.engine.bar_builder import BarBuilder
        bb = BarBuilder()
        print("✓ BarBuilder instantiation")
        
        # Test EMA
        from src.engine.ema import EMAState
        ema = EMAState("TEST", "1m", 8, 21)
        print("✓ EMAState instantiation")
        
        # Test signal
        from src.execution.execution import Signal
        signal = Signal("TEST", "BUY", 100.0, 1, 99.0, 101.0)
        print("✓ Signal creation")
        
        # Test config
        from src.config import watchlist_symbols
        symbols = watchlist_symbols()
        print(f"✓ Config loaded, watchlist: {symbols}")
        
        print("\n🎉 Basic functionality tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Basic functionality test failed: {e}")
        return False


if __name__ == "__main__":
    print("Mental Trader - Import and Functionality Test")
    print("=" * 50)
    
    import_success = test_imports()
    if import_success:
        func_success = test_basic_functionality()
        
        if func_success:
            print("\n🎉 All tests passed! The system is ready to use.")
            print("\nNext steps:")
            print("1. Configure your .env file with broker credentials")
            print("2. Set up your PostgreSQL database")
            print("3. Start trading:")
            print("   - CLI mode: python main.py")
            print("   - Web mode: python main.py --web")
        else:
            print("\n❌ Some functionality tests failed.")
            sys.exit(1)
    else:
        print("\n❌ Import tests failed.")
        sys.exit(1)
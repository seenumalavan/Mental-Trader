#!/usr/bin/env python3
"""
Mental Trader - Main Entry Point
Simple web server for the trading system.
"""
import os
import sys

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import the FastAPI app to make it available at module level
try:
    from src.app import app
except ImportError as e:
    print(f"Failed to import app: {e}")
    app = None

if __name__ == "__main__":
    if app is None:
        print("Error: Failed to load the FastAPI application")
        sys.exit(1)
        
    try:
        import uvicorn
        print("Starting Mental Trader...")
        print("Web Interface: http://localhost:8000")
        print("API Docs: http://localhost:8000/docs")
        print("Press Ctrl+C to stop.")
        
        uvicorn.run(
            app,  # Use the imported app directly
            host="0.0.0.0",
            port=8000,
            reload=False
        )
    except ImportError:
        print("Error: uvicorn is required. Install it with:")
        print("pip install uvicorn")
        sys.exit(1)
    except Exception as e:
        print(f"Failed to start: {e}")
        sys.exit(1)

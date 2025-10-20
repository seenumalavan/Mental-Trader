import logging
import sys

def configure_logging():
    """Configure logging for the application."""
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

# Make sure the function is available for import
__all__ = ['configure_logging']

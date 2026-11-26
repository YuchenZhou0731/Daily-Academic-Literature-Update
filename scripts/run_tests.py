"""Run all offline behavioral tests without external credentials or requests."""
from pathlib import Path
import sys
import unittest

directory = Path(__file__).resolve().parent
sys.path.insert(0, str(directory))
suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

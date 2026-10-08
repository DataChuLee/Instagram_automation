"""Use the application dependencies without modifying the system Python."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
suite = unittest.TestSuite()
suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests')))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

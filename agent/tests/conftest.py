import sys
from unittest.mock import MagicMock

for _name in ("win32gui", "win32process", "win32api", "win32con"):
    sys.modules.setdefault(_name, MagicMock())

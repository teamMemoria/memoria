"""Compatibility import while the dependent slice is being applied."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.providers.database")

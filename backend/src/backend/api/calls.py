"""Compatibility import; implementation lives in frameworks.http.calls."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.frameworks.http.calls")

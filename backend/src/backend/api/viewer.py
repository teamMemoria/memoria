"""Compatibility import; implementation lives in frameworks.http.viewer."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.frameworks.http.viewer")

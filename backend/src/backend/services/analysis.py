"""Compatibility import; implementation lives in frameworks.data_access.analysis."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.frameworks.data_access.analysis")

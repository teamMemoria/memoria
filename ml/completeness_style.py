"""Compatibility import for rules.completeness_style."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("ml.rules.completeness_style")

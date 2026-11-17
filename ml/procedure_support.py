"""Compatibility import for rules.procedure_support."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("ml.rules.procedure_support")

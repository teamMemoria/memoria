"""Compatibility import; implementation lives in entities.identity."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.entities.identity")

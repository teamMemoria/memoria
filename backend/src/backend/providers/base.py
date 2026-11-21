"""Compatibility import for the adapter-facing projection ports."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.interface_adapters.ports")

"""Compatibility import for backend.frameworks.database.models.knowledge."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.frameworks.database.models.knowledge")

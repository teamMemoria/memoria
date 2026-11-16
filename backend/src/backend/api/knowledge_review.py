"""Compatibility import; implementation lives in frameworks.http.knowledge_review."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("backend.frameworks.http.knowledge_review")

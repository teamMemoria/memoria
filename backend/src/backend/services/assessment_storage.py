"""Compatibility import; implementation lives in frameworks.data_access.assessment_storage."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module(
    "backend.frameworks.data_access.assessment_storage"
)

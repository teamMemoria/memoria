"""Compatibility exports; keep this package path for legacy submodule shims."""

from backend.frameworks.database import models as _models

__all__ = _models.__all__
globals().update({name: getattr(_models, name) for name in __all__})

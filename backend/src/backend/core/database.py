from sqlalchemy.orm import DeclarativeBase

# The engine and sessions live in backend.db.session, and the database URL in
# backend.core.config.Settings. This module only holds the model base class.


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

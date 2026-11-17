from enum import StrEnum

from sqlalchemy import Enum


def str_enum(enum: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum as varchar with a CHECK constraint on its values."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )

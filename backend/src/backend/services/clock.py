from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time in UTC. Services take it as a parameter so tests can fix it."""
    return datetime.now(UTC)

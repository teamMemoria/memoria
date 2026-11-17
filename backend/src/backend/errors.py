"""Shared application errors; HTTP adapters choose response status codes."""


class ProviderUnavailableError(Exception):
    """The data source could not be reached."""


class RecordNotFoundError(Exception):
    """The record does not exist or is not visible to the requester."""


class ConflictError(Exception):
    """The write disagrees with what is already stored."""

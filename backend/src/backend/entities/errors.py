"""Application errors; HTTP adapters choose response status codes."""


class ProviderUnavailableError(Exception):
    """The data source could not be reached. Routes turn this into a 503, not an empty result."""


class RecordNotFoundError(Exception):
    """The record does not exist or is not visible to the requester (a 404)."""


class ConflictError(Exception):
    """The write disagrees with what is already stored (a 409)."""

"""Exception types shared by the client, service and API layers."""


class SetNotFound(Exception):
    """SET answered 404 for this symbol (or the symbol has no data)."""


class SetUpstreamError(Exception):
    """SET could not be reached, timed out, blocked us, or returned a 5xx."""


class SetParseError(Exception):
    """SET answered, but the payload is not in a shape/value range we trust."""

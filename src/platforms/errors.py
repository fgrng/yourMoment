"""Typed platform errors; retry policies decide by type, never by message."""


class PlatformError(Exception):
    """Base class for all platform errors."""


class PlatformAuthError(PlatformError):
    """The platform rejected the credentials. Do not retry."""


class PlatformUnavailable(PlatformError):
    """Network error, timeout or 5xx. Retry."""


class PlatformRejected(PlatformError):
    """The platform refuses the action (e.g. article deleted). Do not retry."""

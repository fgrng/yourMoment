"""Platform interface: yourMoment talks to every platform only through this package (ADR-0001)."""

from src.platforms.errors import (
    PlatformAuthError,
    PlatformError,
    PlatformRejected,
    PlatformUnavailable,
)
from src.platforms.registry import adapter_for, connect, use_adapter
from src.platforms.types import (
    ArticleContent,
    ArticleRef,
    ArticleSummary,
    PlatformAccount,
    PlatformAdapter,
    PlatformConnection,
    PostedComment,
)

__all__ = [
    "ArticleContent",
    "ArticleRef",
    "ArticleSummary",
    "PlatformAccount",
    "PlatformAdapter",
    "PlatformAuthError",
    "PlatformConnection",
    "PlatformError",
    "PlatformRejected",
    "PlatformUnavailable",
    "PostedComment",
    "adapter_for",
    "connect",
    "use_adapter",
]

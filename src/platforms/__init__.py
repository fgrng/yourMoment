"""Platform interface: yourMoment talks to every platform only through this package (ADR-0001)."""

from src.platforms.errors import (
    InvalidTarget,
    PlatformAuthError,
    PlatformError,
    PlatformRejected,
    PlatformUnavailable,
)
from src.platforms.registry import MYMOMENT, adapter_for, adapter_for_platform, connect, use_adapter
from src.platforms.targets import validate_target
from src.platforms.types import (
    ArticleContent,
    ArticleRef,
    ArticleSummary,
    PlatformAccount,
    PlatformAdapter,
    PlatformConnection,
    PostedComment,
    StudentRef,
    TargetDimension,
    TargetOption,
    TargetValue,
)

__all__ = [
    "ArticleContent",
    "ArticleRef",
    "ArticleSummary",
    "InvalidTarget",
    "MYMOMENT",
    "PlatformAccount",
    "PlatformAdapter",
    "PlatformAuthError",
    "PlatformConnection",
    "PlatformError",
    "PlatformRejected",
    "PlatformUnavailable",
    "PostedComment",
    "StudentRef",
    "TargetDimension",
    "TargetOption",
    "TargetValue",
    "adapter_for",
    "adapter_for_platform",
    "connect",
    "use_adapter",
    "validate_target",
]

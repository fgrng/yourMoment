"""
Comment helpers for yourMoment application.

Validation and HTML paragraph formatting for AI comments, used by the
comment generation stage.
"""

import re
from typing import Any, Dict, Optional

from src.config.settings import get_settings


def ensure_html_paragraphs(text: str) -> str:
    """Normalize comment text to HTML paragraphs. No-op if already contains <p> tags."""
    if not text:
        return text
    stripped = text.strip()
    if "<p>" in stripped.lower():
        return stripped
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", stripped) if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else stripped


def validate_comment(
    comment_content: str,
    min_length: int = None,
    max_length: Optional[int] = None,
    enable_content_validation: bool = True,
) -> Dict[str, Any]:
    """
    Validate a generated comment against quality and requirement criteria.

    Standalone function — no service dependencies, callable from tasks.

    Args:
        comment_content: Generated comment text (must already include AI prefix)
        min_length: Minimum allowed length of content after prefix
        max_length: Maximum allowed length of content after prefix
        enable_content_validation: Whether to run repetition/placeholder checks

    Returns:
        Dictionary with keys: is_valid, has_ai_prefix, errors, content_length
    """
    errors = []

    settings = get_settings()
    if min_length is None:
        min_length = settings.monitoring.COMMENT_MIN_LENGTH
    if max_length is None:
        max_length = settings.monitoring.COMMENT_MAX_LENGTH
    ai_prefix = settings.monitoring.AI_COMMENT_PREFIX
    has_ai_prefix = comment_content.startswith(ai_prefix) or comment_content.startswith(
        f"<p>{ai_prefix}</p>"
    )
    if not has_ai_prefix:
        errors.append("Missing required German AI prefix")

    content_without_prefix = (
        comment_content.replace(f"<p>{ai_prefix}</p>", "")
        .replace(ai_prefix, "")
        .strip()
    )
    content_length = len(content_without_prefix)

    if content_length < min_length:
        errors.append(f"Comment too short ({content_length} < {min_length} chars)")

    if max_length is not None and content_length > max_length:
        errors.append(f"Comment too long ({content_length} > {max_length} chars)")

    if not content_without_prefix:
        errors.append("Comment content is empty after prefix")

    if enable_content_validation:
        words = content_without_prefix.split()
        if len(words) > 5 and len(set(words)) < len(words) * 0.5:
            errors.append("Comment appears to be repetitive")

        placeholder_patterns = [r"\{[^}]+\}"]
        for pattern in placeholder_patterns:
            if re.search(pattern, content_without_prefix):
                errors.append("Comment contains unresolved placeholders")
                break

    return {
        "is_valid": len(errors) == 0,
        "has_ai_prefix": has_ai_prefix,
        "errors": errors,
        "content_length": content_length,
    }

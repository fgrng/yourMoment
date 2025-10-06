"""Shared placeholder definitions for prompt templates."""

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PlaceholderInfo:
    """Information about a template placeholder."""
    name: str
    is_required: bool
    description: str
    example_value: str


SUPPORTED_PLACEHOLDERS: Dict[str, PlaceholderInfo] = {
    "article_title": PlaceholderInfo(
        name="article_title",
        is_required=False,
        description="Title of the myMoment article",
        example_value="Ein Arbeitsnachmittag an der PHSG",
    ),
    "article_content": PlaceholderInfo(
        name="article_content",
        is_required=False,
        description="Full text content of the article",
        example_value=(
            "Wir sitzen zu viert in einem neu renovierten Sitzungszimmer an der PHSG in St. Gallen. "
            "Ich bin zum ersten Mal an diesem Standort der PHSG.\nNächste Woche steht Brainstorming zu "
            "Schreibaufgaben an, mal schauen, was da Gescheites dabei rauskommt."
        ),
    ),
    "article_author": PlaceholderInfo(
        name="article_author",
        is_required=False,
        description="Author username of the article",
        example_value="RoyalWildcat",
    ),
    "article_raw_html": PlaceholderInfo(
        name="article_raw_html",
        is_required=False,
        description="Raw HTML content of the article (for advanced processing)",
        example_value="<div class=\"article\"><p>Wir sitzen zu viert in einem neu renovierten Sitzungszimmer an der PHSG in St. Gallen.</p></div>",
    ),
}


__all__ = [
    "PlaceholderInfo",
    "SUPPORTED_PLACEHOLDERS",
]

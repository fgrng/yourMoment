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
        description="Titel des Artikels von myMoment",
        example_value="Ein Arbeitsnachmittag an der PHSG",
    ),
    "article_content": PlaceholderInfo(
        name="article_content",
        is_required=False,
        description="Vollständiger Inhalt des Artikels von myMoment",
        example_value=(
            "Wir sitzen zu in einem neu renovierten Sitzungszimmer an der PHSG in St.Gallen. "
            "Ich bin zum ersten Mal an diesem Standort. Nächste Woche steht Brainstorming zu "
            "neuen Schreibaufgaben an. Mal schauen, was da Gescheites dabei rauskommt."
        ),
    ),
    "article_author": PlaceholderInfo(
        name="article_author",
        is_required=False,
        description="Name de Autor:in (Pseudonym) von myMoment",
        example_value="GracefulUnicorn",
    ),
    "article_raw_html": PlaceholderInfo(
        name="article_raw_html",
        is_required=False,
        description="Vollstänige Darstellung des Artikels im HTML-Format (für weitergehende Verarbeitung)",
        example_value="<div class=\"article\"><p>Wir sitzen zu viert in einem neu renovierten Sitzungszimmer an der PHSG in St.Gallen.</p></div>",
    ),
}


__all__ = [
    "PlaceholderInfo",
    "SUPPORTED_PLACEHOLDERS",
]

## Diese Datei markiert das scraper-Verzeichnis als Python-Paket
"""
WebScraper-Modul für myMoment-Webscraper.
"""

from .main import WebScraper
from .monitor import PostMonitor

__all__ = ['WebScraper', 'PostMonitor']

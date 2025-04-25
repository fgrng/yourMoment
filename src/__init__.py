# Diese Datei markiert das src-Verzeichnis als Python-Paket
# Sie kann leer bleiben oder Imports für einfacheren Zugriff enthalten

from .scraper import WebScraper
from .config import load_config, save_config

__all__ = ['WebScraper', 'load_config', 'save_config']

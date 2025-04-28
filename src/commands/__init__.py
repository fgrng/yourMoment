## Diese Datei markiert das commands-Verzeichnis als Python-Paket
from .auth import add_auth_subparsers
from .posts import add_post_subparsers
"""
Commandline-Modul für myMoment-Webscraper.
"""

from .comments import add_comment_subparsers
from .monitor import add_monitor_subparsers

__all__ = ['add_auth_subparsers', 'add_post_subparsers', 'add_comment_subparsers', 'add_monitor_subparsers']

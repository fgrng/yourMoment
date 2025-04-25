## Diese Datei markiert das commands-Verzeichnis als Python-Paket
from .auth import add_auth_subparsers
from .posts import add_post_subparsers
from .comments import add_comment_subparsers

__all__ = ['add_auth_subparsers', 'add_post_subparsers', 'add_comment_subparsers']

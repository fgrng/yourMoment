"""Chooses the adapter for a platform account and opens connections."""

from __future__ import annotations

from typing import AsyncContextManager, Optional

from src.platforms.types import PlatformAccount, PlatformAdapter, PlatformConnection

_override: Optional[PlatformAdapter] = None


def use_adapter(adapter: Optional[PlatformAdapter]) -> None:
    """Replace the adapter for every account (tests); None restores the default."""
    global _override
    _override = adapter


def adapter_for(account: PlatformAccount) -> PlatformAdapter:
    """Return the adapter for the account's platform.

    Until the schema knows platform types, every account is a myMoment account.
    """
    if _override is not None:
        return _override
    return _default_mymoment_adapter()


def connect(account: PlatformAccount, *, fresh_login: bool = False) -> AsyncContextManager[PlatformConnection]:
    """Open a connection to the account's platform: `async with connect(account) as conn`.

    `fresh_login` checks the credentials themselves instead of reusing a stored session.
    """
    return adapter_for(account).connect(account, fresh_login=fresh_login)


def _default_mymoment_adapter() -> PlatformAdapter:
    from src.config.settings import get_settings
    from src.platforms.mymoment.adapter import MyMomentAdapter
    from src.services.mymoment_session_service import MyMomentSessionCookieStore

    scraper_settings = get_settings().scraper
    return MyMomentAdapter(
        cookie_store=MyMomentSessionCookieStore(),
        rate_limit_delay=1.0 / scraper_settings.SCRAPING_RATE_LIMIT,
        timeout=scraper_settings.MYMOMENT_TIMEOUT,
    )

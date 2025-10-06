"""
Rate limiting middleware for yourMoment application.

This module provides rate limiting functionality to protect against abuse
and ensure fair usage of web scraping and API endpoints.
"""

import time
import asyncio
import logging
from typing import Dict, Any, Optional, Callable, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass
class RateLimitRule:
    """Configuration for a rate limiting rule."""
    requests: int  # Number of requests allowed
    window: int    # Time window in seconds
    burst: int = None  # Optional burst limit (defaults to requests)

    def __post_init__(self):
        if self.burst is None:
            self.burst = self.requests


@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting implementation."""
    tokens: float
    last_refill: float
    requests: deque = field(default_factory=deque)

    def __post_init__(self):
        if not hasattr(self, 'last_refill') or self.last_refill is None:
            self.last_refill = time.time()


class RateLimiter:
    """
    Token bucket-based rate limiter with sliding window support.

    Supports both per-IP and per-user rate limiting with configurable rules.
    """

    def __init__(self):
        self.buckets: Dict[str, RateLimitBucket] = {}
        self.rules: Dict[str, RateLimitRule] = {}
        self.cleanup_interval = 300  # Clean up old buckets every 5 minutes
        self.last_cleanup = time.time()

        # Default rate limiting rules
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Setup default rate limiting rules."""
        self.rules = {
            # API endpoints
            "api_general": RateLimitRule(requests=100, window=60),  # 100 req/min
            "api_auth": RateLimitRule(requests=5, window=60),       # 5 auth req/min
            "api_scraping": RateLimitRule(requests=10, window=60),  # 10 scraping req/min

            # Web scraping (external requests)
            "scraping_mymoment": RateLimitRule(requests=30, window=60, burst=5),  # 30 req/min, burst 5
            "scraping_general": RateLimitRule(requests=60, window=60, burst=10),  # 60 req/min, burst 10

            # User-specific limits
            "user_general": RateLimitRule(requests=1000, window=3600),  # 1000 req/hour per user
            "user_premium": RateLimitRule(requests=5000, window=3600),  # 5000 req/hour for premium
        }

    def add_rule(self, name: str, rule: RateLimitRule):
        """Add or update a rate limiting rule."""
        self.rules[name] = rule
        logger.info(f"Rate limit rule '{name}' configured: {rule.requests}/{rule.window}s")

    def get_bucket_key(self, identifier: str, rule_name: str) -> str:
        """Generate bucket key for rate limiting."""
        return f"{rule_name}:{identifier}"

    def _cleanup_old_buckets(self):
        """Clean up old, unused buckets."""
        current_time = time.time()

        if current_time - self.last_cleanup < self.cleanup_interval:
            return

        # Find buckets that haven't been used recently
        cutoff_time = current_time - 3600  # 1 hour
        old_buckets = [
            key for key, bucket in self.buckets.items()
            if bucket.last_refill < cutoff_time
        ]

        for key in old_buckets:
            del self.buckets[key]

        if old_buckets:
            logger.info(f"Cleaned up {len(old_buckets)} old rate limit buckets")

        self.last_cleanup = current_time

    def _refill_bucket(self, bucket: RateLimitBucket, rule: RateLimitRule) -> RateLimitBucket:
        """Refill tokens in the bucket based on time elapsed."""
        current_time = time.time()
        time_elapsed = current_time - bucket.last_refill

        # Calculate tokens to add based on elapsed time
        tokens_to_add = (time_elapsed / rule.window) * rule.requests
        bucket.tokens = min(rule.burst, bucket.tokens + tokens_to_add)
        bucket.last_refill = current_time

        return bucket

    def _sliding_window_check(self, bucket: RateLimitBucket, rule: RateLimitRule) -> bool:
        """Check sliding window for request rate."""
        current_time = time.time()
        window_start = current_time - rule.window

        # Remove old requests from the window
        while bucket.requests and bucket.requests[0] < window_start:
            bucket.requests.popleft()

        # Check if we're within the rate limit
        return len(bucket.requests) < rule.requests

    def is_allowed(self, identifier: str, rule_name: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if a request is allowed based on rate limiting rules.

        Args:
            identifier: Unique identifier (IP, user ID, etc.)
            rule_name: Name of the rate limiting rule to apply

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        self._cleanup_old_buckets()

        rule = self.rules.get(rule_name)
        if not rule:
            logger.warning(f"Rate limit rule '{rule_name}' not found, allowing request")
            return True, {}

        bucket_key = self.get_bucket_key(identifier, rule_name)
        current_time = time.time()

        # Get or create bucket
        if bucket_key not in self.buckets:
            self.buckets[bucket_key] = RateLimitBucket(
                tokens=rule.burst,
                last_refill=current_time
            )

        bucket = self.buckets[bucket_key]

        # Refill tokens
        bucket = self._refill_bucket(bucket, rule)

        # Check sliding window
        if not self._sliding_window_check(bucket, rule):
            # Rate limit exceeded
            retry_after = rule.window - (current_time - min(bucket.requests)) if bucket.requests else rule.window

            return False, {
                "rule": rule_name,
                "limit": rule.requests,
                "window": rule.window,
                "retry_after": int(retry_after),
                "requests_remaining": 0
            }

        # Check token bucket
        if bucket.tokens < 1:
            # No tokens available
            time_until_token = rule.window / rule.requests

            return False, {
                "rule": rule_name,
                "limit": rule.requests,
                "window": rule.window,
                "retry_after": int(time_until_token),
                "requests_remaining": 0
            }

        # Allow request and consume token
        bucket.tokens -= 1
        bucket.requests.append(current_time)

        # Calculate remaining requests
        remaining_window = max(0, rule.requests - len(bucket.requests))
        remaining_tokens = int(bucket.tokens)
        requests_remaining = min(remaining_window, remaining_tokens)

        return True, {
            "rule": rule_name,
            "limit": rule.requests,
            "window": rule.window,
            "requests_remaining": requests_remaining
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "active_buckets": len(self.buckets),
            "rules_configured": len(self.rules),
            "last_cleanup": datetime.fromtimestamp(self.last_cleanup).isoformat(),
            "rules": {name: {"requests": rule.requests, "window": rule.window, "burst": rule.burst}
                     for name, rule in self.rules.items()}
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting HTTP requests.

    Provides automatic rate limiting based on request patterns and user types.
    """

    def __init__(self, app, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(app)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.exempt_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

    def get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        # Try to get user ID from authentication
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return f"user:{user.id}"

        # Fall back to IP address
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return f"ip:{forwarded_for.split(',')[0].strip()}"

        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    def get_rate_limit_rule(self, request: Request) -> str:
        """Determine which rate limit rule to apply."""
        path = request.url.path

        # Authentication endpoints
        if path.startswith("/auth/"):
            return "api_auth"

        # API endpoints with scraping functionality
        if any(endpoint in path for endpoint in ["/monitoring-processes", "/articles", "/comments"]):
            return "api_scraping"

        # General API endpoints
        if path.startswith("/api/") or path.startswith("/users/"):
            return "api_general"

        # Default rule
        return "api_general"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with rate limiting."""
        # Skip rate limiting for exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        # Get client identifier and rate limit rule
        identifier = self.get_client_identifier(request)
        rule_name = self.get_rate_limit_rule(request)

        # Check rate limit
        is_allowed, rate_info = self.rate_limiter.is_allowed(identifier, rule_name)

        if not is_allowed:
            logger.warning(
                f"Rate limit exceeded for {identifier} on {request.url.path} "
                f"(rule: {rule_name}, retry after: {rate_info.get('retry_after')}s)"
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Try again in {rate_info.get('retry_after')} seconds.",
                    "rule": rate_info.get("rule"),
                    "limit": rate_info.get("limit"),
                    "window": rate_info.get("window"),
                    "retry_after": rate_info.get("retry_after")
                },
                headers={
                    "Retry-After": str(rate_info.get("retry_after", 60)),
                    "X-RateLimit-Limit": str(rate_info.get("limit", 0)),
                    "X-RateLimit-Remaining": str(rate_info.get("requests_remaining", 0)),
                    "X-RateLimit-Reset": str(int(time.time()) + rate_info.get("retry_after", 60))
                }
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers to response
        if rate_info:
            response.headers["X-RateLimit-Limit"] = str(rate_info.get("limit", 0))
            response.headers["X-RateLimit-Remaining"] = str(rate_info.get("requests_remaining", 0))
            response.headers["X-RateLimit-Window"] = str(rate_info.get("window", 0))

        return response


class ScrapingRateLimiter:
    """
    Specialized rate limiter for web scraping operations.

    Provides rate limiting specifically for external web scraping
    to be respectful of target websites.
    """

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.domain_delays: Dict[str, float] = {}
        self.last_request_times: Dict[str, float] = {}

        # Setup scraping-specific rules
        self._setup_scraping_rules()

    def _setup_scraping_rules(self):
        """Setup rate limiting rules for web scraping."""
        # myMoment specific limits (be respectful)
        self.rate_limiter.add_rule(
            "mymoment_scraping",
            RateLimitRule(requests=20, window=60, burst=3)  # 20 req/min, burst 3
        )

        # General web scraping limits
        self.rate_limiter.add_rule(
            "general_scraping",
            RateLimitRule(requests=30, window=60, burst=5)  # 30 req/min, burst 5
        )

        # Per-domain delays (minimum time between requests)
        self.domain_delays = {
            "mymoment.ch": 2.0,      # 2 seconds between requests
            "new.mymoment.ch": 2.0,  # 2 seconds between requests
            "default": 1.0           # 1 second for other domains
        }

    def get_domain_from_url(self, url: str) -> str:
        """Extract domain from URL for rate limiting."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return "unknown"

    async def wait_if_needed(self, url: str) -> float:
        """
        Wait if needed to respect rate limits before making a request.

        Args:
            url: URL being requested

        Returns:
            Time waited in seconds
        """
        domain = self.get_domain_from_url(url)
        current_time = time.time()

        # Check domain-specific delay
        domain_delay = self.domain_delays.get(domain, self.domain_delays["default"])
        last_request = self.last_request_times.get(domain, 0)

        time_since_last = current_time - last_request
        if time_since_last < domain_delay:
            wait_time = domain_delay - time_since_last
            logger.info(f"Rate limiting: waiting {wait_time:.2f}s for {domain}")
            await asyncio.sleep(wait_time)
            return wait_time

        return 0.0

    def is_scraping_allowed(self, url: str, session_id: str = "default") -> Tuple[bool, Dict[str, Any]]:
        """
        Check if a scraping request is allowed.

        Args:
            url: URL being scraped
            session_id: Identifier for the scraping session

        Returns:
            Tuple of (is_allowed, rate_info)
        """
        domain = self.get_domain_from_url(url)

        # Determine rule based on domain
        if "mymoment" in domain:
            rule_name = "mymoment_scraping"
        else:
            rule_name = "general_scraping"

        identifier = f"scraping:{session_id}:{domain}"
        return self.rate_limiter.is_allowed(identifier, rule_name)

    def record_request(self, url: str):
        """Record that a request was made to update rate limiting."""
        domain = self.get_domain_from_url(url)
        self.last_request_times[domain] = time.time()

    def get_scraping_stats(self) -> Dict[str, Any]:
        """Get scraping rate limiter statistics."""
        base_stats = self.rate_limiter.get_stats()

        return {
            **base_stats,
            "domain_delays": self.domain_delays,
            "last_requests": {
                domain: datetime.fromtimestamp(timestamp).isoformat()
                for domain, timestamp in self.last_request_times.items()
            }
        }


# Global instances
_global_rate_limiter: Optional[RateLimiter] = None
_global_scraping_limiter: Optional[ScrapingRateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    return _global_rate_limiter


def get_scraping_rate_limiter() -> ScrapingRateLimiter:
    """Get the global scraping rate limiter instance."""
    global _global_scraping_limiter
    if _global_scraping_limiter is None:
        _global_scraping_limiter = ScrapingRateLimiter()
    return _global_scraping_limiter


# Convenience functions for use in scraping services
async def wait_for_scraping_rate_limit(url: str) -> float:
    """
    Convenience function to wait for scraping rate limits.

    Args:
        url: URL being scraped

    Returns:
        Time waited in seconds
    """
    limiter = get_scraping_rate_limiter()
    return await limiter.wait_if_needed(url)


def check_scraping_rate_limit(url: str, session_id: str = "default") -> bool:
    """
    Convenience function to check scraping rate limits.

    Args:
        url: URL being scraped
        session_id: Scraping session identifier

    Returns:
        True if request is allowed
    """
    limiter = get_scraping_rate_limiter()
    is_allowed, _ = limiter.is_scraping_allowed(url, session_id)
    if is_allowed:
        limiter.record_request(url)
    return is_allowed
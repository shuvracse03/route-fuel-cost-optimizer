"""
Two-layer cache-aside service.

Layer 1: Redis  (fast, volatile, TTL-based)
Layer 2: PostgreSQL route_cache table (durable, hit-count analytics)

On MISS at both layers → full computation → write-through to both.
On HIT at DB but MISS at Redis → re-populate Redis from DB.
"""
import json
import logging
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.route.models import RouteCache
from apps.core.request_context import set_data_source, DataSource

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "route:"


def get_cached_route(cache_key: str) -> Optional[dict]:
    """
    Return a previously computed route response dict, or None on full MISS.
    Updates the DB hit counter and re-populates Redis from DB on a
    Redis-only miss.
    """
    # Layer 1: Redis
    redis_key = _redis_key(cache_key)
    cached = cache.get(redis_key)
    if cached is not None:
        logger.debug("Redis HIT for key %s", cache_key[:12])
        set_data_source(DataSource.REDIS)
        cached["meta"]["cached"] = True
        return cached

    # Layer 2: PostgreSQL
    try:
        record = RouteCache.objects.get(cache_key=cache_key)
    except RouteCache.DoesNotExist:
        return None

    logger.debug("DB HIT for key %s (Redis miss)", cache_key[:12])
    set_data_source(DataSource.DB_CACHE)
    response = record.response_json
    response["meta"]["cached"] = True

    # Re-populate Redis
    cache.set(redis_key, response, timeout=settings.ROUTE_CACHE_TTL)

    # Increment hit counter (non-blocking; ignore failures)
    RouteCache.objects.filter(pk=record.pk).update(
        hit_count=record.hit_count + 1,
        updated_at=timezone.now(),
    )

    return response


def save_route_to_cache(
    cache_key: str,
    start_location: str,
    finish_location: str,
    response: dict,
) -> None:
    """
    Persist a freshly computed route response to both Redis and PostgreSQL.
    The *response* dict is stored as-is; callers should set meta.cached=False.
    """
    redis_key = _redis_key(cache_key)
    cache.set(redis_key, response, timeout=settings.ROUTE_CACHE_TTL)

    RouteCache.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            "start_location": start_location,
            "finish_location": finish_location,
            "response_json": response,
            "hit_count": 0,
        },
    )
    logger.debug("Saved route to cache for key %s", cache_key[:12])


def _redis_key(cache_key: str) -> str:
    return f"{REDIS_KEY_PREFIX}{cache_key}"

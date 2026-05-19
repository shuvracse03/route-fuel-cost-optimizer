"""
pytest configuration and shared fixtures.

Overrides cache backend to use LocMemCache so tests don't need Redis.
Marks all tests requiring the Django ORM as @pytest.mark.django_db.
"""
import django
import pytest
from django.test import override_settings


# Use in-memory cache for all tests — no Redis required
TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}


@pytest.fixture(autouse=True)
def use_in_memory_cache(settings):
    """Override cache to LocMemCache for every test automatically."""
    settings.CACHES = TEST_CACHES

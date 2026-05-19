"""
Test settings — uses a dedicated PostgreSQL/PostGIS test database.

The test DB (fuel_route_test) must be pre-created by a superuser:

    CREATE DATABASE fuel_route_test;
    \\c fuel_route_test
    CREATE EXTENSION postgis;
    GRANT ALL PRIVILEGES ON DATABASE fuel_route_test TO fuel_admin;

pytest-django will NOT create/drop the DB itself (TEST_CREATE = False).
Run migrations once manually:

    python manage.py migrate --settings=fuel_route.settings.test
"""
from .base import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": "fuel_route_test",
        "USER": "fuel_admin",
        "PASSWORD": "pass123",
        "HOST": "localhost",
        "PORT": "5432",
        "TEST": {
            "NAME": "fuel_route_test",  # reuse the pre-created DB; don't auto-create
        },
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable throttling so tests aren't rate-limited
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}  # noqa: F405

# Disable Redis — use local-mem cache for tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

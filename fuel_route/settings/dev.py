"""Development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Extend base LOGGING — add console handlers for dev without overwriting
# the api_file handler and api_requests logger defined in base.py
LOGGING["handlers"]["console"] = {
    "class": "logging.StreamHandler",
    "formatter": "verbose",
}

LOGGING["loggers"]["apps"] = {
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
}

LOGGING["loggers"]["django.request"] = {
    "handlers": ["console"],
    "level": "INFO",
    "propagate": False,
}

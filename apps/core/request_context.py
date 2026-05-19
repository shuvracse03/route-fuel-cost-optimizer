"""
Thread-local request context for passing metadata through the request lifecycle.

Allows any layer (view, service) to attach metadata to the current request
so the logging middleware can include it in the log entry.
"""
import threading
from enum import Enum

_local = threading.local()


class DataSource(str, Enum):
    """Where the response data came from."""
    REDIS = "redis_cache"
    DB_CACHE = "db_cache"
    ORS_API = "ors_api"
    UNKNOWN = "unknown"


def set_data_source(source: DataSource) -> None:
    """Record the data source for this request."""
    _local.data_source = source


def get_data_source() -> DataSource:
    """Retrieve the data source for this request."""
    return getattr(_local, "data_source", DataSource.UNKNOWN)


def clear_request_context() -> None:
    """Reset thread-local state at the start of each request."""
    _local.data_source = DataSource.UNKNOWN

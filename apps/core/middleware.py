"""
Request logging middleware.

Logs every API call with:
  - start time
  - end time
  - duration (ms)
  - API name (method + path)
  - data source (Redis cache, DB cache, ORS API, unknown)
  - status code
  - response size

Logs are written to logs/api_requests.log with daily rotation.
"""
import logging
import time
from django.utils.decorators import decorator_from_middleware
from django.utils.deprecation import MiddlewareMixin

from apps.core.request_context import clear_request_context, get_data_source

logger = logging.getLogger("api_requests")


class APIRequestLoggingMiddleware(MiddlewareMixin):
    """Logs all API requests with timing and data source information."""

    def process_request(self, request):
        """Clear context and record start time."""
        clear_request_context()
        request._start_time = time.time()
        return None

    def process_response(self, request, response):
        """Log the request with timing and metadata."""
        if not hasattr(request, "_start_time"):
            return response

        start_time = request._start_time
        end_time = time.time()
        duration_ms = (end_time - start_time) * 1000

        data_source = get_data_source()
        path = request.path
        method = request.method
        status_code = response.status_code
        response_size = len(response.content) if hasattr(response, "content") else 0

        log_message = (
            f"API_REQUEST | "
            f"method={method} | "
            f"path={path} | "
            f"status={status_code} | "
            f"duration_ms={duration_ms:.2f} | "
            f"data_source={data_source} | "
            f"response_size_bytes={response_size}"
        )

        if status_code >= 400:
            logger.warning(log_message)
        else:
            logger.info(log_message)

        return response

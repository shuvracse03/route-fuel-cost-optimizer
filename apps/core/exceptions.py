"""
Custom DRF exception handler — always returns JSON, never HTML.
"""
import logging

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        return response

    # Unhandled exception — log it and return a clean 500
    logger.exception("Unhandled exception in %s", context.get("view"))
    return Response(
        {"error": "An unexpected server error occurred. Please try again later."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

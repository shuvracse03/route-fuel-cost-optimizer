#!/usr/bin/env python3
"""
Direct test of logging middleware without running full Django server.
"""
import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fuel_route.settings.dev")
sys.path.insert(0, str(Path(__file__).parent))
django.setup()

import logging
from apps.core.middleware import APIRequestLoggingMiddleware
from apps.core.request_context import set_data_source, DataSource

# Get the logger
logger = logging.getLogger("api_requests")

print("=" * 80)
print("Testing API Logging")
print("=" * 80)

# Test 1: Direct logging
print("\n✓ Test 1: Direct logging to file...")
logger.info("API_REQUEST | method=POST | path=/api/v1/route/ | status=200 | duration_ms=123.45 | data_source=redis_cache | response_size_bytes=4521")

# Test 2: Check log file exists
log_file = Path(__file__).parent / "logs" / "api_requests.log"
if log_file.exists():
    print(f"✓ Log file created: {log_file}")
    with open(log_file, "r") as f:
        lines = f.readlines()
    print(f"✓ Log entries: {len(lines)}")
    print("\nLatest entry:")
    if lines:
        print(f"  {lines[-1].strip()}")
else:
    print(f"✗ Log file NOT created at {log_file}")

print("\n" + "=" * 80)

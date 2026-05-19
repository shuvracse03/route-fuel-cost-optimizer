#!/usr/bin/env python
"""
Quick test to verify API logging works correctly.

Run from project root:
    python manage.py shell < test_logging.py
"""
import json
import os
from django.test import Client
from django.conf import settings

print("=" * 80)
print("Testing API Logging")
print("=" * 80)

# Ensure logs directory exists
log_dir = os.path.join(settings.BASE_DIR, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "api_requests.log")

print(f"\n✓ Logs directory: {log_dir}")
print(f"✓ Log file: {log_file}")

# Make a test API call
client = Client()
print("\n📡 Making test API call to POST /api/v1/route/...")

test_payload = {
    "start": "Dallas, TX",
    "finish": "Los Angeles, CA",
}

response = client.post(
    "/api/v1/route/",
    data=json.dumps(test_payload),
    content_type="application/json",
)

print(f"✓ Response status: {response.status_code}")

# Check if log file was created
if os.path.exists(log_file):
    print(f"\n✓ Log file exists!")
    with open(log_file, "r") as f:
        logs = f.read()
    
    if logs:
        print(f"✓ Log entries written:\n")
        for line in logs.split("\n")[-5:]:  # Show last 5 lines
            if line.strip():
                print(f"  {line}")
    else:
        print("⚠️  Log file is empty")
else:
    print(f"⚠️  Log file not created at {log_file}")

print("\n" + "=" * 80)
print("Log format: [LEVEL] timestamp | logger | message")
print("Data sources: redis_cache | db_cache | ors_api | unknown")
print("=" * 80)

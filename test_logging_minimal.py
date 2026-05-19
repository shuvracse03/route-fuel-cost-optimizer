#!/usr/bin/env python3
"""
Minimal test: Verify logging config works by directly instantiating handlers.
"""
import logging
import logging.handlers
from pathlib import Path

# Setup logging exactly like Django would
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

log_file = str(log_dir / "api_requests.log")

print("=" * 80)
print("Direct Handler Test")
print("=" * 80)
print(f"\nLog file path: {log_file}")
print(f"Log dir exists: {log_dir.exists()}")
print(f"Log dir writable: {log_dir.is_dir()}")

# Create logger and handler manually
logger = logging.getLogger("api_requests")
logger.setLevel(logging.INFO)

# Create rotating file handler
handler = logging.handlers.RotatingFileHandler(
    log_file,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)

# Create formatter
formatter = logging.Formatter(
    "[{levelname}] {asctime} | {name} | {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)

handler.setFormatter(formatter)
logger.addHandler(handler)

# Test logging
print("\n✓ Logging test message...")
logger.info("TEST | method=POST | path=/api/v1/test/ | status=200 | duration_ms=123.45 | data_source=redis_cache | response_size_bytes=4521")

# Verify file was created
import time
time.sleep(0.5)  # Give file time to write

if Path(log_file).exists():
    print(f"✅ SUCCESS: Log file created at {log_file}")
    with open(log_file, "r") as f:
        content = f.read()
    print(f"\n✓ File size: {len(content)} bytes")
    print(f"✓ Content:\n{content}")
else:
    print(f"❌ FAILED: Log file NOT created at {log_file}")
    print(f"✓ Current directory: {Path.cwd()}")
    print(f"✓ Directory contents: {list(Path.cwd().glob('logs/*'))}")

print("\n" + "=" * 80)

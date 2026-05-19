# Fuel Route Optimizer API

A Django REST API that accepts a start and finish location within the USA, computes an optimal driving route, identifies the most **cost-effective** fuel stops using a **Dynamic Programming (shortest-path) algorithm**, and returns the total estimated fuel cost.

## Stack

| Layer               | Technology                                                     |
| ------------------- | -------------------------------------------------------------- |
| Framework           | Django 6.0.5 + Django REST Framework 3.15                      |
| Routing             | OpenRouteService (free tier) — **1 API call per unique route** |
| Geocoding (offline) | Nominatim (OSM) — batch-run once during data load              |
| Database            | PostgreSQL + PostGIS                                           |
| Cache               | Redis (Layer 1) + PostgreSQL route_cache (Layer 2)             |
| Fuel optimizer      | **Dynamic Programming — DAG shortest path (globally optimal)** |

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, ORS_API_KEY
```

Get a **free** ORS API key at https://openrouteservice.org/dev/#/signup

### 3. Create PostgreSQL database + enable PostGIS

```sql
CREATE DATABASE fuel_route;
\c fuel_route
CREATE EXTENSION postgis;
```

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Load + geocode fuel stations (one-time, ~50 minutes for full geocoding)

```bash
# Full load with geocoding (recommended)
python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv

# Quick test load without geocoding (fuel stops won't work but API boots)
python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv --skip-geocoding

# Resume an interrupted geocoding run
python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv --resume
```

### 6. Start the server

```bash
python manage.py runserver
```

---

## API Usage

### `POST /api/v1/route/`

**Request:**

```json
{
  "start": "Dallas, TX",
  "finish": "Los Angeles, CA"
}
```

**Response:**

```json
{
  "route": {
    "start": "Dallas, TX",
    "finish": "Los Angeles, CA",
    "total_distance_miles": 1432.5,
    "duration_hours": 20.4,
    "geometry": {
      "type": "LineString",
      "coordinates": [[-96.796, 32.776], ["..."], [-118.243, 34.052]]
    }
  },
  "fuel_stops": [
    {
      "opis_id": 44,
      "name": "CIRCLE K #2612042",
      "address": "I-35, EXIT 271",
      "city": "Jarrell",
      "state": "TX",
      "lat": 30.868,
      "lng": -97.591,
      "price_per_gallon": 2.919,
      "miles_from_start": 203.4,
      "miles_from_last_stop": 203.4
    }
  ],
  "fuel_summary": {
    "total_gallons": 143.25,
    "total_cost_usd": 418.36,
    "avg_price_per_gallon": 2.921,
    "num_stops": 3,
    "cost_breakdown": [
      {
        "from_miles": 0,
        "to_miles": 203.4,
        "distance_miles": 203.4,
        "price_per_gallon": 2.919,
        "gallons": 20.34,
        "cost_usd": 59.37
      }
    ]
  },
  "meta": {
    "cached": false,
    "computed_at": "2024-01-15T10:23:45Z",
    "ors_calls_made": 1
  }
}
```

---

## Architecture

```
POST /api/v1/route/
      │
      ▼
[1] Redis Cache (< 10ms on HIT)
      │ MISS
      ▼
[2] PostgreSQL route_cache (< 50ms on HIT)
      │ MISS
      ▼
[3] OpenRouteService API  ← exactly 1 call per unique route
      │  returns GeoJSON LineString + distance
      ▼
[4] GeoJSON → mile markers (haversine accumulation along route)
      ▼
[5] Single PostGIS query → all stations within route bounding box
      ▼
[6] DP shortest-path optimizer → globally optimal stop sequence
      ▼
[7] Fuel cost: distance / 10 MPG × price per segment
      ▼
[8] Save to Redis + PostgreSQL cache
      ▼
JSON Response
```

---

## Fuel Stop Algorithm: Dynamic Programming (DAG Shortest Path)

### Why not Greedy?

A naive greedy approach divides the route into fixed ~450-mile windows and picks the cheapest station **within each window independently**. This produces **locally optimal but globally suboptimal** results.

**Example where greedy fails:**

```
Route: Dallas → Los Angeles (1,400 miles)

Stations along route:
  A: mile 320,  $2.50/gal
  B: mile 400,  $3.50/gal   ← greedy's mandatory "Window 1" pick (mile 350–480)
  C: mile 750,  $2.80/gal

Greedy result:
  Forced to stop at B ($3.50) because it falls in the 350–480 mi window.
  Cost: (400/10) × $3.50 + (350/10) × $2.80 = $140.00 + $98.00 = $238.00

DP result:
  Recognises that stopping at A ($2.50) instead is also reachable in one leg,
  and A → C is within 500 miles (430 mi gap), skipping B entirely.
  Cost: (320/10) × $2.50 + (430/10) × $2.80 = $80.00 + $120.40 = $200.40

Saving: $37.60  (15% cheaper on this segment alone)
```

### How the DP works

The trip is modelled as a **directed acyclic graph (DAG)**:

```
Nodes:
  START  = trip origin   (mile 0,   free initial tank)
  1..n   = candidate fuel stations, sorted by route mileage
  END    = destination   (mile = total_distance)

Edges:
  An edge (i → j) is valid if 0 < dist(i, j) ≤ 500 miles
  Edge cost = (distance_miles / 10 MPG) × price_per_gallon_at_i
  START → any node costs $0 (vehicle departs with a full tank)

DP recurrence (forward pass):
  dp[0]   = 0
  dp[j]   = min over all valid predecessors i:
              dp[i] + (dist(i,j) / 10) × price_at_i

Backtrack prev[] pointers to recover the optimal stop sequence.
```

### Complexity

| Step | Complexity |
|---|---|
| Single DB query (bbox) | O(S) — one query for all stations |
| Station route projection | O(S × M/k) — sampled mile markers |
| DP forward pass | O(S²) worst case, O(S × W) average |
| **Typical runtime** | **< 100ms for cross-country routes** |

Where S = candidate stations (~300–800), M = route points, W = reachable stations within 500 mi (~50–100).

This guarantees the **globally minimum fuel cost** — not an approximation.

### Corridor filtering

Before running DP, stations more than **30 miles off-route** (configurable via `FUEL_CANDIDATE_CORRIDOR_MILES`) are discarded. This keeps the candidate set lean without ever missing a viable stop.

---

## Performance Targets

| Scenario                       | Target |
| ------------------------------ | ------ |
| Cache HIT (Redis)              | < 10ms |
| Cache HIT (PostgreSQL)         | < 50ms |
| Cache MISS (full compute)      | < 3s   |
| ORS API calls per unique route | **1**  |
| DP optimizer (typical)         | < 100ms|

---

## Project Structure

```
apps/
├── route/
│   ├── models.py              # FuelStation, RouteCache
│   ├── views.py               # RouteView (POST handler)
│   ├── serializers.py         # Input validation
│   ├── admin.py
│   ├── urls.py
│   └── services/
│       ├── ors_client.py      # OpenRouteService wrapper (1 directions call)
│       ├── route_builder.py   # GeoJSON → haversine mile markers
│       ├── fuel_selector.py   # DP globally optimal fuel stop selection
│       ├── cost_calculator.py # Per-segment cost at 10 MPG
│       └── cache_service.py   # Redis (L1) + PostgreSQL (L2) cache-aside
└── core/
    ├── utils.py               # haversine(), bbox(), make_cache_key()
    ├── exceptions.py          # Custom DRF error handler
    ├── middleware.py           # API request logging middleware
    ├── request_context.py     # Thread-local data source tracking
    └── management/commands/
        ├── load_fuel_data.py  # CSV → dedup by OPIS ID (min price) → geocode → insert
        └── purge_old_routes.py # Weekly cache cleanup
tests/
├── conftest.py                # Shared fixtures (LocMemCache, no Redis needed)
├── test_utils.py              # Unit tests for haversine, bbox, cache key
├── test_route_builder.py      # Unit tests for GeoJSON → mile markers
├── test_dp_optimizer.py       # Unit tests for DP algorithm correctness
├── test_cost_calculator.py    # Unit tests for fuel cost calculation
├── test_serializers.py        # Unit tests for input validation
└── test_route_view.py         # Integration tests for POST /api/v1/route/
logs/
└── api_requests.log           # Auto-created on first request (file-only, rotating)
```

---

## API Request Logging

Every request to the API is automatically logged to `logs/api_requests.log`. Logs are written to file only — no terminal output.

### Log Format

```
[INFO] 2024-01-15 10:23:45 | api_requests | API_REQUEST | method=POST | path=/api/v1/route/ | status=200 | duration_ms=342.15 | data_source=redis_cache | response_size_bytes=4521
```

### Log Fields

| Field | Example | Description |
|---|---|---|
| `[LEVEL]` | `INFO` / `WARNING` | INFO for 2xx/3xx, WARNING for 4xx/5xx |
| `timestamp` | `2024-01-15 10:23:45` | When the request completed |
| `method` | `POST` | HTTP method |
| `path` | `/api/v1/route/` | API endpoint |
| `status` | `200` | HTTP response code |
| `duration_ms` | `342.15` | Total processing time in milliseconds |
| `data_source` | `redis_cache` | Where the response data came from |
| `response_size_bytes` | `4521` | Payload size in bytes |

### Data Sources

| Value | Meaning | Typical Latency |
|---|---|---|
| `redis_cache` | Cache hit in Redis (Layer 1) | 5–15 ms |
| `db_cache` | Cache hit in PostgreSQL (Layer 2) | 40–80 ms |
| `ors_api` | Full compute via OpenRouteService | 1000–3000 ms |
| `unknown` | Uncached or error response | — |

### How It Works

The logging is implemented as a Django middleware (`apps/core/middleware.py`) that wraps every request:

1. **`process_request`** — records start time, clears thread-local context
2. **Services** — `cache_service.py` sets `redis_cache` or `db_cache`; `views.py` sets `ors_api` after an ORS call
3. **`process_response`** — computes duration, reads data source from thread-local, writes log entry

### Viewing Logs

```bash
# Live tail
tail -f logs/api_requests.log

# Last 20 entries
tail -20 logs/api_requests.log

# Filter by data source
grep "redis_cache" logs/api_requests.log
grep "db_cache" logs/api_requests.log
grep "ors_api" logs/api_requests.log

# Filter errors (status >= 400)
grep "WARNING" logs/api_requests.log

# Count requests by data source
grep -o "data_source=[a-z_]*" logs/api_requests.log | sort | uniq -c

# Average response time (ms)
awk -F'duration_ms=' '{print $2}' logs/api_requests.log | awk '{print $1}' \
  | awk '{sum+=$1; count++} END {print "Avg: " sum/count " ms"}'
```

### Log Rotation

Log files rotate automatically at **10 MB** with up to **5 backups** retained:
`api_requests.log` → `api_requests.log.1` → `api_requests.log.2` → ... → `api_requests.log.5`

---

## Testing

The project includes a full pytest test suite covering unit tests for the core algorithms and integration tests for the API endpoint.

### Setup

```bash
pip install pytest pytest-django pytest-mock
```

No database, Redis, or ORS API key is needed to run the tests — all external dependencies are mocked.

### Run Tests

```bash
# Run all tests
pytest

# Run only fast unit tests (no DB, no mocks needed)
pytest tests/test_utils.py tests/test_route_builder.py tests/test_dp_optimizer.py tests/test_cost_calculator.py

# Run only integration tests
pytest tests/test_route_view.py tests/test_serializers.py

# Run with verbose output
pytest -v

# Run with coverage report
pip install pytest-cov
pytest --cov=apps --cov-report=term-missing
```

### Test Coverage

| File | Type | What's Tested |
|---|---|---|
| `tests/test_utils.py` | Unit | `haversine_miles`, `compute_bbox`, `make_cache_key`, `normalise_location`, `min_distance_to_corridor` |
| `tests/test_route_builder.py` | Unit | GeoJSON → mile markers, cumulative mileage, coordinate (lng/lat) ordering |
| `tests/test_dp_optimizer.py` | Unit | `_run_dp` correctness, **DP beats greedy** proof, unreachable routes, 10-station scenarios |
| `tests/test_cost_calculator.py` | Unit | Per-segment costs, totals, **DP cheaper than greedy** validation |
| `tests/test_serializers.py` | Unit | Input validation: missing fields, same-location rejection, whitespace trimming |
| `tests/test_route_view.py` | Integration | Cache HIT/MISS flows, ORS error propagation, response shape, 400 errors |

### Key Algorithmic Tests

The `test_dp_optimizer.py` file directly proves DP global optimality vs greedy using the README example:

```
Route: 0 → 1000 miles
  Station A: mile 320, $2.50  ← DP picks this
  Station B: mile 400, $3.50  ← Greedy is forced here (window-based)
  Station C: mile 750, $2.80

DP cost:    (320/10 × $2.50) + (430/10 × $2.80) = $80.00 + $120.40 = $200.40  ✓
Greedy cost:(400/10 × $3.50) + (350/10 × $2.80) = $140.00 + $98.00 = $238.00  ✗

DP saves: $37.60 (15% cheaper)
```

The test asserts that `_run_dp` chooses station A over B — **guaranteeing global optimality**.


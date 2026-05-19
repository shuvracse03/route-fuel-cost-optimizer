"""
Management command: load_fuel_data

Loads fuel station data from the provided CSV file into the database.

Pipeline:
  1. Parse CSV
  2. Deduplicate by OPIS Truckstop ID — keep the row with the LOWEST Retail Price
  3. Geocode each unique station via Nominatim (OSM) at ≤ 1 req/sec (ToS compliant)
  4. Save to fuel_stations table with PostGIS POINT geometry

Usage:
    python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv
    python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv --batch-size 50
    python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv --skip-geocoding
    python manage.py load_fuel_data --file data/fuel-prices-for-be-assessment.csv --resume
"""
import csv
import logging
import time
from pathlib import Path
from typing import Dict

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from apps.route.models import FuelStation

logger = logging.getLogger(__name__)

GEOCODE_DELAY = 1.1        # seconds between Nominatim requests (ToS: ≤ 1/sec)
GEOCODE_TIMEOUT = 10       # seconds per request
MAX_RETRIES = 3


class Command(BaseCommand):
    help = "Load fuel station data from CSV, deduplicate by OPIS ID (min price), and geocode."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the fuel prices CSV file",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="DB bulk_create batch size (default: 100)",
        )
        parser.add_argument(
            "--skip-geocoding",
            action="store_true",
            help="Load stations without geocoding (useful for quick imports / testing)",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Skip stations that already exist in the DB (by opis_id); "
                 "only geocode stations where geocoded=False",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Delete all existing fuel stations before loading",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["file"])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        if options["overwrite"]:
            count = FuelStation.objects.all().delete()[0]
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing station(s)."))

        self.stdout.write(f"Parsing CSV: {csv_path}")
        unique_stations = self._parse_and_deduplicate(csv_path)
        self.stdout.write(
            self.style.SUCCESS(
                f"Parsed {len(unique_stations)} unique stations (deduplicated by OPIS ID)."
            )
        )

        if options["resume"]:
            existing_ids = set(FuelStation.objects.values_list("opis_id", flat=True))
            before = len(unique_stations)
            unique_stations = {
                k: v for k, v in unique_stations.items() if k not in existing_ids
            }
            self.stdout.write(
                f"Resume mode: skipping {before - len(unique_stations)} already-loaded stations."
            )

        if options["skip_geocoding"]:
            self._bulk_insert_without_geocoding(unique_stations, options["batch_size"])
        else:
            self._geocode_and_insert(unique_stations)

    # -----------------------------------------------------------------------
    # CSV parsing
    # -----------------------------------------------------------------------

    def _parse_and_deduplicate(self, csv_path: Path) -> Dict[int, dict]:
        """
        Read CSV and return a dict keyed by OPIS ID containing the row with
        the lowest Retail Price for that station.
        """
        stations: Dict[int, dict] = {}
        skipped = 0

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    price = float(row["Retail Price"])
                except (ValueError, KeyError):
                    skipped += 1
                    continue

                if opis_id not in stations or price < stations[opis_id]["min_price"]:
                    stations[opis_id] = {
                        "opis_id": opis_id,
                        "name": row.get("Truckstop Name", "").strip(),
                        "address": row.get("Address", "").strip(),
                        "city": row.get("City", "").strip(),
                        "state": row.get("State", "").strip().upper()[:2],
                        "rack_id": self._safe_int(row.get("Rack ID")),
                        "min_price": price,
                    }

        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped {skipped} malformed CSV row(s)."))

        return stations

    # -----------------------------------------------------------------------
    # Insert without geocoding
    # -----------------------------------------------------------------------

    def _bulk_insert_without_geocoding(self, stations: Dict[int, dict], batch_size: int):
        objects = [
            FuelStation(
                opis_id=s["opis_id"],
                name=s["name"],
                address=s["address"],
                city=s["city"],
                state=s["state"],
                rack_id=s["rack_id"],
                min_price=s["min_price"],
                geocoded=False,
            )
            for s in stations.values()
        ]
        FuelStation.objects.bulk_create(objects, batch_size=batch_size, ignore_conflicts=True)
        self.stdout.write(
            self.style.SUCCESS(f"Inserted {len(objects)} stations (geocoding skipped).")
        )

    # -----------------------------------------------------------------------
    # Geocoding + insert
    # -----------------------------------------------------------------------

    def _geocode_and_insert(self, stations: Dict[int, dict]):
        geocoder = Nominatim(
            user_agent="fuel_route_optimizer/1.0",
            timeout=GEOCODE_TIMEOUT,
        )

        total = len(stations)
        loaded = 0
        failed = 0

        self.stdout.write(
            f"Geocoding {total} stations via Nominatim (~{total} seconds minimum)…"
        )

        for idx, station in enumerate(stations.values(), start=1):
            address_str = (
                f"{station['address']}, {station['city']}, {station['state']}, USA"
            )

            lat, lng = self._geocode_with_retry(geocoder, address_str)

            if lat is None:
                # Try a coarser address (city + state only)
                coarse = f"{station['city']}, {station['state']}, USA"
                lat, lng = self._geocode_with_retry(geocoder, coarse)

            if lat is None:
                logger.debug(
                    "Geocoding failed for OPIS %d: %s", station["opis_id"], address_str
                )
                failed += 1
                geocoded = False
                point = None
                geocoded_at = None
            else:
                geocoded = True
                point = Point(lng, lat, srid=4326)
                geocoded_at = timezone.now()
                loaded += 1

            FuelStation.objects.update_or_create(
                opis_id=station["opis_id"],
                defaults={
                    "name": station["name"],
                    "address": station["address"],
                    "city": station["city"],
                    "state": station["state"],
                    "rack_id": station["rack_id"],
                    "min_price": station["min_price"],
                    "lat": lat,
                    "lng": lng,
                    "location": point,
                    "geocoded": geocoded,
                    "geocoded_at": geocoded_at,
                },
            )

            # Progress report every 100 stations
            if idx % 100 == 0 or idx == total:
                self.stdout.write(
                    f"  [{idx}/{total}] Loaded: {loaded}  Failed: {failed}",
                    ending="\r",
                )
                self.stdout.flush()

            time.sleep(GEOCODE_DELAY)

        self.stdout.write("")  # newline after \r progress
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Loaded: {loaded}/{total}  |  Failed geocoding: {failed}/{total}"
            )
        )

    def _geocode_with_retry(
        self, geocoder: Nominatim, address: str
    ) -> tuple[float | None, float | None]:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                location = geocoder.geocode(address)
                if location:
                    return location.latitude, location.longitude
                return None, None
            except GeocoderTimedOut:
                if attempt < MAX_RETRIES:
                    time.sleep(GEOCODE_DELAY * attempt)
            except GeocoderServiceError as exc:
                logger.warning("Nominatim service error: %s", exc)
                return None, None
        return None, None

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

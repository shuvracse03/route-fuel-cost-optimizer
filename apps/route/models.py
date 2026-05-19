from django.contrib.gis.db import models as gis_models
from django.db import models


class FuelStation(models.Model):
    """
    A unique fuel station loaded from the OPIS CSV.

    One row per OPIS Truckstop ID. Where the source CSV has multiple rows for
    the same station (different fuel grades), we keep only the minimum retail
    price so the route optimizer always selects the cheapest option.
    """

    opis_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    min_price = models.DecimalField(max_digits=8, decimal_places=4)

    # Populated during the load_fuel_data management command
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    # PostGIS geography column — enables fast ST_DWithin / ST_Distance queries
    location = gis_models.PointField(
        geography=True,
        srid=4326,
        null=True,
        blank=True,
        spatial_index=True,
    )

    geocoded = models.BooleanField(default=False, db_index=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fuel_stations"
        ordering = ["min_price"]
        indexes = [
            models.Index(fields=["state", "geocoded"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) — ${self.min_price}"


class RouteCache(models.Model):
    """
    Persists computed route responses keyed by SHA-256 of the normalised
    start|finish pair. Acts as Layer 2 of the cache-aside strategy (Redis
    is Layer 1).
    """

    cache_key = models.CharField(max_length=64, unique=True, db_index=True)
    start_location = models.CharField(max_length=255)
    finish_location = models.CharField(max_length=255)
    response_json = models.JSONField()
    hit_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "route_cache"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.start_location} → {self.finish_location} (hits: {self.hit_count})"

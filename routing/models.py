from django.db import models

class Station(models.Model):
    """
    Represents a fuel station / truck stop in the fuel_router system.
    """
    opis_id = models.IntegerField(
        help_text="The station identifier (allows temporary CSV duplicates before deduplication)"
    )
    name = models.CharField(
        max_length=255
    )
    address = models.CharField(
        max_length=255
    )
    city = models.CharField(
        max_length=100
    )
    state = models.CharField(
        max_length=2, 
        help_text="2-letter US state code"
    )
    rack_id = models.IntegerField(
        help_text="The supply terminal identifier"
    )
    price = models.FloatField(
        help_text="Retail fuel price ($/gallon)"
    )
    latitude = models.FloatField(
        null=True, 
        blank=True, 
        help_text="GPS Latitude coordinate"
    )
    longitude = models.FloatField(
        null=True, 
        blank=True, 
        help_text="GPS Longitude coordinate"
    )
    class Meta:
        # Composite index to optimize bounding box spatial queries (< 5ms)
        indexes = [
            models.Index(fields=['latitude', 'longitude'], name='routing_stat_lat_lon_idx')
        ]

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state} (${self.price}/gal)"

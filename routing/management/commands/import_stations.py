import pandas as pd
from django.core.management.base import BaseCommand
from routing.models import Station

class Command(BaseCommand):
    help = "Imports fuel stations from the enriched Excel handling trailing spaces in headers and min-price deduplication"

    def handle(self, *args, **options):
        excel_path = "fuel-prices-enriched-with-coordinates.xlsx"

        self.stdout.write(self.style.SUCCESS(f"Reading {excel_path}..."))
        
        try:
            df = pd.read_excel(excel_path)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"File '{excel_path}' not found at project root."))
            return

        # Clean column names by stripping any accidental trailing/leading spaces (like 'Retail Price ')
        df.columns = [c.strip() for c in df.columns]

        initial_count = len(df)

        # 1. Sort by 'Retail Price' ascending to ensure min(price) comes first
        df = df.sort_values(by='Retail Price', ascending=True)
        
        # 2. Deduplicate based on 'OPIS Truckstop ID' keeping the first row (lowest price)
        df = df.drop_duplicates(subset=['OPIS Truckstop ID'], keep='first')
        deduped_count = len(df)

        self.stdout.write(
            f"Found {initial_count} rows. Removed {initial_count - deduped_count} duplicates. "
            f"Processing {deduped_count} unique stations..."
        )

        stations_to_create = []
        
        # 3. Iterate and map to database records
        for _, row in df.iterrows():
            opis_id_val = int(row['OPIS Truckstop ID']) if pd.notna(row['OPIS Truckstop ID']) else 0
            rack_id_val = int(row['Rack ID']) if pd.notna(row['Rack ID']) else 0
            raw_price = float(row['Retail Price']) if pd.notna(row['Retail Price']) else 0.0

            station = Station(
                opis_id=opis_id_val,
                name=str(row['Truckstop Name']) if pd.notna(row['Truckstop Name']) else "Unknown Station",
                address=str(row['Address']) if pd.notna(row['Address']) else "",
                city=str(row['City']) if pd.notna(row['City']) else "",
                state=str(row['State']) if pd.notna(row['State']) else "",
                rack_id=rack_id_val,
                price=round(raw_price, 3), # Rounding to 3 decimal places standard
                latitude=float(row['Latitude']) if pd.notna(row['Latitude']) else None,
                longitude=float(row['Longitude']) if pd.notna(row['Longitude']) else None,
            )
            stations_to_create.append(station)

        # 4. Clear existing entries to prevent duplicate primary keys on re-run
        Station.objects.all().delete()

        # 5. Fast Bulk Insert into PostgreSQL
        Station.objects.bulk_create(stations_to_create)
        
        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed and imported {len(stations_to_create)} stations into PostgreSQL!")
        )
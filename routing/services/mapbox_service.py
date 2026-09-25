import os 
import requests 
from django.conf import settings 

class MapboxService: 
    def __init__(self): 

        # Retrieve Mapbox token from settings.py or directly from os.environ 
        
        self.access_token = getattr( settings, 'MAPBOX_ACCESS_TOKEN', os.getenv('MAPBOX_ACCESS_TOKEN') )
        if not self.access_token: 
            raise ValueError('Missing Mapbox API key.') 
        self.base_url = 'https://api.mapbox.com' 
    
    def geocode(self, address: str) -> dict: 

        """Calls 1 & 2: Geocoding API (Address -> GPS coordinates)""" 

        url = f'{self.base_url}/geocoding/v5/mapbox.places/{requests.utils.quote(address)}.json' 

        params = { 'access_token': self.access_token, 'limit': 1, 'country': 'US', } 

        response = requests.get(url, params=params) 

        response.raise_for_status() 

        data = response.json() 

        if not data.get('features'): 

            raise ValueError(f'Address not found: {address}') 
        
        center = data['features'][0]['center'] 

        return {'longitude': center[0], 'latitude': center[1]} 
    
    
    def get_directions(self, start_coords: dict, finish_coords: dict) -> dict: 

        """Call 3: Directions API (Retrieves route, distance in miles, and GeoJSON geometry)""" 

        coordinates_str = ( f"{start_coords['longitude']},{start_coords['latitude']};" f"{finish_coords['longitude']},{finish_coords['latitude']}" ) 
        
        url = f'{self.base_url}/directions/v5/mapbox/driving/{coordinates_str}' 
        
        params = { 'access_token': self.access_token, 'geometries': 'geojson', 'overview': 'full', 'steps': 'false', } 
        
        response = requests.get(url, params=params) 
        
        response.raise_for_status() 
        
        data = response.json() 
        
        if not data.get('routes'): 
           
            raise ValueError('No route found between the specified locations.') 
        
        route = data['routes'][0] 
        
        distance_meters = route['distance'] 
        
        distance_miles = distance_meters * 0.000621371 # Convert meters to miles 
        
        return { 
            'distance_miles': round(distance_miles, 2), 
            'duration_seconds': route['duration'], 
            'geometry': route['geometry'], # 'GeoJSON LineString geometry' 
        }
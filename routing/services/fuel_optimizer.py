import math
from typing import Dict, List
import numpy as np
from routing.models import Station

class FuelOptimizerService:
    def __init__(
        self,
        max_range_miles: float = 500.0,
        mpg: float = 10.0,
        max_corridor_miles: float = 15.0,
    ):
        self.max_range_miles = max_range_miles
        self.mpg = mpg
        self.tank_capacity_gallons = max_range_miles / mpg
        self.max_corridor_miles = max_corridor_miles

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 3958.8  # Earth radius in miles
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2 +
            math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def filter_candidate_stations(self, route_coords: List[List[float]]) -> tuple:
        """Fast spatial filtering and route projection using NumPy vectorization and coordinate subsampling."""
        # 1. Subsample route points (keep 1 point approx every ~2 miles)
        subsampled_coords = [route_coords[0]]
        cum_dist = [0.0]
        for i in range(1, len(route_coords)):
            prev_lon, prev_lat = subsampled_coords[-1]
            curr_lon, curr_lat = route_coords[i]
            d = self.haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
            if d >= 2.0 or i == len(route_coords) - 1:
                subsampled_coords.append(route_coords[i])
                cum_dist.append(cum_dist[-1] + d)
        total_route_miles = cum_dist[-1]

        # Convert to NumPy arrays for fast matrix operations
        route_arr = np.array(subsampled_coords)  # Shape (N, 2) -> [lon, lat]
        route_lons = route_arr[:, 0]
        route_lats = route_arr[:, 1]
        cum_dist_arr = np.array(cum_dist)

        # 2. Bounding Box filter from DB
        margin_deg = self.max_corridor_miles / 55.0
        min_lat = np.min(route_lats) - margin_deg
        max_lat = np.max(route_lats) + margin_deg
        min_lon = np.min(route_lons) - margin_deg
        max_lon = np.max(route_lons) + margin_deg

        db_stations = Station.objects.filter(
            latitude__gte=min_lat,
            latitude__lte=max_lat,
            longitude__gte=min_lon,
            longitude__lte=max_lon,
        ).values(
            'opis_id', 'name', 'address', 'city', 'state', 'price', 'latitude', 'longitude',
        )

        if not db_stations:
            return [], total_route_miles

        candidate_stations = []

        # 3. Vectorized Distance Computation with NumPy
        for station in db_stations:
            s_lat, s_lon = float(station['latitude']), float(station['longitude'])
            # Approximate Haversine using Euclidean projection around average lat
            rad_lat = math.radians(s_lat)
            dlat = (route_lats - s_lat) * 69.0  # 1 deg lat approx 69 miles
            dlon = (route_lons - s_lon) * 69.0 * math.cos(rad_lat)
            dists = np.sqrt(dlat**2 + dlon**2)
            min_idx = np.argmin(dists)
            min_dist = dists[min_idx]

            if min_dist <= self.max_corridor_miles:
                candidate_stations.append({
                    'opis_id': station['opis_id'],
                    'name': station['name'],
                    'address': station['address'],
                    'city': station['city'],
                    'state': station['state'],
                    'price': float(station['price']),
                    'latitude': s_lat,
                    'longitude': s_lon,
                    'dist_from_start': round(float(cum_dist_arr[min_idx]), 2),
                    'off_route_miles': round(float(min_dist), 2),
                })

        return candidate_stations, total_route_miles

    def optimize_fuel_stops(
        self, candidate_stations: List[Dict], total_route_miles: float
    ) -> Dict:
        """Executes optimal fuel stop selection along the projected route."""
        candidate_stations = sorted(
            candidate_stations, key=lambda x: x['dist_from_start']
        )
        fuel_stops = []
        curr_pos = 0.0
        total_cost = 0.0
        total_gallons = 0.0

        while curr_pos + self.max_range_miles < total_route_miles:
            max_reachable = curr_pos + self.max_range_miles
            reachable = [
                s for s in candidate_stations 
                if curr_pos < s['dist_from_start'] <= max_reachable
            ]
            if not reachable:
                ahead = [
                    s for s in candidate_stations if s['dist_from_start'] > curr_pos
                ]
                if not ahead:
                    break
                best_stop = ahead[0]
            else:
                far_reachable = [
                    s for s in reachable if s['dist_from_start'] >= curr_pos + 250.0
                ]
                if far_reachable:
                    best_stop = min(
                        far_reachable,
                        key=lambda s: (s['price'], -s['dist_from_start'])
                    )
                else:
                    best_stop = max(reachable, key=lambda s: s['dist_from_start'])

            dist_traveled = best_stop['dist_from_start'] - curr_pos
            gallons_needed = dist_traveled / self.mpg
            stop_cost = gallons_needed * best_stop['price']
            
            stop_info = dict(best_stop)
            stop_info['gallons_purchased'] = round(gallons_needed, 2)
            stop_info['cost'] = round(stop_cost, 2)
            
            fuel_stops.append(stop_info)
            total_cost += stop_cost
            total_gallons += gallons_needed
            curr_pos = best_stop['dist_from_start']

        # Final segment to destination
        final_dist = total_route_miles - curr_pos
        final_gallons = final_dist / self.mpg
        last_price = fuel_stops[-1]['price'] if fuel_stops else 3.50
        final_cost = final_gallons * last_price
        
        total_cost += final_cost
        total_gallons += final_gallons

        return {
            'total_route_miles': round(total_route_miles, 2),
            'total_gallons': round(total_gallons, 2),
            'total_fuel_cost': round(total_cost, 2),
            'fuel_stops': fuel_stops,
        }

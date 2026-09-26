import math
from typing import Dict, List, Tuple, Optional
import numpy as np
from routing.models import Station


class FuelOptimizerService:
    """
    Fuel stop optimizer service for trucks.
    Finds optimal refueling stations along a route to minimize total fuel cost
    while respecting truck range constraints and corridor distance limits.
    """

    def __init__(
        self,
        tank_capacity_gallons: float = 50.0,
        consumption_rate: float = 0.1,
        max_corridor_miles: float = 15.0,
    ):
        """
        Initialize the fuel optimizer service.

        Args:
            tank_capacity_gallons: Tank capacity in gallons (default: 50 gallons)
            consumption_rate: Fuel consumption in gallons/mile (default: 0.1 = 10 gal/100 miles)
            max_corridor_miles: Maximum distance off-route to a station (default: 15 miles)
        """
        self.tank_capacity_gallons = tank_capacity_gallons
        self.consumption_rate = consumption_rate
        # Maximum range = tank capacity / consumption rate (e.g., 50 / 0.1 = 500 miles)
        self.max_range_miles = tank_capacity_gallons / consumption_rate
        self.max_corridor_miles = max_corridor_miles

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate great-circle distance between two points using Haversine formula.

        Args:
            lat1, lon1: Starting point coordinates (latitude, longitude)
            lat2, lon2: Ending point coordinates (latitude, longitude)

        Returns:
            Distance in miles
        """
        r = 3958.8  # Earth radius in miles
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2 +
            math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def filter_candidate_stations(self, route_coords: List[List[float]]) -> Tuple[List[Dict], float]:
        """
        Filter and project fuel stations near the route using spatial indexing and NumPy vectorization.

        Args:
            route_coords: List of [longitude, latitude] pairs along the route

        Returns:
            Tuple of (candidate_stations_list, total_route_miles)
            Each station includes distance from route start and off-route distance
        """
        # 1. Subsample route points to 1 point approximately every 2 miles for efficiency
        subsampled_coords = [route_coords[0]]
        cum_dist = [0.0]

        for i in range(1, len(route_coords)):
            prev_lon, prev_lat = subsampled_coords[-1]
            curr_lon, curr_lat = route_coords[i]
            d = self.haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)
            # Keep point if it's 2+ miles away or it's the last point
            if d >= 2.0 or i == len(route_coords) - 1:
                subsampled_coords.append(route_coords[i])
                cum_dist.append(cum_dist[-1] + d)

        total_route_miles = cum_dist[-1]

        # 2. Convert to NumPy arrays for vectorized distance calculations
        route_arr = np.array(subsampled_coords)  # Shape (N, 2) -> [lon, lat]
        route_lons = route_arr[:, 0]
        route_lats = route_arr[:, 1]
        cum_dist_arr = np.array(cum_dist)

        # 3. Create bounding box with margin for initial database filtering
        margin_deg = self.max_corridor_miles / 55.0  # ~1 degree ≈ 69 miles
        min_lat = np.min(route_lats) - margin_deg
        max_lat = np.max(route_lats) + margin_deg
        min_lon = np.min(route_lons) - margin_deg
        max_lon = np.max(route_lons) + margin_deg

        # Query PostgreSQL with bounding box for initial filtering
        db_stations = Station.objects.filter(
            latitude__gte=min_lat,
            latitude__lte=max_lat,
            longitude__gte=min_lon,
            longitude__lte=max_lon,
        ).values(
            'opis_id', 'name', 'address', 'city', 'state', 'price',
            'latitude', 'longitude',
        )

        if not db_stations:
            return [], total_route_miles

        candidate_stations = []

        # 4. Vectorized distance computation with NumPy for each station
        for station in db_stations:
            s_lat, s_lon = float(station['latitude']), float(station['longitude'])

            # Find closest point on route using Euclidean projection
            rad_lat = math.radians(s_lat)
            # Convert degrees to miles (1 deg lat ≈ 69 miles, lon varies by latitude)
            dlat = (route_lats - s_lat) * 69.0
            dlon = (route_lons - s_lon) * 69.0 * math.cos(rad_lat)
            dists = np.sqrt(dlat**2 + dlon**2)
            min_idx = np.argmin(dists)
            min_dist = dists[min_idx]

            # Only include if within corridor distance from route
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

    def validate_route_feasibility(
        self, candidate_stations: List[Dict], total_route_miles: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if the complete route is feasible given truck range and available stations.

        Args:
            candidate_stations: List of available fuel stations with distance info
            total_route_miles: Total distance of the route

        Returns:
            Tuple of (is_feasible, error_message)
            is_feasible: True if route can be completed, False if impossible
            error_message: Human-readable error description if not feasible, None if feasible
        """
        # Handle no stations case
        if not candidate_stations:
            if total_route_miles <= self.max_range_miles:
                # Short route, no refueling needed
                return True, None
            else:
                return False, (
                    f"❌ ERROR: No stations found and route > {self.max_range_miles} miles "
                    f"({total_route_miles} miles requested)"
                )

        # Sort stations by distance from start
        sorted_stations = sorted(candidate_stations, key=lambda x: x['dist_from_start'])

        # Verify first station is reachable
        if sorted_stations[0]['dist_from_start'] > self.max_range_miles:
            return False, (
                f"❌ ERROR: First station at {sorted_stations[0]['dist_from_start']} miles, "
                f"max range {self.max_range_miles} miles"
            )

        # Verify gaps between consecutive stations don't exceed range
        curr_pos = 0.0
        for station in sorted_stations:
            gap = station['dist_from_start'] - curr_pos
            if gap > self.max_range_miles:
                return False, (
                    f"❌ ERROR: Gap of {gap} miles between {curr_pos} and "
                    f"{station['dist_from_start']} miles (station: {station['name']})"
                )
            curr_pos = station['dist_from_start']

        # Verify final segment to destination is reachable
        final_gap = total_route_miles - curr_pos
        if final_gap > self.max_range_miles:
            return False, (
                f"❌ ERROR: {round(final_gap, 2)} miles to destination, max range {round(self.max_range_miles, 2)} miles"
            )

        return True, None

    def optimize_fuel_stops(
        self, candidate_stations: List[Dict], total_route_miles: float
    ) -> Dict:
        """
        Select optimal fuel stops using greedy algorithm to minimize total cost.

        Uses a greedy approach: at each step, selects the best reachable station
        within tank range, preferring stations further away for better pricing.

        Args:
            candidate_stations: List of available fuel stations
            total_route_miles: Total distance to travel

        Returns:
            Dictionary with optimization result:
            - status: 'success' or 'error'
            - message: Human-readable result description
            - total_route_miles: Route distance
            - total_gallons: Total fuel needed
            - total_fuel_cost: Total cost in dollars
            - avg_price_per_gallon: Average fuel price
            - fuel_stops: List of selected stops with details
        """
        # Pre-validate route feasibility
        is_feasible, error_msg = self.validate_route_feasibility(candidate_stations, total_route_miles)
        if not is_feasible:
            return {
                'status': 'error',
                'message': error_msg,
                'total_route_miles': round(total_route_miles, 2),
                'fuel_stops': [],
                'total_gallons': 0.0,
                'total_fuel_cost': 0.0,
            }

        # Handle short route with no stations needed
        if not candidate_stations:
            final_gallons = total_route_miles * self.consumption_rate
            return {
                'status': 'success',
                'message': f'✅ Short route ({round(total_route_miles, 2)} miles) - no stops required',
                'total_route_miles': round(total_route_miles, 2),
                'fuel_stops': [],
                'total_gallons': round(final_gallons, 2),
                'total_fuel_cost': 0.0,
            }

        # Greedy algorithm: at each step, find best station within reach
        candidate_stations = sorted(candidate_stations, key=lambda x: x['dist_from_start'])
        fuel_stops = []
        curr_pos = 0.0
        total_cost = 0.0
        total_gallons = 0.0

        while curr_pos + self.max_range_miles < total_route_miles:
            max_reachable = curr_pos + self.max_range_miles
            # Find all stations reachable from current position
            reachable = [
                s for s in candidate_stations
                if curr_pos < s['dist_from_start'] <= max_reachable
            ]

            if not reachable:
                # No station in range, pick nearest ahead
                ahead = [s for s in candidate_stations if s['dist_from_start'] > curr_pos]
                if not ahead:
                    break
                best_stop = ahead[0]
            else:
                # Prefer stations far in range (typically better pricing)
                far_reachable = [
                    s for s in reachable if s['dist_from_start'] >= curr_pos + 250.0
                ]
                if far_reachable:
                    # Among far stations, choose cheapest, then furthest
                    best_stop = min(far_reachable, key=lambda s: (s['price'], -s['dist_from_start']))
                else:
                    # Among near stations, choose furthest
                    best_stop = max(reachable, key=lambda s: s['dist_from_start'])

            # Calculate fuel needed for this leg
            dist_traveled = best_stop['dist_from_start'] - curr_pos
            gallons_needed = round(dist_traveled * self.consumption_rate, 2)

            # Verify tank capacity is sufficient
            if gallons_needed > self.tank_capacity_gallons:
                return {
                    'status': 'error',
                    'message': (
                        f"❌ ERROR: {gallons_needed} gallons needed, "
                        f"tank capacity {self.tank_capacity_gallons} gallons"
                    ),
                    'total_route_miles': round(total_route_miles, 2),
                    'fuel_stops': fuel_stops,
                    'total_gallons': round(total_gallons, 2),
                    'total_fuel_cost': round(total_cost, 2),
                }

            # Calculate stop cost and record stop information
            stop_cost = round(gallons_needed * best_stop['price'], 2)

            stop_info = dict(best_stop)
            stop_info['gallons_purchased'] = gallons_needed
            stop_info['cost'] = stop_cost
            stop_info['distance_from_previous'] = round(dist_traveled, 2)

            fuel_stops.append(stop_info)
            total_cost += stop_cost
            total_gallons += gallons_needed
            curr_pos = best_stop['dist_from_start']

        # Final segment to destination
        final_dist = total_route_miles - curr_pos
        final_gallons = round(final_dist * self.consumption_rate, 2)

        # Use last stop price or default if no stops
        if fuel_stops:
            last_price = fuel_stops[-1]['price']
        else:
            last_price = 3.50  # Default fallback price

        final_cost = round(final_gallons * last_price, 2)
        total_cost += final_cost
        total_gallons += final_gallons

        return {
            'status': 'success',
            'message': f'✅ Route optimized: {len(fuel_stops)} stops, total cost ${round(total_cost, 2)}',
            'total_route_miles': round(total_route_miles, 2),
            'total_gallons': round(total_gallons, 2),
            'total_fuel_cost': round(total_cost, 2),
            'avg_price_per_gallon': round(total_cost / total_gallons, 2) if total_gallons > 0 else 0.0,
            'fuel_stops': fuel_stops,
        }

    def plan_route(self, route_coords: List[List[float]]) -> Dict:
        """
        Execute complete pipeline: filter stations -> validate feasibility -> optimize stops.

        Args:
            route_coords: List of [longitude, latitude] pairs along the route

        Returns:
            Complete optimization result with status, message, and detailed breakdown
        """
        # Filter nearby stations from database
        candidate_stations, total_route_miles = self.filter_candidate_stations(route_coords)
        # Optimize fuel stops
        result = self.optimize_fuel_stops(candidate_stations, total_route_miles)

        # Add metadata
        result['candidate_stations_found'] = len(candidate_stations)
        result['max_range_miles'] = self.max_range_miles

        return result
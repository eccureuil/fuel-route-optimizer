# 🚚 Fuel Route Optimizer - Django REST API & Mapbox GL JS

![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.14-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.1.1-092E20?style=for-the-badge&logo=django&logoColor=white)
![Django REST Framework](https://img.shields.io/badge/Django_REST_Framework-DRF-A30000?style=for-the-badge&logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18.4-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Mapbox](https://img.shields.io/badge/Mapbox-GL_JS_%2F_Directions-000000?style=for-the-badge&logo=mapbox&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-Vectorized-013243?style=for-the-badge&logo=numpy&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Cache_1h-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-brightgreen.svg?style=for-the-badge)

An intelligent, high-performance route optimization REST API for heavy trucks traveling across the contiguous United States. The application calculates the most cost-effective fuel stops along a given route while enforcing vehicle range constraints, fuel tank capacities, spatial corridors, and strict performance limits.

---

## 🌟 Key Features & Architectural Highlights

- **Strict Guarantee of 3 API Calls Max per Request**:
  - **Call 1**: Mapbox Geocoding API for origin location (`start_location`).
  - **Call 2**: Mapbox Geocoding API for destination location (`finish_location`).
  - **Call 3**: Mapbox Directions API for precise route geometry (`LineString`).
  - *Benefit*: Total API cost control ($0.75/1k geocodes, $2.00/1k directions), zero external requests during station lookup, and response latency kept strictly under 3.5 seconds.

- **Ultra-Fast Local Spatial Filtering**:
  - Queries gas stations within a **15-mile off-route corridor** using bounding-box spatial queries directly in **PostgreSQL 18.4**.
  - Performs vectorized geographical projections using **NumPy** and the Haversine formula.

- **OPIS ID Price Deduplication**:
  - Uniquely identifies stations using their **`OPIS ID`**.
  - **Lowest Price Guarantee**: When multiple records exist for the same physical station, the system retains exclusively the entry offering the **lowest retail price per gallon**.

- **Greedy Optimization & Vehicle Range Constraints**:
  - Maximum Truck Range: **500 miles** per full tank (50 gallons at 10 MPG / 0.1 gal/mi).
  - Smart Stop Selection: Prefers stations in the **250 to 500-mile** forward window with the lowest price per gallon to minimize total stops.

- **Desert Zone & Edge Case Validation**:
  - Pre-validates route feasibility and flags desert gaps (> 500 miles without reachable stations) with an explicit **`HTTP 400 Bad Request`** error response.

- **High-Performance Caching & Web Map**:
  - Built-in 1-hour Redis / Django memory cache (`/api/route/cached/`) lowering latency to < 15 ms on frequent routes.
  - Interactive WebGL map UI (`/api/map/`) powered by Mapbox GL JS.

---

## 📥 Data Ingestion & Deduplication Pipeline

The fuel station dataset is ingested and processed conceptually from the enriched Excel file (`fuel_price_enriched_with_coordinates.xlsx`) through the following stages:

1. **Pandas Excel Loading**:
   - The enriched `.xlsx` dataset containing station coordinates (`latitude`, `longitude`) is read into memory using **Pandas**.

2. **Lowest Retail Price Deduplication**:
   - The dataset is sorted by retail price in ascending order.
   - Duplicates on the unique business identifier **`OPIS ID`** are removed (`drop_duplicates`), ensuring that only the record with the **lowest price per gallon** is preserved for each physical station.

3. **Atomic PostgreSQL 18.4 Bulk Insert**:
   - Cleaned records are mapped to Django `Station` model instances.
   - Inserted in bulk (`bulk_create`) inside a single atomic SQL transaction, storing over 8,000 station records in under a second.

---

## 📐 Algorithmic Decision Tree & Edge Cases

The core optimization engine (`FuelOptimizerService`) evaluates routes through a deterministic decision tree covering all operational edge cases:

```
                                 [Route Requested]
                                         │
                             [Feasibility Validation]
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
         [Feasible Route]                                [Infeasible Route]
                 │                                               │
    ┌────────────┴────────────┐                        ┌─────────┴─────────┐
    ▼                         ▼                        ▼                   ▼
[Short Route <=500mi]  [Long Route >500mi]    [Gap >500mi / Desert Zone] [Missing Params]
    │                         │                        │                   │
    ▼                         ▼                        ▼                   ▼
(0 Stops Required)     (Greedy Optimization)   (HTTP 400 Bad Request)   (HTTP 400 Error)
(Default Fuel Rate)    (Cheapest Station Stop) (Detailed Error Message) (Missing Parameter)
```

### Pre-Validation Feasibility Rules (`validate_route_feasibility`)

| Scenario / Case | Business Condition | Status | Algorithm Behavior & HTTP Response |
| :--- | :--- | :--- | :--- |
| **Case A1: Short Route without Stations** | `total_miles <= 500` AND 0 stations found | ✅ **Feasible** | Completed on initial tank. 0 stops required (`HTTP 200`). |
| **Case A2: Long Route without Stations** | `total_miles > 500` AND 0 stations found | ❌ **Infeasible** | Returns `HTTP 400 Bad Request`: `"❌ ERROR: No stations found and route > 500 miles"`. |
| **Case B1: First Station Beyond Max Range** | First station `dist > 500` miles | ❌ **Infeasible** | Returns `HTTP 400 Bad Request`: `"❌ ERROR: First station at X miles, max range 500 miles"`. |
| **Case B2: Desert Zone Gap Between Stations** | Gap between consecutive stations `> 500` mi | ❌ **Infeasible** | Returns `HTTP 400 Bad Request`: `"❌ ERROR: Gap of X miles between Y and Z miles (station: Name)"`. |
| **Case B3: Final Leg Beyond Max Range** | Distance from last station to destination `> 500` mi | ❌ **Infeasible** | Returns `HTTP 400 Bad Request`: `"❌ ERROR: X miles to destination, max range 500 miles"`. |
| **Case B4: Valid Corridor Gaps** | All station gaps `<= 500` mi | ✅ **Feasible** | Route passes feasibility and proceeds to greedy optimizer. |

---

## 🏛️ Tech Stack

- **Backend Framework**: Python 3.12 / 3.14, Django 6.1.1, Django REST Framework (DRF)
- **Database**: PostgreSQL 18.4 (Bounding box spatial queries, indexed on `latitude`/`longitude`)
- **Data Processing**: Pandas (Excel ingestion & lowest price deduplication), NumPy (Vectorized Haversine)
- **Mapping & Routing**: Mapbox Geocoding API, Mapbox Directions API (Strictly capped at 3 API calls max)
- **Frontend & Visualization**: Mapbox GL JS (WebGL rendering), HTML5, CSS3, JavaScript ES6+
- **Caching**: Redis / Django Memory Cache

---

## 💻 Local Development & Setup

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 18.4
- Mapbox API Access Token (`MAPBOX_ACCESS_TOKEN`)
- Git

### 2. Clone & Virtual Environment
```bash
git clone https://github.com/votre-compte/fuel-route-optimizer.git
cd fuel-route-optimizer

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Variables (`.env`)

Create a **`.env`** file in the root directory:

```env
DEBUG=True
SECRET_KEY=your_django_secret_key_here

MAPBOX_ACCESS_TOKEN=pk.eyJ1IjoieW91ci11c2VybmFtZSIsImEiOiJjb...

DB_NAME=fuel_optimizer_db
DB_USER=postgres
DB_PASSWORD=your_postgres_password_here
DB_HOST=127.0.0.1
DB_PORT=5432
```

Variables are loaded securely into Django using `python-dotenv`.

### 5. Exclusion of Sensitive Files (`.gitignore`)
```gitignore
venv/
.env
.env.local
*.sqlite3
__pycache__/
*.py[cod]
.DS_Store
```

### 6. Migrations, Ingestion & Running Server
```bash
# 1. Apply PostgreSQL Migrations
python manage.py migrate

# 2. Ingest Enriched Excel Dataset using Pandas Command
python manage.py import_fuel_stations --csv-file=fuel_price_enriched_with_coordinates.xlsx

# 3. Start Development Server
python manage.py runserver
```

---

## 📡 API Reference

### 1. Interactive Map UI
`GET /api/map/`
- **Description**: Serves the WebGL map interface (`route_map.html`).
- **Response**: `200 OK`

### 2. Direct Route Optimization API
`GET /api/route/`
- **Query Parameters**:
  - `start` (string, required): Departure address or city (e.g. `Miami, FL`).
  - `finish` (string, required): Destination address or city (e.g. `New York, NY`).

#### Successful Response (`200 OK`):
```json
{
  "status": "success",
  "message": "✅ Route optimized: 3 stops, total cost $412.35",
  "data": {
    "start_location": "Miami, FL",
    "finish_location": "New York, NY",
    "total_distance_miles": 1280.5,
    "max_truck_range_miles": 500.0,
    "total_fuel_gallons": 128.05,
    "total_fuel_cost": 412.35,
    "avg_price_per_gallon": 3.22,
    "number_of_fuel_stops": 3,
    "candidate_stations_found": 86,
    "fuel_stops": [
      {
        "stop_number": 1,
        "name": "Circle K #2706617",
        "address": "2250 US HWY 98 N",
        "city": "Lakeland",
        "state": "FL",
        "price_per_gallon": 3.251,
        "distance_from_start_miles": 253.19,
        "off_route_distance_miles": 0.42,
        "distance_from_previous_miles": 253.19,
        "gallons_purchased": 25.32,
        "cost_dollars": 82.31,
        "coordinates": {
          "latitude": 28.064,
          "longitude": -81.958
        }
      }
    ],
    "route_geometry": {
      "type": "LineString",
      "coordinates": [[-80.191, 25.761], ...]
    }
  }
}
```

#### Error Response (`400 Bad Request`):
```json
{
  "status": "error",
  "message": "❌ ERROR: Gap of 520.5 miles between 120.0 and 640.5 miles (station: Pilot Travel Center #104)",
  "data": {
    "start_location": "Miami, FL",
    "finish_location": "Remote Area, US",
    "total_distance_miles": 850.0,
    "route_geometry": { "type": "LineString", "coordinates": [...] }
  }
}
```

### 3. Cached Route API
`GET /api/route/cached/`
- **Description**: Same payload as `/api/route/`, but cached in Redis/Memory for **1 hour** (`"cached": true`, latency < 15 ms).

---

## ⚡ Performance & Benchmarks

| Route Type | Distance | Direct Time | Cached Time | HTTP Status |
| :--- | :--- | :--- | :--- | :--- |
| **Short Route (< 500 mi)** | 95.2 mi | ~0.35 s | < 10 ms | `200 OK` (0 stops) |
| **Long Route (Miami ➔ New York)** | 1,280.5 mi | ~1.45 s | < 10 ms | `200 OK` (3 stops) |
| **Desert Zone / Gap > 500 mi** | 850.0 mi | ~0.40 s | N/A | `400 Bad Request` |

---


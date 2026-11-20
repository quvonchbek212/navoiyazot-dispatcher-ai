# Navoiyazot Logistics · AI Dispatcher API

High-performance logistics dispatching engine designed for the **Navoiyazot industrial chemical complex**. Automates vehicle selection for freight requests, tracks GPS movements, and monitors vehicle stays inside geofenced garage and factory yard zones.

---

## Key Capabilities

* **Automated Vehicle Allocation**: Matches transport requests to available, technically inspected vehicles considering payload weight, volume, and vehicle classification.
* **Geofenced Yard & Garage Monitoring**: Real-time detection of garage entry, exit, and idle long-stop events using GPS telemetry.
* **Vehicle Status & Telemetry**: Tracks real-time vehicle movement, speed profile, and active transport assignments.
* **Zero Disruption Sync**: Thread-safe background monitoring with deduped periodic snapshots.

---

## Tech Stack

* **Language**: Python 3.12+
* **Framework**: FastAPI (Asynchronous REST API)
* **Data Validation**: Pydantic v2
* **Database Driver**: Psycopg2-binary (PostgreSQL)
* **Geo-processing**: Haversine distance, polygon geofence algorithms
* **HTTP Client**: HTTPX (Async telemetry integration)

---

## Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/ai-dispatcher/workspace` | Get dispatch board, matching requests, and yard status |
| `POST` | `/ai-dispatcher/refresh` | Trigger re-computation of vehicle allocations |
| `GET` | `/ai-dispatcher/garage` | Retrieve current geofence coordinates & stay parameters |
| `PUT` | `/ai-dispatcher/garage` | Update garage radius, coordinates, and thresholds |
| `GET` | `/ai-dispatcher/observation` | Retrieve detailed GPS telemetry & activity for a vehicle |
| `GET` | `/healthz` | Service health status |

---

## Quick Start

### 1. Installation
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file based on your environment:
```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=atil_navoiyazot
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. Run Service
```bash
python main.py
# Server runs on http://localhost:8001 (Docs: http://localhost:8001/docs)
```

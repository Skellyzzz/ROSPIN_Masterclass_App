# Dive Spot Finder

A platform for discovering cliff jumping spots, monitoring marine water quality and detecting potential oil spills using satellite data.

## Project Structure

```
ROSPIN_Masterclass_App/
├── frontend/            # React + TypeScript + Vite + Tailwind CSS
├── backend/             # FastAPI (to be added)
├── gis/                 # Satellite + LiDAR data pipeline, QGIS project, web app prototype
├── docker-compose.yml   # PostgreSQL + PostGIS
└── README.md
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Backend | Python, FastAPI |
| Database | PostgreSQL + PostGIS |
| Infrastructure | Docker Compose (database) |

## Prerequisites

- [Node.js](https://nodejs.org/) 20.19+ or 22+
- [Python](https://www.python.org/) 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Git

## Quick Start

### 1. Database

```bash
docker compose up -d
```

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The app runs at <http://localhost:5173>. See [`frontend/README.md`](frontend/README.md) for details.

### 3. Backend

Coming soon.

## Database (PostgreSQL + PostGIS)

The database runs in Docker using the `postgis/postgis:16-3.4` image.

### Connection details

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5433` |
| Database | `divespot` |
| User | `divespot` |
| Password | `divespot_dev` |

Connection string:

```
postgresql://divespot:divespot_dev@localhost:5433/divespot
```

Port `5433` is used on the host to avoid conflicts with a local PostgreSQL instance on `5432`. These credentials are for local development only.

### Verify PostGIS

```bash
docker exec -it divespot-db psql -U divespot -d divespot -c "SELECT PostGIS_Version();"
```

Run a basic spatial query:

```bash
docker exec -it divespot-db psql -U divespot -d divespot -c "SELECT ST_AsText(ST_SetSRID(ST_MakePoint(28.0, 44.2), 4326));"
```

Expected result: `POINT(28 44.2)`.

### Useful commands

| Command | Effect |
|---|---|
| `docker compose up -d` | Start the database |
| `docker compose stop` | Stop it (data is kept) |
| `docker compose down` | Remove the container (data is kept in the volume) |
| `docker compose down -v` | Remove the container and all data |
| `docker ps` | Check running containers |

### Troubleshooting

- **`port is already allocated`:** another service is using the port. Change the left side of the port mapping in `docker-compose.yml` (for example `"5434:5432"`) and update the connection string accordingly.
- **Docker command not found or engine not running:** start Docker Desktop and wait until it reports the engine is running.

## GIS data pipeline (`gis/`)

The satellite and LiDAR processing behind the spots: PlanetScope water depth calibrated with ICESat-2, Sentinel-2 monthly statistics, LiDAR cliff analysis, orthophoto rock detection, wave exposure and swim routes. For the Mallorca test area it already produces 133 rated jump spots (`gis/outputs/spots/cliff_spots.gpkg`) and a static web app prototype with a 3D diorama per spot (`gis/outputs/webapp`).

Details, data sources and how to run it: [`gis/README.md`](gis/README.md).

## Roadmap

- **Phase 1 – MVP Foundation:** authentication, dashboard, interactive map, first cliff jumping spots, water quality structure
- **Phase 2 – Advanced Features:** Copernicus Marine data, bathymetry, suitability score, oil spill detection with Sentinel-1
- **Phase 3 – Finalization:** environmental alerts, anomaly detection, testing, documentation, demo
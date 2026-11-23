# Dive Spot Finder – GIS pipeline

**Cliff-diving spot safety from Earth Observation & LiDAR.**

Built for the **ROSPIN Satellite Data Processing Masterclass** (3rd edition).

Dive Spot Finder finds coastal cliffs you can jump from and rates each one: is the water deep enough, are there rocks at the
entry, is there room for a run-up, where do you climb out, how often is the sea calm, and which months are best.
Everything is built from free or research-licensed data, much of it from satellites.

Test area: ~2 km of the east coast of Mallorca (Spain), 133 jump spots found and rated.

> Dive Spot Finder is a pre-selection tool, not a safety guarantee. Satellite-derived depth has an error of ~1–3 m and
> boulders in deep or dark water are not visible. Always check the depth on site and never jump alone.

## What it does

| Check | Data | Flags the spot when… |
| --- | --- | --- |
| Height and horizontal distance to the water | LiDAR | the water is more than 5 m away |
| Run-up, ledges, cracks behind the lip | LiDAR | there is no run-up or a ledge has to be cleared |
| Water depth at the entry | PlanetScope + ICESat-2 (satellite) | below 3 / 4 / 5 / 6 m for cliffs under 5 / 10 / 20 / over 20 m |
| Seabed type | PlanetScope (satellite) + Balearic habitat map | rocky or dark bottom |
| Rocks at the entry | 25 cm aerial orthophoto | rocks at the surface or visible boulders |
| Wave exposure | Open-Meteo wave history + coastline shape | exposed spot, frequent waves |
| Foam and turbidity | PlanetScope + Sentinel-2 (satellite) | frequent foam or turbid water |
| Swim route to a safe exit | LiDAR (shortest path through water) | exit more than 150 m away |
| Access | OpenStreetMap | (information only) |
| Best months | Open-Meteo + Sentinel-2 | (information only: ≥ 80% calm days, water ≥ 21 °C, little foam) |

Each spot gets **Promising / Caution / Unsafe** with the reasons spelled out, and a difficulty from Beginner (< 5 m)
to Extreme (> 20 m).

### Web app

- Map (Esri satellite) with the spots coloured by safety, filters, and a live 3-day wave forecast per spot.
- Spot sheet with the verdict, depth, seabed, run-up, swim to the exit, exposure, access and best months.
- **3D diorama** of each spot: a round tabletop model cut from the LiDAR terrain with the orthophoto on top, the
  satellite-derived seabed under translucent water, the animated jump arc (fall time, entry speed) and the swim route.
  Three modes: hybrid (terrain + LiDAR point texture), 3D model, LiDAR points.
- **Tiled 3D data:** terrain, texture and points are stored once in 50 × 50 m tiles (40 MB for the test area). A
  diorama downloads only the tiles inside its circle (usually under 1 MB) and neighbouring spots reuse them.

## Data

### Satellite data

| Data | What it is | Used for |
| --- | --- | --- |
| PlanetScope SuperDove, 8 bands, 3 m | multispectral imagery, 4 dates (Sep–Oct 2026) | water depth, seabed type, turbidity, algae, foam |
| ICESat-2 ATL24 (NASA) | satellite laser bathymetry | calibrating the Planet depth |
| Sentinel-2 L2A (ESA Copernicus), 10 m | 565 images, 2018–2026 | monthly foam and turbidity → best months |
| Esri World Imagery | satellite basemap | web map background |

### Other data

| Data | What it is | Used for |
| --- | --- | --- |
| LiDAR PNOA 2024 (IGN Spain) | airborne point cloud, 5–10 pts/m², RGB | cliff height and shape, run-up, exits, 3D model |
| PNOA orthophoto 25 cm (IGN Spain) | aerial photo, May 2024 | rocks at the entry, foam, 3D texture |
| Balearic seabed habitat map (IDEIB) | sand, Posidonia, rock with algae | seabed type at the entry |
| Open-Meteo Marine | wave and sea temperature history + forecast | exposure, best months, daily conditions |
| OpenStreetMap | paths, roads, parking | access |

## How it works

| Step | Script | Runs in |
| --- | --- | --- |
| 1 | `water_products.py` – water mask, corrections, turbidity, chlorophyll, depth ratio, seabed classes from Planet | QGIS |
| 2 | `fetch_icesat2_atl24.py` – ICESat-2 bottom photons via SlideRule | venv |
| 3 | `calibrate_sdb.py` – calibrates the Planet depth on ICESat-2 (Stumpf / Lyzenga, leave-one-track-out) | QGIS |
| 4 | `fetch_pnoa_ortho.py` – 25 cm orthophoto from the IGN WMS | QGIS |
| 5 | `ortho_rocks.py` – rocks, foam and dark objects at the cliff foot | QGIS |
| 6 | `seabed_type.py` – seabed type from the IDEIB habitat map | QGIS |
| 7 | `cliff_analysis.py` – terrain analysis, jump spots, swim routes, safety and difficulty | QGIS |
| 8 | `wave_exposure.py` – wave exposure and monthly calm days per spot | QGIS |
| 9 | `osm_access.py` – access from OpenStreetMap | QGIS |
| 10 | `s2_timeseries.py` – Sentinel-2 monthly statistics | venv |
| 11 | `export_app.py`, `export_tiles.py` – web app data and 3D tiles | QGIS / venv |
| 12 | `load_layers.py` – loads and styles all layers in the QGIS project | QGIS |

The digital terrain model (`outputs/lidar/dtm_1m.tif`) is built from LiDAR classes 2 (ground) and 9 (water) with the
PDAL algorithms in QGIS. Detailed notes on every product and method: [`outputs/README.md`](outputs/README.md) (Romanian).

## Getting the data

- **In this repository:** code, the QGIS project, the jump spots (`outputs/spots`), swim routes, waves, ICESat-2,
  OpenStreetMap and Sentinel-2 statistics, and the complete web app with its 3D tiles.
- **[GitHub Release gis-data-v1](https://github.com/Skellyzzz/ROSPIN_Masterclass_App/releases/tag/gis-data-v1) (`dive-spot-finder-gis-data-v1.zip`):** the two LiDAR `.laz` tiles and the larger rasters (LiDAR, orthophoto,
  seabed, Sentinel-2). Unzip it into the `gis/` folder.
- **Not included: PlanetScope imagery** and the products that keep its pixel values (`outputs/water`). The Planet
  Education & Research license does not allow publishing them. With your own Planet access, order PSScene
  `analytic_8b_sr_udm2` for the area and rerun step 1.

### Running

All commands below run from the `gis/` folder.

- QGIS 4.2 (with PDAL): open `cliff_dive_spot_finder.qgz` (relative paths) and run a script from the Python console:
  `exec(open(QgsProject.instance().homePath() + "/scripts/<script>.py", encoding="utf-8").read())`
- Python 3.12 venv for the venv steps:
  `py -3.12 -m venv .venv-icesat2` then `.venv-icesat2/Scripts/python -m pip install -r requirements.txt`
- Web app locally: `py -m http.server 8765 --directory outputs/webapp`, then open http://localhost:8765

Scripts find the project folder automatically (the open QGIS project, or the parent of `scripts/`); set
`DIVESPOT_ROOT` to override it.

## Team

- Dan Alupei
- Sebastian Ciui
- Gabriel Feraru
- Oana Tătărău
- Irinuca Ștefania Ungureanu
- Denisa Ileana Urda

## Licenses and attribution

Code: [MIT](LICENSE). Data keep their own licenses:

- Planet Team (2026). Planet Application Program Interface: In Space for Life on Earth. San Francisco, CA. https://api.planet.com
  — imagery under the Planet Education & Research program; only derived products are published here.
- LiDAR-PNOA 2024 and PNOA orthophoto: CC BY 4.0, © Instituto Geográfico Nacional (scne.es).
- Contains modified Copernicus Sentinel data (2018–2026).
- NASA ICESat-2 ATL24, accessed through SlideRule.
- Seabed habitats: Govern de les Illes Balears – IDEIB (CC BY-SA).
- Wave and sea-temperature data by Open-Meteo.com (CC BY 4.0).
- © OpenStreetMap contributors (ODbL).
- Basemap: Esri, Maxar, Earthstar Geographics.

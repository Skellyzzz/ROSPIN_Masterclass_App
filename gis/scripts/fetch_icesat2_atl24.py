"""Descarca fotonii de batimetrie ICESat-2 ATL24 peste zona Planet, prin serviciul public SlideRule.

Rulare (in mediul virtual separat, nu in QGIS):
    .venv-icesat2/Scripts/python scripts/fetch_icesat2_atl24.py   (din folderul proiectului)

ATL24 = produsul oficial NASA de batimetrie costiera ICESat-2: fotonii sunt deja clasificati
(fund / suprafata), cu corectie de refractie si cote ortometrice (EGM2008).
Iesire: outputs/icesat2/atl24_photons.gpkg (+ .parquet)
"""
import os
import sys

from sliderule import sliderule


def _project_root():
    """Folderul proiectului: variabila DIVESPOT_ROOT, folderul proiectului QGIS deschis sau parintele lui scripts/."""
    import os as _os
    import sys as _sys
    if _os.environ.get("DIVESPOT_ROOT"):
        return _os.environ["DIVESPOT_ROOT"].replace("\\", "/")
    if "qgis.core" in _sys.modules:
        from qgis.core import QgsProject
        home = QgsProject.instance().homePath()
        if home and _os.path.isdir(_os.path.join(home, "scripts")):
            return home
    return _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))).replace("\\", "/")


_ROOT = _project_root()

OUT = f"{_ROOT}/outputs/icesat2"
os.makedirs(OUT, exist_ok=True)

# extinderea scenelor Planet (lon/lat), cu ~1 km in plus in larg
AOI = [
    {"lon": 3.270, "lat": 39.478},
    {"lon": 3.335, "lat": 39.478},
    {"lon": 3.335, "lat": 39.518},
    {"lon": 3.270, "lat": 39.518},
    {"lon": 3.270, "lat": 39.478},
]

sliderule.init(verbose=True)
parms = {"atl24": {"class_ph": ["bathymetry", "sea_surface"]}} if "--with-surface" in sys.argv else {}
gdf = sliderule.run("atl24x", parms, aoi=AOI)
print("fotoni:", len(gdf))
if len(gdf):
    print(gdf.columns.tolist())
    print(gdf.head())
    gdf.to_parquet(f"{OUT}/atl24_photons.parquet")
    gdf.to_file(f"{OUT}/atl24_photons.gpkg", layer="photons", driver="GPKG")

    # CSV in UTM 31N (grila Planet) pentru calibrate_sdb.py
    g = gdf.reset_index()
    g["depth"] = g["surface_h"] - g["ortho_h"]
    g = g.to_crs(32631)
    g["x"], g["y"] = g.geometry.x, g.geometry.y
    g["date"] = g["time_ns"].dt.strftime("%Y%m%d")
    g["track"] = g["date"] + "_" + g["rgt"].astype(str) + "_" + g["gt"].astype(str)
    cols = ["x", "y", "depth", "surface_h", "ortho_h", "confidence", "quality_ph", "track", "date", "x_atc"]
    g[cols].to_csv(f"{OUT}/atl24_photons_utm31n.csv", index=False)

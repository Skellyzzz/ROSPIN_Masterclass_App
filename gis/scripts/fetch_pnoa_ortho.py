"""Descarca ortofoto PNOA (IGN, 25 cm, mai 2024) pentru zona LiDAR, prin WMS-ul public IGN.

    exec(open(QgsProject.instance().homePath() + "/scripts/fetch_pnoa_ortho.py", encoding="utf-8").read())

Iesire: outputs/ortho/pnoa_ortho_25cm.tif (RGB, EPSG:25831, grila aliniata la LiDAR)
"""
import os
import urllib.request

from osgeo import gdal


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

OUT = f"{_ROOT}/outputs/ortho"
os.makedirs(f"{OUT}/tiles", exist_ok=True)
URL = "https://www.ign.es/wms-inspire/pnoa-ma"
RES = 0.25
X0, Y0, X1, Y1 = 524980, 4370980, 526020, 4373020   # zona LiDAR + 20 m
TW, TH = 520, 510                                    # m pe tile -> 2080 x 2040 px (< 4096)

tiles = []
y = Y0
while y < Y1:
    x = X0
    while x < X1:
        bx1, by1 = min(x + TW, X1), min(y + TH, Y1)
        w, h = int(round((bx1 - x) / RES)), int(round((by1 - y) / RES))
        name = f"{OUT}/tiles/t_{int(x)}_{int(y)}.jpg"
        if not os.path.exists(name):
            q = (f"{URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=OI.OrthoimageCoverage&STYLES="
                 f"&CRS=EPSG:25831&BBOX={x},{y},{bx1},{by1}&WIDTH={w}&HEIGHT={h}&FORMAT=image/jpeg")
            req = urllib.request.Request(q, headers={"User-Agent": "qgis-research-client"})
            with urllib.request.urlopen(req, timeout=120) as r, open(name, "wb") as f:
                f.write(r.read())
        # georeferentiere: GeoTIFF fara pierderi de la JPEG
        tif = name.replace(".jpg", ".tif")
        gdal.Translate(tif, name, outputSRS="EPSG:25831", outputBounds=[x, by1, bx1, y])
        tiles.append(tif)
        x = bx1
    y = min(y + TH, Y1)

vrt = gdal.BuildVRT(f"{OUT}/_ortho.vrt", tiles)
vrt = None
gdal.Translate(f"{OUT}/pnoa_ortho_25cm.tif", f"{OUT}/_ortho.vrt",
               creationOptions=["COMPRESS=JPEG", "JPEG_QUALITY=92", "PHOTOMETRIC=YCBCR", "TILED=YES"])
ds = gdal.Open(f"{OUT}/pnoa_ortho_25cm.tif")
ds.BuildOverviews("AVERAGE", [2, 4, 8, 16])
print("ortofoto:", ds.RasterXSize, "x", ds.RasterYSize, ds.GetGeoTransform(), "tiles", len(tiles))

"""Tipul fundului marii din cartografia bionomica oficiala a Guvernului Balearelor (IDEIB,
serviciul GOIB_Posidonia_IB, stratul 4 "LIFE 2006 Bionomia LIC"; licenta CC BY-SA).

Descarcare (o data):
  .../GOIB_Posidonia_IB/MapServer/4/query?geometry=<bbox>&inSR=25831&outFields=*&outSR=25831&f=geojson
  -> outputs/seabed/ideib_layer4.geojson   (stratul 2 "Posidonia oceanica" -> ideib_layer2.geojson)

    exec(open(QgsProject.instance().homePath() + "/scripts/seabed_type.py", encoding="utf-8").read())

Coduri (outputs/seabed/seabed_type_1m.tif, grila LiDAR):
  1 nisip   2 nisip + Posidonia (alternanta)   3 Posidonia   4 Cymodocea (iarba marina pe nisip)
  5 stanca cu alge (comunitate fotofila)       6 stanca cu alge + Posidonia    9 altele / necunoscut
"""
import json

from osgeo import gdal, ogr, osr


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

ROOT = f"{_ROOT}"
SB = f"{ROOT}/outputs/seabed"
NAMES = {1: "nisip", 2: "nisip + Posidonia", 3: "Posidonia", 4: "Cymodocea pe nisip",
         5: "stanca cu alge", 6: "stanca cu alge + Posidonia", 9: "alt tip"}


def code(tipus, tipus2=""):
    t = f"{tipus or ''} | {tipus2 or ''}".lower()
    rock = "fot" in t or "roca" in t or "pedra" in t or "piedra" in t
    posi = "posidonia" in t
    sand = "arenes" in t or "arena" in t or "fang" in t
    if rock and posi:
        return 6
    if rock:
        return 5
    if (tipus or "").lower().startswith("posidonia"):
        return 2 if sand else 3
    if "cymodocea" in t:
        return 4
    if sand and posi:
        return 2
    if sand:
        return 1
    if posi:
        return 3
    return 9


src = json.load(open(f"{SB}/ideib_layer4.geojson", encoding="utf-8", errors="replace"))
srs = osr.SpatialReference()
srs.ImportFromEPSG(25831)
mem = ogr.GetDriverByName("Memory").CreateDataSource("m")
lyr = mem.CreateLayer("b", srs, ogr.wkbMultiPolygon)
lyr.CreateField(ogr.FieldDefn("code", ogr.OFTInteger))
lyr.CreateField(ogr.FieldDefn("tip", ogr.OFTString))
lyr.CreateField(ogr.FieldDefn("tip_ro", ogr.OFTString))
counts = {}
for f in src["features"]:
    p = f["properties"]
    c = code(p.get("TIPUS"), p.get("TIPUS2"))
    counts[NAMES[c]] = counts.get(NAMES[c], 0) + 1
    g = ogr.CreateGeometryFromJson(json.dumps(f["geometry"]))
    feat = ogr.Feature(lyr.GetLayerDefn())
    feat.SetField("code", c)
    feat.SetField("tip", p.get("TIPUS") or "")
    feat.SetField("tip_ro", NAMES[c])
    feat.SetGeometry(g)
    lyr.CreateFeature(feat)

# vector pentru harta
gp = f"{SB}/seabed_type.gpkg"
drv = ogr.GetDriverByName("GPKG")
try:
    drv.DeleteDataSource(gp)
except Exception:
    pass
out = drv.CopyDataSource(mem, gp)
out = None

# raster pe grila LiDAR 1 m (poligoanele mici, ex. Posidonia peste nisip, se suprapun: ordinea conteaza)
dtm = gdal.Open(f"{ROOT}/outputs/lidar/dtm_1m.tif")
r = gdal.GetDriverByName("GTiff").Create(f"{SB}/seabed_type_1m.tif", dtm.RasterXSize, dtm.RasterYSize, 1,
                                         gdal.GDT_Byte, ["COMPRESS=DEFLATE"])
r.SetGeoTransform(dtm.GetGeoTransform())
r.SetProjection(dtm.GetProjection())
r.GetRasterBand(1).SetNoDataValue(0)
gdal.RasterizeLayer(r, [1], lyr, options=["ATTRIBUTE=code", "ALL_TOUCHED=TRUE"])
r = None
print("poligoane pe tip:", counts)

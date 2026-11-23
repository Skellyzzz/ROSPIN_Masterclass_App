"""Accesul la fiecare punct de saritura din OpenStreetMap (poteci, drumuri, parcari).

Date: outputs/osm/access_raw.json (Overpass API, highway=* si amenity=parking in zona de studiu).
    exec(open(QgsProject.instance().homePath() + "/scripts/osm_access.py", encoding="utf-8").read())

Pentru fiecare punct:
  dist_path_m       distanta in linie dreapta pana la cea mai apropiata poteca/alee/scari/drum de pamant
  dist_road_m       ... pana la cel mai apropiat drum carosabil
  walk_from_parking_m  traseul cel mai scurt pe reteaua OSM de la o parcare pana la punctul retelei cel mai
                    apropiat de punct + portiunea finala in afara potecii (off_trail_m)
Iesiri: outputs/osm/osm_access.gpkg (straturi ways, parking) si campurile noi in cliff_spots.gpkg
"""
import heapq
import json
import math
import os

import numpy as np
from osgeo import ogr, osr


def _project_root():
    """Folderul proiectului: variabila CLAVADO_ROOT, folderul proiectului QGIS deschis sau parintele lui scripts/."""
    import os as _os
    import sys as _sys
    if _os.environ.get("CLAVADO_ROOT"):
        return _os.environ["CLAVADO_ROOT"].replace("\\", "/")
    if "qgis.core" in _sys.modules:
        from qgis.core import QgsProject
        home = QgsProject.instance().homePath()
        if home and _os.path.isdir(_os.path.join(home, "scripts")):
            return home
    return _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))).replace("\\", "/")


_ROOT = _project_root()

ROOT = f"{_ROOT}"
RAW = f"{ROOT}/outputs/osm/access_raw.json"
els = json.load(open(RAW, encoding="utf-8"))["elements"]

wgs = osr.SpatialReference(); wgs.ImportFromEPSG(4326)
utm = osr.SpatialReference(); utm.ImportFromEPSG(25831)
for s_ in (wgs, utm):
    s_.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
TR = osr.CoordinateTransformation(wgs, utm)


def to_utm(lon, lat):
    x, y, _ = TR.TransformPoint(lon, lat)
    return x, y


WALK = {"path", "footway", "track", "steps", "pedestrian", "cycleway", "bridleway"}
ROAD = {"residential", "service", "secondary", "tertiary", "unclassified", "primary", "living_street", "road"}

nodes = {}           # id -> (x, y)
adj = {}             # id -> [(id2, len)]
ways = []            # (kind, highway, name, [(x,y)...])
parkings = []        # (x, y, name)
for e in els:
    t = e.get("tags", {})
    if t.get("amenity") == "parking":
        if e["type"] == "node":
            parkings.append((*to_utm(e["lon"], e["lat"]), t.get("name", "")))
        elif "geometry" in e:
            pts = [to_utm(g["lon"], g["lat"]) for g in e["geometry"]]
            parkings.append((float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts])), t.get("name", "")))
        continue
    hw = t.get("highway")
    if e["type"] != "way" or not hw or "geometry" not in e:
        continue
    kind = "walk" if hw in WALK else "road" if hw in ROAD else "other"
    pts = [to_utm(g["lon"], g["lat"]) for g in e["geometry"]]
    ways.append((kind, hw, t.get("name", ""), pts))
    ids = e.get("nodes", [])
    for i, nid in enumerate(ids):
        nodes[nid] = pts[i]
    for a, b in zip(ids[:-1], ids[1:]):
        L = math.dist(nodes[a], nodes[b])
        adj.setdefault(a, []).append((b, L))
        adj.setdefault(b, []).append((a, L))

NID = np.array(list(nodes.keys()))
NXY = np.array([nodes[i] for i in NID])

# Dijkstra multi-sursa din toate parcarile (legate de cel mai apropiat nod)
dist = {}
pq = []
for px, py, _ in parkings:
    j = int(np.argmin(np.hypot(NXY[:, 0] - px, NXY[:, 1] - py)))
    d0 = float(np.hypot(NXY[j, 0] - px, NXY[j, 1] - py))
    heapq.heappush(pq, (d0, int(NID[j])))
while pq:
    d_, n_ = heapq.heappop(pq)
    if n_ in dist:
        continue
    dist[n_] = d_
    for m_, L in adj.get(n_, []):
        if m_ not in dist:
            heapq.heappush(pq, (d_ + L, m_))


def seg_dist(px, py, pts):
    best = 1e12
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L2))
        best = min(best, math.hypot(px - x1 - t * dx, py - y1 - t * dy))
    return best


# ---- salveaza retelele ca GeoPackage (pentru harta)
gp = f"{ROOT}/outputs/osm/osm_access.gpkg"
drv = ogr.GetDriverByName("GPKG")
if os.path.exists(gp):
    drv.DeleteDataSource(gp)
ods = drv.CreateDataSource(gp)
wl = ods.CreateLayer("ways", utm, ogr.wkbLineString)
for fn in ("kind", "highway", "name"):
    wl.CreateField(ogr.FieldDefn(fn, ogr.OFTString))
for kind, hw, nm, pts in ways:
    f = ogr.Feature(wl.GetLayerDefn())
    f.SetField("kind", kind); f.SetField("highway", hw); f.SetField("name", nm)
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(x, y)
    f.SetGeometry(g)
    wl.CreateFeature(f)
pl = ods.CreateLayer("parking", utm, ogr.wkbPoint)
pl.CreateField(ogr.FieldDefn("name", ogr.OFTString))
for x, y, nm in parkings:
    f = ogr.Feature(pl.GetLayerDefn()); f.SetField("name", nm)
    g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(x, y); f.SetGeometry(g); pl.CreateFeature(f)
ods = None

# ---- campuri pe puncte
NEW = [("dist_path_m", ogr.OFTReal), ("dist_road_m", ogr.OFTReal), ("dist_parking_m", ogr.OFTReal),
       ("walk_from_parking_m", ogr.OFTReal), ("off_trail_m", ogr.OFTReal), ("access_txt", ogr.OFTString)]
ds = ogr.Open(f"{ROOT}/outputs/spots/cliff_spots.gpkg", 1)
walk_ways = [w for w in ways if w[0] == "walk"]
road_ways = [w for w in ways if w[0] == "road"]
reach = np.array([int(i) in dist for i in NID])
res = {}
for lname in ("spots", "jumps"):
    lyr = ds.GetLayer(lname)
    names = [lyr.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(lyr.GetLayerDefn().GetFieldCount())]
    for n, t in NEW:
        if n not in names:
            lyr.CreateField(ogr.FieldDefn(n, t))
    for f in lyr:
        if lname == "spots":
            x, y = f.GetGeometryRef().GetX(), f.GetGeometryRef().GetY()
            dpath = min((seg_dist(x, y, w[3]) for w in walk_ways), default=np.nan)
            droad = min((seg_dist(x, y, w[3]) for w in road_ways), default=np.nan)
            dpark = min((math.hypot(x - px, y - py) for px, py, _ in parkings), default=np.nan)
            dd = np.hypot(NXY[:, 0] - x, NXY[:, 1] - y)
            # cel mai bun nod: traseu + portiune in afara potecii (penalizata x1.5, teren accidentat)
            cost = np.where(reach, [dist.get(int(i), np.inf) for i in NID], np.inf) + 1.5 * dd
            j = int(np.argmin(cost))
            walk = float(dist.get(int(NID[j]), np.nan) + dd[j]) if np.isfinite(cost[j]) else np.nan
            off = float(dd[j])
            txt = ("poteca langa punct" if dpath < 30 else f"cea mai apropiata poteca la ~{dpath:.0f} m")
            if np.isfinite(walk) and off <= 150:
                txt += f"; ~{walk / 1000:.1f} km de la parcare (~{walk / 1000 / 3.5 * 60:.0f} min)"
            else:
                # potecile din apropiere nu sunt legate in OSM de reteaua de la parcari
                walk = np.nan
                txt += "; traseu de la parcare necunoscut (poteci OSM neconectate)"
            res[f.GetFID()] = {"dist_path_m": round(dpath, 0), "dist_road_m": round(droad, 0),
                               "dist_parking_m": round(dpark, 0),
                               "walk_from_parking_m": round(walk, 0) if np.isfinite(walk) else None,
                               "off_trail_m": round(off, 0), "access_txt": txt}
        for k, v in res.get(f.GetFID(), {}).items():
            if v is not None:
                f.SetField(k, v)
        lyr.SetFeature(f)
ds = None
w = np.array([v["walk_from_parking_m"] or np.nan for v in res.values()])
print(f"retea: {len(ways)} cai, {len(parkings)} parcari, {len(nodes)} noduri; "
      f"mers de la parcare min/median/max: {np.nanmin(w):.0f}/{np.nanmedian(w):.0f}/{np.nanmax(w):.0f} m")

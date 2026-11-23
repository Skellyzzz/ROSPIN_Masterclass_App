"""Exporta punctele de saritura pentru aplicatia web (outputs/webapp/spots.js, WGS84).

    exec(open(QgsProject.instance().homePath() + "/scripts/export_app.py", encoding="utf-8").read())

Luni bune pentru fiecare punct (toate conditiile, pe istoricul disponibil):
  - valuri: >= 80% din zile calme (val efectiv maxim 09-19 < 0.5 m)   outputs/waves/wave_monthly_spots.json
  - apa: temperatura medie la suprafata >= 21 C                        outputs/waves/sst_monthly.json
  - spuma (Sentinel-2): in <= 25% din scenele lunii, daca exista date    outputs/s2/s2_spot_stats.json
"""
import json
import os

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
OUT = f"{ROOT}/outputs/webapp"
os.makedirs(OUT, exist_ok=True)

src = osr.SpatialReference(); src.ImportFromEPSG(25831)
dst = osr.SpatialReference(); dst.ImportFromEPSG(4326)
for s_ in (src, dst):
    s_.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
TR = osr.CoordinateTransformation(src, dst)

def _load(path):
    return json.load(open(path)) if os.path.exists(path) else {}


s2 = _load(f"{ROOT}/outputs/s2/s2_spot_stats.json")
wave_m = _load(f"{ROOT}/outputs/waves/wave_monthly_spots.json")
sst = _load(f"{ROOT}/outputs/waves/sst_monthly.json")
CALM_MIN, SST_MIN, FOAM_MAX = 80, 21.0, 25

KEEP = ["height_m", "clearance_m", "face_angle_deg", "difficulty", "difficulty_txt", "min_depth_req_m",
        "safety", "safety_txt", "issues", "bottom_txt", "depth_est_m", "depth_cal_m", "seabed_txt",
        "rocks_landing_m2", "exit_type", "ortho_rock_out_m2", "ortho_rock_base_m2", "ortho_foam_pct", "run_up_m",
        "ledge_h_m", "crevasse_behind", "exit_dist_m", "turbidity_FNU", "chl_mg_m3",
        "facing_deg", "open_sector", "open_mask", "summer_calm_days_pct", "exposure_txt",
        "walk_from_parking_m", "off_trail_m", "access_txt"]

ds = ogr.Open(f"{ROOT}/outputs/spots/cliff_spots.gpkg")
jumps = {f.GetFID(): f.GetGeometryRef().Clone() for f in ds.GetLayer("jumps")}
# traseul de inot pana la iesire, [[lon, lat], ...] (5 zecimale ~ 1 m)
swim = {}
if ds.GetLayerByName("swim"):
    for f in ds.GetLayer("swim"):
        g = f.GetGeometryRef()
        swim[f.GetField("spot_fid")] = [[round(c, 6) for c in TR.TransformPoint(*g.GetPoint_2D(i))[:2]]
                                        for i in range(g.GetPointCount())]
feats = []
for f in ds.GetLayer("spots"):
    g = f.GetGeometryRef()
    lon, lat, _ = TR.TransformPoint(g.GetX(), g.GetY())
    jg = jumps[f.GetFID()]
    llon, llat, _ = TR.TransformPoint(*jg.GetPoint_2D(1))
    props = {k: f.GetField(k) for k in KEEP if f.GetFieldIndex(k) >= 0}
    props["id"] = f.GetFID()
    props["landing"] = [round(llon, 6), round(llat, 6)]
    if f.GetFID() in swim:
        props["swim"] = swim[f.GetFID()]
    st = s2.get(str(f.GetFID()), {}).get("monthly", {})
    wm_ = wave_m.get(str(f.GetFID()), {})
    months = {}
    for m in range(1, 13):
        k = str(m)
        w_, t_, s_ = wm_.get(k), sst.get(k), st.get(k)
        months[m] = {"calm": w_["calm_pct"] if w_ else None, "rough": w_["rough_pct"] if w_ else None,
                     "sst": t_["sst_mean"] if t_ else None,
                     "foam": s_["foam_scenes_pct"] if s_ else None, "turb": s_["turb_median"] if s_ else None}
    def ok(v):
        return ((v["calm"] is not None and v["calm"] >= CALM_MIN) and (v["sst"] is not None and v["sst"] >= SST_MIN)
                and (v["foam"] is None or v["foam"] <= FOAM_MAX))
    props["months"] = months
    props["best_months"] = [m for m, v in months.items() if ok(v)]
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                  "properties": props})
ds = None

meta = {"generated": __import__("datetime").date.today().isoformat(),
        "wave_point": {"lat": 39.497, "lon": 3.335},
        "s2_monthly": _load(f"{ROOT}/outputs/s2/s2_monthly.json") or None, "sst_monthly": sst or None,
        "best_rule": {"calm_min_pct": CALM_MIN, "sst_min_c": SST_MIN, "foam_max_pct": FOAM_MAX}}
with open(f"{OUT}/spots.js", "w", encoding="utf-8") as fh:
    fh.write("window.SPOTS = ")
    json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)
    fh.write(";\nwindow.META = ")
    json.dump(meta, fh, ensure_ascii=False)
    fh.write(";\n")
with open(f"{OUT}/spots.geojson", "w", encoding="utf-8") as fh:
    json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)
print("exportat:", len(feats), "puncte ->", OUT)

"""Statistici multi-anuale Sentinel-2 L2A (2018-2026) pentru apa din zona de studiu.

Sursa: Earth Search (Element84) STAC + COG-uri publice pe AWS (sentinel-cogs), fara cont.
Se citeste doar fereastra zonei (~4 x 3.5 km) din fiecare scena (citire pe intervale HTTP).

Rulare (mediul virtual separat, are rasterio):
    .venv-icesat2/Scripts/python scripts/s2_timeseries.py   (din folderul proiectului)

Pe fiecare scena (o scena / zi, tile 31SED, nori < 20%):
  apa valida  = masca de apa Planet (reproiectata la 10 m) & SCL fara nori/umbre & reflectanta > 0
  turbiditate = Nechad 2009 pe banda rosie (B04 minus B08 ca deglint simplu), FNU
  spuma       = NIR si albastru cu > 0.04 peste mediana apei largi din aceeasi scena
                (anomalie, ca sa nu se confunde cu reflexia soarelui / sunglint)
Iesiri (outputs/s2/):
  s2_turb_median_<sezon>.tif, s2_turb_p90_<sezon>.tif, s2_foam_freq_<sezon>.tif, s2_nobs_<sezon>.tif
  (sezon = vara: mai-oct, iarna: nov-apr), s2_monthly.json (climatologie pe luni pentru zona de coasta)
  s2_spot_stats.json (pe fiecare punct de saritura: turbiditate si spuma pe luni, cele mai bune luni)
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds


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
OUT = f"{ROOT}/outputs/s2"
os.makedirs(OUT, exist_ok=True)
BBOX_LL = [3.27, 39.48, 3.33, 39.52]
B = (523611.0, 4370322.0, 527751.0, 4373790.0)   # extinderea Planet in EPSG:32631
RES = 10.0
W, H = int((B[2] - B[0]) / RES), int((B[3] - B[1]) / RES)
DST_T = rasterio.transform.from_origin(B[0], B[3], RES, RES)
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

# ------------------------------------------------------------------ cautare STAC
items, url = [], "https://earth-search.aws.element84.com/v1/search"
body = {"collections": ["sentinel-2-l2a"], "bbox": BBOX_LL,
        "datetime": "2018-01-01T00:00:00Z/2026-11-01T00:00:00Z",
        "query": {"eo:cloud_cover": {"lt": 20}}, "limit": 200}
while True:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "research-client"})
    js = json.loads(urllib.request.urlopen(req, timeout=120).read())
    items += js["features"]
    nxt = [l for l in js.get("links", []) if l.get("rel") == "next"]
    if not nxt:
        break
    body = nxt[0].get("body", body)
    url = nxt[0]["href"]
by_day = {}
for it in items:
    if it["properties"].get("grid:code") != "MGRS-31SED":
        continue
    day = it["properties"]["datetime"][:10]
    if day not in by_day or it["properties"]["eo:cloud_cover"] < by_day[day]["properties"]["eo:cloud_cover"]:
        by_day[day] = it
days = sorted(by_day)
print(f"scene: {len(items)} gasite, {len(days)} zile unice", flush=True)

# masca de apa Planet -> 10 m
with rasterio.open(f"{ROOT}/outputs/water/water_mask.tif") as src:
    wm = np.zeros((H, W), "uint8")
    reproject(src.read(1), wm, src_transform=src.transform, src_crs=src.crs, dst_transform=DST_T,
              dst_crs="EPSG:32631", resampling=Resampling.mode)
WATER = wm == 1
# distanta (pixeli) de la uscat, prin dilatari succesive (fara scipy)
DIST = np.full((H, W), 99, "int16")
_land = ~WATER
DIST[_land] = 0
for _k in range(1, 31):
    _p = np.pad(_land, 1, constant_values=False)
    _land = (_p[1:-1, 1:-1] | _p[:-2, 1:-1] | _p[2:, 1:-1] | _p[1:-1, :-2] | _p[1:-1, 2:]
             | _p[:-2, :-2] | _p[:-2, 2:] | _p[2:, :-2] | _p[2:, 2:])
    DIST[(DIST == 99) & _land] = _k


def read_band(href, res_out=RES):
    with rasterio.open(href) as ds:
        win = from_bounds(*B, transform=ds.transform)
        a = ds.read(1, window=win, out_shape=(H, W), resampling=Resampling.nearest, boundless=True, fill_value=0)
    return a


CACHE = f"{OUT}/cache_v2"   # v2: spuma ca anomalie fata de apa larga (fara sunglint)
os.makedirs(CACHE, exist_ok=True)


FOAM_DN = 0.04   # spuma: NIR si albastru cu > 0.04 peste mediana apei largi (>= 300 m de mal) din aceeasi scena


def foam_from(nira, bluea, valid):
    return valid & (nira.astype("float32") > FOAM_DN) & (bluea.astype("float32") > FOAM_DN)


def process(day):
    cp = f"{CACHE}/{day}.npz"
    if os.path.exists(cp):
        z = np.load(cp)
        if z["turb"].size == 1:
            return day, None, "cache: fara apa valida"
        return day, (z["turb"], foam_from(z["nira"], z["bluea"], z["valid"]), z["valid"]), None
    r = _process(day)
    if r[1] is not None:
        t_, nira, bluea, v_ = r[1]
        np.savez_compressed(cp, turb=t_, nira=nira, bluea=bluea, valid=v_)
        r = (day, (t_, foam_from(nira, bluea, v_), v_), None)
    elif r[2] == "putina apa valida":
        np.savez_compressed(cp, turb=np.zeros(1), foam=np.zeros(1), valid=np.zeros(1))
    return r


def _process(day):
    it = by_day[day]
    a = it["assets"]
    try:
        blue, red, nir = (read_band(a[k]["href"]).astype("float32") for k in ("blue", "red", "nir"))
        scl = read_band(a["scl"]["href"])
    except Exception as e:
        return day, None, str(e)[:100]
    valid = WATER & (red > 0) & ~np.isin(scl, [0, 1, 3, 8, 9, 10, 11])
    if valid.sum() < 500:
        return day, None, "putina apa valida"
    # armonizare offset (procesare >= 04.00 are +1000 daca nu e deja scazut)
    off = 0.0
    if np.median(red[valid]) > 800:
        off = 1000.0
    blue, red, nir = (np.maximum(x - off, 0) / 10000.0 for x in (blue, red, nir))
    # sunglint-ul ridica uniform NIR si albastrul; spuma e locala -> anomalie fata de apa larga
    deep = valid & (DIST >= 30)
    if deep.sum() < 200:
        deep = valid & (DIST >= 10)
    nb, bb = (float(np.median(x[deep])) if deep.any() else 0.0 for x in (nir, blue))
    nira = np.where(valid, nir - nb, 0).astype("float16")
    bluea = np.where(valid, blue - bb, 0).astype("float16")
    foam = foam_from(nira, bluea, valid)
    rw = np.clip(red - nir, 1e-5, 0.155)
    turb = 228.1 * rw / (1 - rw / 0.1641)
    turb = np.where(valid & ~foam, turb, np.nan).astype("float32")
    return day, (turb, nira, bluea, valid), None


results = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, (day, res, err) in enumerate(ex.map(process, days)):
        if res is not None:
            results[day] = res
        if i % 50 == 0:
            print(f"  {i}/{len(days)} ({len(results)} valide)", flush=True)
print(f"scene folosite: {len(results)}", flush=True)

months = {d: int(d[5:7]) for d in results}
seasons = {"vara": [5, 6, 7, 8, 9, 10], "iarna": [11, 12, 1, 2, 3, 4]}
prof = {"driver": "GTiff", "width": W, "height": H, "count": 1, "crs": "EPSG:32631",
        "transform": DST_T, "dtype": "float32", "nodata": -9999.0, "compress": "deflate"}


def save(name, arr):
    with rasterio.open(f"{OUT}/{name}.tif", "w", **prof) as d:
        d.write(np.where(np.isfinite(arr), arr, -9999.0).astype("float32"), 1)


for sname, mm in seasons.items():
    ds_ = [d for d in results if months[d] in mm]
    if not ds_:
        continue
    T = np.stack([results[d][0] for d in ds_])
    F = np.stack([results[d][1] for d in ds_]).astype("float32")
    V = np.stack([results[d][2] for d in ds_]).astype("float32")
    with np.errstate(all="ignore"):
        save(f"s2_turb_median_{sname}", np.nanmedian(T, 0))
        save(f"s2_turb_p90_{sname}", np.nanpercentile(T, 90, 0))
        n = V.sum(0)
        save(f"s2_foam_freq_{sname}", np.where(n > 0, F.sum(0) / np.maximum(n, 1), np.nan))
        save(f"s2_nobs_{sname}", np.where(WATER, n, np.nan))

# climatologie lunara in fasia de coasta (<= 150 m de uscat)
coast = WATER & (DIST <= int(150 / RES))
monthly = {}
for m in range(1, 13):
    ds_ = [d for d in results if months[d] == m]
    if not ds_:
        continue
    tv = np.concatenate([results[d][0][coast & results[d][2]] for d in ds_])
    fv = [results[d][1][coast].sum() / max((coast & results[d][2]).sum(), 1) for d in ds_]
    monthly[m] = {"scene": len(ds_), "turb_median": round(float(np.nanmedian(tv)), 2),
                  "turb_p90": round(float(np.nanpercentile(tv, 90)), 2),
                  "foam_pct_median": round(100 * float(np.median(fv)), 2),
                  "foam_scenes_pct": round(100 * float(np.mean([f > 0.01 for f in fv])), 1)}
json.dump(monthly, open(f"{OUT}/s2_monthly.json", "w"), indent=1)

# statistici pe punct (apa la > 20 m de mal, pe o raza de 60 m in jurul punctului de intrare in apa)
try:
    import geopandas as gpd

    j = gpd.read_file(f"{ROOT}/outputs/spots/cliff_spots.gpkg", layer="jumps").to_crs(32631)
    spot = {}
    yy, xx = np.mgrid[0:H, 0:W]
    cx = B[0] + (xx + 0.5) * RES
    cy = B[3] - (yy + 0.5) * RES
    for fid, g in zip(j.index, j.geometry):
        lx, ly = g.coords[-1]
        # fara primii 20 m de langa mal: pixelii de 10 m de acolo sunt amestecati cu stanca luminoasa
        rr = np.hypot(cx - lx, cy - ly)
        zone = WATER & (DIST >= 3) & (rr <= 60)
        if zone.sum() < 3:
            zone = WATER & (DIST >= 3) & (rr <= 120)
        per_m = {}
        for m in range(1, 13):
            ds_ = [d for d in results if months[d] == m]
            fz, tz = [], []
            for d in ds_:
                t_, f_, v_ = results[d]
                vz = zone & v_
                if vz.sum() >= 2:
                    fz.append(f_[vz].mean())
                    tz.append(np.nanmedian(t_[vz]))
            if fz:
                per_m[m] = {"n": len(fz), "foam_scenes_pct": round(100 * float(np.mean([x > 0.1 for x in fz])), 0),
                            "turb_median": round(float(np.nanmedian(tz)), 2)}
        good = [m for m, v in per_m.items() if v["foam_scenes_pct"] <= 10 and v["turb_median"] <= 3]
        spot[int(fid) + 1] = {"monthly": per_m, "best_months": good}
    json.dump(spot, open(f"{OUT}/s2_spot_stats.json", "w"))
    print("statistici pe puncte:", len(spot), flush=True)
except Exception as e:  # noqa: BLE001
    print("statistici pe puncte esuate:", e, flush=True)
print("gata", flush=True)

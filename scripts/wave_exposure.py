"""Expunerea fiecarui punct de saritura la valuri, din istoricul valurilor (Open-Meteo Marine, gratuit,
fara cont; pentru acest punct datele exista din oct 2021, cererea pentru 2016-2025 intoarce valori goale
inainte) + forma coastei.

    exec(open(QgsProject.instance().homePath() + "/scripts/wave_exposure.py", encoding="utf-8").read())

Pentru fiecare punct:
  1. sectorul deschis spre mare: raze din punctul de intrare in apa, din 5 in 5 grade, pe masca de apa
     Planet; o directie e "deschisa" daca raza ramane pe apa 1500 m (sau iese din imagine pe apa)
  2. valul efectiv la punct = Hs * cos(diferenta dintre directia din care vine valul si directia in care
     priveste peretele), doar pentru directiile deschise
  3. statistici pe toata perioada disponibila (~4 ani): % ore cu val efectiv > 0.5 m / > 1 m (tot anul si mai-octombrie)
     si % zile "calme" vara (maximul zilei < 0.5 m)
  4. pe luni: % zile calme (val efectiv maxim intre 09-19 < 0.5 m) si agitate (>= 1 m)
     -> outputs/waves/wave_monthly_spots.json (cheie = FID-ul punctului)
Adauga campurile in outputs/spots/cliff_spots.gpkg (spots + jumps) si salveaza istoricul in outputs/waves/.
"""
import csv
import json
import math
import os
import urllib.request

import numpy as np
from osgeo import gdal, ogr, osr


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
OUTW = f"{ROOT}/outputs/waves"
os.makedirs(OUTW, exist_ok=True)
LAT, LON = 39.497, 3.335        # larg, la est de zona de studiu
HIST = f"{OUTW}/wave_history_2016_2025.csv"
VARS = "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_direction"

# ------------------------------------------------------------- 1. istoric valuri
if not os.path.exists(HIST):
    rows = []
    for year in range(2016, 2026):
        url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}&hourly={VARS}"
               f"&start_date={year}-01-01&end_date={year}-12-31&timezone=Europe%2FMadrid")
        req = urllib.request.Request(url, headers={"User-Agent": "research-client"})
        js = json.loads(urllib.request.urlopen(req, timeout=120).read())
        hh = js["hourly"]
        for i, t in enumerate(hh["time"]):
            rows.append([t] + [hh[v][i] for v in VARS.split(",")])
    with open(HIST, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time"] + VARS.split(","))
        w.writerows(rows)
    grid = {"lat": js["latitude"], "lon": js["longitude"]}
    json.dump(grid, open(f"{OUTW}/grid_point.json", "w"))

# temperatura apei la suprafata, climatologie lunara (pentru "lunile bune" din aplicatie)
SST = f"{OUTW}/sst_monthly.json"
if not os.path.exists(SST):
    url = (f"https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}"
           f"&hourly=sea_surface_temperature&start_date=2021-10-01&end_date=2026-10-31&timezone=Europe%2FMadrid")
    js = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-client"}),
                                           timeout=120).read())
    tv = np.array([x if x is not None else np.nan for x in js["hourly"]["sea_surface_temperature"]], float)
    tm = np.array([int(t[5:7]) for t in js["hourly"]["time"]])
    out = {}
    for m in range(1, 13):
        s_ = np.isfinite(tv) & (tm == m)
        if s_.any():
            out[m] = {"sst_mean": round(float(tv[s_].mean()), 1), "sst_p10": round(float(np.percentile(tv[s_], 10)), 1),
                      "sst_p90": round(float(np.percentile(tv[s_], 90)), 1)}
    json.dump(out, open(SST, "w"), indent=1)

data = list(csv.DictReader(open(HIST)))
T = np.array([r["time"] for r in data])
HS = np.array([float(r["wave_height"]) if r["wave_height"] else np.nan for r in data])
DIR = np.array([float(r["wave_direction"]) if r["wave_direction"] else np.nan for r in data])
ok = np.isfinite(HS) & np.isfinite(DIR)
T, HS, DIR = T[ok], HS[ok], DIR[ok]
MONTH = np.array([int(t[5:7]) for t in T])
DAY = np.array([t[:10] for t in T])
HOUR = np.array([int(t[11:13]) for t in T])
DAYTIME = (HOUR >= 9) & (HOUR <= 19)      # ora locala (cererea e in Europe/Madrid)
SUMMER = (MONTH >= 5) & (MONTH <= 10)
print(f"istoric: {len(T)} ore, Hs mediu {HS.mean():.2f} m, p90 {np.percentile(HS, 90):.2f} m")

# roza valurilor (pentru README / aplicatie)
rose = {}
for a in range(0, 360, 45):
    m = ((DIR - a + 22.5) % 360) < 45
    rose[f"{a}"] = {"pct": round(100 * m.mean(), 1), "hs_mean": round(float(HS[m].mean()), 2) if m.any() else None}
json.dump(rose, open(f"{OUTW}/wave_rose.json", "w"), indent=1)

# ------------------------------------------------------------- 2. sector deschis spre mare
wm_ds = gdal.Open(f"{ROOT}/outputs/water/water_mask.tif")
WGT = wm_ds.GetGeoTransform()
WM = wm_ds.ReadAsArray() == 1
src = osr.SpatialReference(); src.ImportFromEPSG(25831)
dst = osr.SpatialReference(); dst.ImportFromEPSG(32631)
for s_ in (src, dst):
    s_.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
TR = osr.CoordinateTransformation(src, dst)


def open_dirs(x, y, length=1500, step=6):
    X, Y, _ = TR.TransformPoint(x, y)
    res = []
    for az in range(0, 360, 5):
        dx, dy = math.sin(math.radians(az)), math.cos(math.radians(az))
        opened = True
        # primii ~40 m de langa perete sunt marcati uscat in masca Planet (adiacenta) -> sarim peste ei
        for s in range(40, length + 1, step):
            c = int((X + dx * s - WGT[0]) / WGT[1])
            r = int((WGT[3] - (Y + dy * s)) / -WGT[5])
            if not (0 <= r < WM.shape[0] and 0 <= c < WM.shape[1]):
                break                      # iese din imagine pe apa -> deschis
            if not WM[r, c]:
                opened = False
                break
        res.append(opened)
    return np.array(res)


AZ = np.arange(0, 360, 5)

# ------------------------------------------------------------- 3. statistici pe punct
gpkg = f"{ROOT}/outputs/spots/cliff_spots.gpkg"
ds = ogr.Open(gpkg, 1)
NEW = [("facing_deg", ogr.OFTReal), ("open_sector", ogr.OFTString), ("open_deg", ogr.OFTReal),
       ("waves_gt05_pct", ogr.OFTReal), ("waves_gt1_pct", ogr.OFTReal),
       ("summer_waves_gt05_pct", ogr.OFTReal), ("summer_calm_days_pct", ogr.OFTReal),
       ("exposure_txt", ogr.OFTString), ("open_mask", ogr.OFTString)]
spots_l = ds.GetLayer("spots")
jumps_l = ds.GetLayer("jumps")
for lyr in (spots_l, jumps_l):
    names = [lyr.GetLayerDefn().GetFieldDefn(i).GetName() for i in range(lyr.GetLayerDefn().GetFieldCount())]
    for n, t in NEW:
        if n not in names:
            lyr.CreateField(ogr.FieldDefn(n, t))

jumps = {f.GetFID(): f.GetGeometryRef().Clone() for f in jumps_l}
COMP = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSV", "SV", "VSV", "V", "VNV", "NV", "NNV"]


def compass(a):
    return COMP[int(((a % 360) + 11.25) // 22.5) % 16]


results = {}
MONTHLY = {}
for f in spots_l:
    g = jumps[f.GetFID()]
    x0, y0 = g.GetPoint_2D(0)
    x1, y1 = g.GetPoint_2D(1)
    facing = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360
    od = open_dirs(x1, y1)
    if not od.any():
        od = open_dirs(x1, y1, length=600)
    # valul efectiv: Hs * cos(dir_val - facing) daca directia din care vine valul e deschisa
    diff = np.radians(((DIR - facing + 180) % 360) - 180)
    idx = (np.round(DIR / 5).astype(int)) % 72
    eff = np.where(od[idx] & (np.abs(diff) < math.pi / 2), HS * np.cos(diff), 0.0)
    gt05 = 100 * (eff > 0.5).mean()
    gt1 = 100 * (eff > 1.0).mean()
    s05 = 100 * (eff[SUMMER] > 0.5).mean()
    # zile calme vara: maximul zilei < 0.5 m
    days = {}
    for d_, e_ in zip(DAY[SUMMER], eff[SUMMER]):
        days[d_] = max(days.get(d_, 0.0), e_)
    calm = 100 * np.mean([v < 0.5 for v in days.values()])
    # pe luni: % zile in care valul efectiv ramane < 0.5 m intre 09 si 19 (zi buna de sarit)
    monthly = {}
    for m in range(1, 13):
        sel = DAYTIME & (MONTH == m)
        dm = {}
        for d_, e_ in zip(DAY[sel], eff[sel]):
            dm[d_] = max(dm.get(d_, 0.0), e_)
        if dm:
            monthly[m] = {"calm_pct": round(100 * float(np.mean([v < 0.5 for v in dm.values()])), 0),
                          "rough_pct": round(100 * float(np.mean([v >= 1.0 for v in dm.values()])), 0),
                          "days": len(dm)}
    MONTHLY[f.GetFID()] = monthly
    open_az = AZ[od]
    sector = f"{compass(open_az.min())}-{compass(open_az.max())}" if open_az.size and open_az.size < 72 else ("toate" if open_az.size else "inchis")
    if open_az.size and open_az.size < 72:
        # sector continuu peste nord
        gaps = np.diff(np.concatenate([open_az, [open_az[0] + 360]]))
        k = int(np.argmax(gaps))
        start, end = open_az[(k + 1) % len(open_az)], open_az[k]
        sector = f"{compass(start)}-{compass(end)}"
    txt = ("adapostit" if s05 < 5 else "expunere moderata" if s05 < 20 else "expus la valuri")
    txt += f"; vara {calm:.0f}% din zile calme"
    vals = {"facing_deg": round(facing, 0), "open_sector": sector, "open_deg": float(5 * od.sum()),
            "waves_gt05_pct": round(gt05, 1), "waves_gt1_pct": round(gt1, 1),
            "summer_waves_gt05_pct": round(s05, 1), "summer_calm_days_pct": round(calm, 0),
            "exposure_txt": txt,
            # 72 caractere 0/1, cate unul la 5 grade (0 = N), folosit de aplicatie pentru prognoza live
            "open_mask": "".join("1" if o else "0" for o in od)}
    results[f.GetFID()] = vals
    for k_, v_ in vals.items():
        f.SetField(k_, v_)
    spots_l.SetFeature(f)

for f in jumps_l:
    for k_, v_ in results.get(f.GetFID(), {}).items():
        f.SetField(k_, v_)
    jumps_l.SetFeature(f)
ds = None
json.dump(MONTHLY, open(f"{OUTW}/wave_monthly_spots.json", "w"))

sv = np.array([v["summer_calm_days_pct"] for v in results.values()])
print(f"puncte: {len(results)}; zile calme vara (min/median/max): {sv.min():.0f}/{np.median(sv):.0f}/{sv.max():.0f}%")
print("roza (directia din care vin valurile):", {k: v["pct"] for k, v in rose.items()})

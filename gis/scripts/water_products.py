"""Produse de apa din PlanetScope SuperDove 8 benzi (SR) pentru CLAVADO.

Rulare (in consola Python din QGIS sau prin QGIS MCP execute_code):
    exec(open(QgsProject.instance().homePath() + "/scripts/water_products.py", encoding="utf-8").read())

Benzi SuperDove: 1 coastal blue 443, 2 blue 490, 3 green I 531, 4 green 565,
5 yellow 610, 6 red 665, 7 red edge 705, 8 NIR 865 nm. SR scalat x10000.

Produse (grila Planet 3 m, EPSG:32631), pentru fiecare data si compozit:
  water_mask      1 = apa (din scena 24 sept, 100% senin), folosita pentru toate datele
  dist_shore_m    distanta de la tarm (m)
  turbidity_FNU   Nechad et al. 2009 / 2010, banda rosie 665 nm, dupa deglint
  chl_mg_m3       OC3 (raport albastru/verde, coeficienti OC3M); valid doar in apa optic adanca
  ndci            Normalized Difference Chlorophyll Index (Mishra & Mishra 2012)
  float_algae     1 = vegetatie / alge plutitoare (NIR ridicat + NDVI > 0.2 pe apa)
  whitewater      1 = spuma / valuri care se sparg (reflectanta plata ridicata in NIR)
  psdb            adancime relativa Stumpf 2003 ln(1000*B)/ln(1000*G) (fara unitate, creste cu adancimea)
  bottom_class    0 uscat, 1 fund luminos vizibil (foarte putin adanc), 2 fund vizibil,
                  3 apa optic adanca (fundul nu se vede), 9 invalid (nori/spuma/lipsa date)
"""
import glob
import json
import os

import numpy as np
from osgeo import gdal, osr


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

PS = f"{_ROOT}/Mallorca_Coast_psscene_analytic_8b_sr_udm2/PSScene"
OUT = f"{_ROOT}/outputs/water"
os.makedirs(OUT, exist_ok=True)
NODATA = -9999.0


def read_scene(sid):
    sr = gdal.Open(f"{PS}/{sid}_3B_AnalyticMS_SR_8b_clip.tif")
    udm = gdal.Open(f"{PS}/{sid}_3B_udm2_clip.tif").ReadAsArray()
    a = sr.ReadAsArray().astype("float32") / 10000.0
    # nodata = toate benzile 0; apa in umbra stancilor poate avea NIR = 0 legitim
    have = (a > 0).any(0)
    # udm2: 0 clear, 2 shadow, 3 light haze, 4 heavy haze, 5 cloud
    clear = have & (udm[0] == 1) & (udm[2] == 0) & (udm[4] == 0) & (udm[5] == 0)
    return a, clear, sr.GetGeoTransform(), sr.GetProjection()


def write(name, arr, gt, wkt, dtype=gdal.GDT_Float32, nodata=NODATA):
    path = f"{OUT}/{name}.tif"
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, arr.shape[1], arr.shape[0], 1, dtype, ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    b.ComputeStatistics(False)
    ds = None
    return path


def distance_to_land(water, gt, wkt):
    """Distanta (m) de la fiecare pixel la cel mai apropiat pixel de uscat."""
    drv = gdal.GetDriverByName("MEM")
    src = drv.Create("", water.shape[1], water.shape[0], 1, gdal.GDT_Byte)
    src.SetGeoTransform(gt)
    src.SetProjection(wkt)
    src.GetRasterBand(1).WriteArray((~water).astype("uint8"))
    dst = drv.Create("", water.shape[1], water.shape[0], 1, gdal.GDT_Float32)
    dst.SetGeoTransform(gt)
    dst.SetProjection(wkt)
    gdal.ComputeProximity(src.GetRasterBand(1), dst.GetRasterBand(1), ["VALUES=1", "DISTUNITS=GEO"])
    return dst.GetRasterBand(1).ReadAsArray()


# ---------------------------------------------------------------- date / scene
DATES = {
    # 24 sept: doua scene din aceeasi trecere -> mozaic (prima are prioritate)
    "20260924": ["20260924_103622_94_2565", "20260924_103620_57_2565"],
    "20261014": ["20261014_103612_85_2570"],
    "20261022": ["20261022_104057_02_255b"],
}


def load_date(ids):
    a, clear, gt, wkt = read_scene(ids[0])
    for sid in ids[1:]:
        b, c2, _, _ = read_scene(sid)
        fill = ~clear & c2
        a[:, fill] = b[:, fill]
        clear |= c2
    return a, clear, gt, wkt


# ---------------------------------------------------------------- water mask
ref, ref_clear, GT, WKT = load_date(DATES["20260924"])
# In apa adanca SR are NIR ~0.012 > verde ~0.011, deci NDWI nu e fiabil aici.
# Apa = NIR mic si albastru-coastal peste NIR; apoi pastram doar componenta conexa a marii
# (elimina umbrele de faleza de pe uscat) si umplem gaurile mici (barci, spuma).
from scipy import ndimage

# Langa stanci apa primeste lumina reflectata de uscat (efect de adiacenta) si are NIR ~0.03,
# uneori peste albastru-coastal, deci folosim doar pragul NIR.
cand = ref_clear & (ref[7] < 0.06)
cand = ndimage.binary_opening(cand, iterations=1)
lab, nlab = ndimage.label(cand)
sizes = ndimage.sum(cand, lab, range(1, nlab + 1))
water = lab == (int(np.argmax(sizes)) + 1)
holes = ndimage.binary_fill_holes(water) & ~water
hlab, nh = ndimage.label(holes)
hsize = ndimage.sum(holes, hlab, range(1, nh + 1))
small = np.isin(hlab, np.nonzero(hsize < 200)[0] + 1)
water |= small
dist = distance_to_land(water, GT, WKT)
dist[~water] = 0
write("water_mask", water.astype("uint8"), GT, WKT, gdal.GDT_Byte, 255)
write("dist_shore_m", np.where(water, dist, NODATA).astype("float32"), GT, WKT)

# OC3M (NASA) coeficienti
OC3 = [0.2424, -2.7423, 1.8017, 0.0015, -1.2280]
# Nechad 2009 la 665 nm (A in FNU, C fara unitate, rho_w = pi*Rrs)
NECHAD_A, NECHAD_C = 228.1, 0.1641

stats = {}
products = {}
for date, ids in DATES.items():
    a, clear, gt, wkt = load_date(ids)
    w = water & clear
    nir_raw = a[7]

    # ---- 1. corectia de adiacenta (lumina reflectata de uscatul vecin), doar < 90 m de tarm
    # model de amestec liniar: rho = f * rho_uscat_local + (1 - f) * rho_apa,
    # f estimat din excesul NIR fata de apa curata (apa nu reflecta aproape deloc in NIR)
    landm = (~water & clear).astype("float32")
    wsum = ndimage.gaussian_filter(landm, 4)
    land_spec = np.stack([ndimage.gaussian_filter(a[i] * landm, 4) / np.maximum(wsum, 1e-6)
                          for i in range(8)])
    open_w = w & (dist > 300)
    nir_w = np.percentile(nir_raw[open_w], 20) if open_w.sum() > 500 else np.percentile(nir_raw[w], 5)
    near = w & (dist < 90) & (wsum > 1e-4)
    f = np.zeros(water.shape, "float32")
    f[near] = np.clip((nir_raw[near] - nir_w) / np.maximum(land_spec[7][near] - nir_w, 0.05), 0, 0.9)
    a = np.where(near[None], (a - f[None] * land_spec) / (1 - f[None]), a)
    adjacency_bad = w & (f > 0.5)
    nir = a[7]

    # ---- 2. spuma / valuri si alge plutitoare (pe spectrul corectat)
    ndvi = (nir - a[5]) / (np.abs(nir) + np.abs(a[5]) + 1e-9)
    whitewater = w & ~adjacency_bad & (nir > nir_w + 0.035) & (ndvi < 0.15)
    # alge / vegetatie plutitoare: NIR peste linia de baza a apei din aceeasi scena
    # (robust la sclipirea soarelui, care ridica toata scena) + NDVI clar pozitiv
    nir_base = np.percentile(nir[open_w], 95) if open_w.sum() > 500 else np.percentile(nir[w], 95)
    float_algae = w & ~adjacency_bad & (nir > nir_base + 0.015) & (ndvi > 0.25)

    # ---- 3. deglint Hedley et al. 2005 pe apa adanca, departe de tarm (> 600 m)
    deep = w & (dist > 600) & ~whitewater & ~float_algae
    if deep.sum() < 500:
        deep = w & (dist > 300) & ~whitewater & ~float_algae
    nir_min = np.percentile(nir[deep], 1)
    slopes = []
    d = a.copy()
    for i in range(7):
        x, y = nir[deep], a[i][deep]
        s = np.polyfit(x, y, 1)[0] if x.std() > 1e-5 else 0.0
        s = float(np.clip(s, 0, 1.2))
        slopes.append(s)
        d[i] = a[i] - s * (np.maximum(nir, nir_min) - nir_min)
    good = w & ~whitewater & ~float_algae & ~adjacency_bad

    # turbiditate (FNU)
    rho_r = np.clip(d[5], 1e-5, NECHAD_C * 0.95)
    turb = NECHAD_A * rho_r / (1 - rho_r / NECHAD_C)

    # clorofila OC3
    ratio = np.maximum(d[0], d[1]) / np.clip(d[3], 1e-5, None)
    r = np.log10(np.clip(ratio, 1e-3, None))
    chl = 10 ** (OC3[0] + OC3[1] * r + OC3[2] * r ** 2 + OC3[3] * r ** 3 + OC3[4] * r ** 4)

    ndci = (d[6] - d[5]) / (d[6] + d[5] + 1e-9)

    # adancime relativa Stumpf (albastru / verde)
    psdb = np.log(1000 * np.clip(d[1], 1e-4, None)) / np.log(1000 * np.clip(d[3], 1e-4, None))

    # vizibilitatea fundului: semnalul verde fata de linia de baza a apei optic adanci.
    # Fund luminos (nisip) -> verde peste baza; fund intunecat (stanca cu alge, Posidonia) -> sub baza.
    g_deep = d[3][deep]
    g_inf = float(np.percentile(g_deep, 50))
    g_thr_visible = np.percentile(g_deep, 99) + 0.002
    g_thr_bright = g_inf + 0.02
    g_thr_dark = np.percentile(g_deep, 1) - 0.002
    psdb_deep = np.percentile(psdb[deep], 50)
    bclass = np.full(water.shape, 9, "uint8")
    bclass[~water] = 0
    bclass[good] = 3
    bclass[good & (d[3] > g_thr_visible)] = 2
    bclass[good & (d[3] > g_thr_bright)] = 1
    bclass[good & (d[3] < g_thr_dark)] = 4
    # primul pixel de langa uscat ramane amestecat chiar si dupa corectie
    bclass[water & (dist < 4)] = 9

    # adancime aproximativa presupunand fund de nisip (Lyzenga 1978, o banda, verde 565 nm):
    #   z = ln((A_b - rho_inf) / (rho - rho_inf)) / g
    # A_b = reflectanta nisipului la adancime ~0 (p99.5 din apa cu fund luminos din scena),
    # g = 0.15 1/m (atenuare dus-intors in apa oligotrofa limpede, ~2 x Kd(565) ~ 0.07).
    # Peste fund intunecat estimarea ar fi prea MARE (nesigur), deci se calculeaza doar pentru
    # fund luminos/vizibil. Eroare tipica +-50%.
    G_ATT = 0.15
    bright_px = d[3][good & (d[3] > g_thr_visible)]
    # limitat la 0.08-0.15 (nisip carbonatic, pi*Rrs la 565 nm): un A_b prea mare ar supraestima adancimea
    A_b = float(np.clip(np.percentile(bright_px, 99.5) if bright_px.size > 50 else 0.10, 0.08, 0.15))
    A_b = max(A_b, g_inf + 0.04)
    with np.errstate(all="ignore"):
        sdb = np.log((A_b - g_inf) / np.clip(d[3] - g_inf, 1e-4, None)) / G_ATT
    sdb = np.clip(sdb, 0, 25)
    sdb_out = np.where(good & ((bclass == 1) | (bclass == 2)), sdb, NODATA)

    out = {
        "turbidity_FNU": np.where(good, turb, NODATA),
        "chl_mg_m3": np.where(good, chl, NODATA),
        "ndci": np.where(good, ndci, NODATA),
        "psdb": np.where(good, psdb, NODATA),
        "sdb_sand_m": sdb_out,
    }
    write(f"adjacency_frac_{date}", np.where(w, f, NODATA).astype("float32"), gt, wkt)
    # reflectanta corectata (adiacenta + deglint) benzile 1-4, pentru calibrarea cu ICESat-2
    rc = gdal.GetDriverByName("GTiff").Create(f"{OUT}/rho_corr_{date}.tif", water.shape[1], water.shape[0], 4,
                                              gdal.GDT_Float32, ["COMPRESS=DEFLATE", "TILED=YES"])
    rc.SetGeoTransform(gt)
    rc.SetProjection(wkt)
    for i in range(4):
        b = rc.GetRasterBand(i + 1)
        b.SetNoDataValue(NODATA)
        b.WriteArray(np.where(good, d[i], NODATA).astype("float32"))
        b.SetDescription(["coastal_blue", "blue", "green_i", "green"][i])
    rc = None
    stats.setdefault("_baselines", {})[date] = {
        "rho_inf": [float(np.percentile(d[i][deep], 50)) for i in range(4)]}
    for k, v in out.items():
        write(f"{k}_{date}", v.astype("float32"), gt, wkt)
    write(f"bottom_class_{date}", bclass, gt, wkt, gdal.GDT_Byte, 255)
    write(f"whitewater_{date}", np.where(w, whitewater, 255).astype("uint8"), gt, wkt, gdal.GDT_Byte, 255)
    write(f"float_algae_{date}", np.where(w, float_algae, 255).astype("uint8"), gt, wkt, gdal.GDT_Byte, 255)
    products[date] = dict(out, bottom_class=bclass, whitewater=np.where(w, whitewater, 255),
                          float_algae=np.where(w, float_algae, 255), good=good)

    def q(v):
        return [round(float(x), 3) for x in np.percentile(v[good], [5, 50, 95])] if good.any() else None

    stats[date] = {
        "water_px_valid": int(good.sum()),
        "water_valid_pct": round(100 * good.sum() / max(water.sum(), 1), 1),
        "deglint_slopes": [round(s, 3) for s in slopes],
        "turbidity_FNU_p5_50_95": q(turb),
        "chl_mg_m3_p5_50_95": q(chl),
        "ndci_p5_50_95": q(ndci),
        "whitewater_px": int(whitewater.sum()),
        "float_algae_px": int(float_algae.sum()),
        "bottom_bright_px": int((bclass == 1).sum()),
        "bottom_visible_px": int((bclass == 2).sum()),
        "optically_deep_px": int((bclass == 3).sum()),
        "psdb_deep_median": round(float(psdb_deep), 3),
        "dark_bottom_px": int((bclass == 4).sum()),
        "adjacency_bad_px": int(adjacency_bad.sum()),
        "green_deep_baseline": round(g_inf, 4),
        "sand_A_b": round(A_b, 4),
        "sdb_sand_m_p5_50_95": [round(float(x), 1) for x in np.percentile(sdb[sdb_out != NODATA], [5, 50, 95])] if (sdb_out != NODATA).any() else None,
    }

# ---------------------------------------------------------------- compozit multi-data
for key in ["turbidity_FNU", "chl_mg_m3", "ndci", "psdb"]:
    stack = np.stack([np.where(p[key] == NODATA, np.nan, p[key]) for p in products.values()])
    n = np.isfinite(stack).sum(0)
    with np.errstate(all="ignore"):
        med = np.nanmedian(stack, 0)
        rng = np.nanmax(stack, 0) - np.nanmin(stack, 0)
    write(f"{key}_median", np.where(n > 0, med, NODATA).astype("float32"), GT, WKT)
    if key == "turbidity_FNU":
        write(f"{key}_range", np.where(n > 1, rng, NODATA).astype("float32"), GT, WKT)

# adancime aproximativa: minimul pe date (conservator)
st = np.stack([np.where(p["sdb_sand_m"] == NODATA, np.nan, p["sdb_sand_m"]) for p in products.values()])
with np.errstate(all="ignore"):
    sdb_min = np.nanmin(st, 0)
write("sdb_sand_m_min", np.where(np.isfinite(sdb_min), sdb_min, NODATA).astype("float32"), GT, WKT)

# clasa fundului: cea mai conservatoare observata in datele valide
# ordinea de risc: 1 luminos/putin adanc > 2 fund vizibil > 4 fund intunecat vizibil > 3 optic adanc
RANK = {1: 0, 2: 1, 4: 2, 3: 3}
INV = {v: k for k, v in RANK.items()}
bc = np.stack([p["bottom_class"] for p in products.values()]).astype("int16")
rk = np.full(bc.shape, 99, "int16")
for k, v in RANK.items():
    rk[bc == k] = v
rmin = rk.min(0)
bmin = np.zeros(water.shape, "uint8")
for v, k in INV.items():
    bmin[rmin == v] = k
bottom_cons = np.where(~water, 0, np.where(rmin == 99, 9, bmin)).astype("uint8")
write("bottom_class_conservative", bottom_cons, GT, WKT, gdal.GDT_Byte, 255)

# frecventa spumei / valurilor si a algelor plutitoare (fractie din datele valide)
for key in ["whitewater", "float_algae"]:
    st = np.stack([p[key] for p in products.values()]).astype("float32")
    valid = st != 255
    freq = np.where(valid.sum(0) > 0, (st * valid).sum(0) / np.maximum(valid.sum(0), 1), NODATA)
    freq[~water] = NODATA
    write(f"{key}_freq", freq.astype("float32"), GT, WKT)

json.dump(stats, open(f"{OUT}/water_stats.json", "w"), indent=2)
print(json.dumps(stats, indent=1))

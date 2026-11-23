"""Calibrarea adancimii din Planet (SDB) cu batimetria laser ICESat-2 ATL24.

Rulare in QGIS (dupa water_products.py si fetch_icesat2_atl24.py + exportul CSV):
    exec(open(QgsProject.instance().homePath() + "/scripts/calibrate_sdb.py", encoding="utf-8").read())

Modele testate pe fiecare data Planet (pe pixeli de 3 m, mediana fotonilor din pixel):
  stumpf   z = m1 * ln(1000*B)/ln(1000*G) + m0                     (Stumpf et al. 2003)
  lyzenga  z = a0 + sum_i a_i * ln(rho_i - rho_inf_i), i = albastru, verde I, verde  (Lyzenga 2006)
Validare: leave-one-track-out (o trecere ICESat-2 intreaga lasata deoparte pe rand).
Modelul ales se aplica pe toata scena -> water/sdb_cal_<data>.tif si sdb_cal_min.tif
(minimul pe date, conservator), plus sdb_cal_uncert.tif (eroarea tipica pe intervale de adancime).
"""
import csv
import json

import numpy as np
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

W = f"{_ROOT}/outputs/water"
I2 = f"{_ROOT}/outputs/icesat2"
NODATA = -9999.0
DATES = ["20260924", "20261014", "20261022"]
CONF_MIN = 0.75
Z_MAX_FIT = 25.0   # peste ~20-25 m fundul nu mai e vizibil -> nu calibram acolo

stats = json.load(open(f"{W}/water_stats.json"))
base = stats["_baselines"]

# ---------------------------------------------------------------- fotoni -> pixeli
rows = list(csv.DictReader(open(f"{I2}/atl24_photons_utm31n.csv")))
px = np.array([float(r["x"]) for r in rows])
py = np.array([float(r["y"]) for r in rows])
pz = np.array([float(r["depth"]) if r["depth"] else np.nan for r in rows])
pconf = np.array([float(r["confidence"]) for r in rows])
pq = np.array([int(float(r["quality_ph"])) for r in rows])
ptrk = np.array([r["track"] for r in rows])

ref = gdal.Open(f"{W}/water_mask.tif")
GT, WKT = ref.GetGeoTransform(), ref.GetProjection()
WM = ref.ReadAsArray()
H, Wd = WM.shape
DIST = gdal.Open(f"{W}/dist_shore_m.tif").ReadAsArray()
pc = np.floor((px - GT[0]) / GT[1]).astype(int)
pr = np.floor((GT[3] - py) / -GT[5]).astype(int)
ok = (pc >= 0) & (pc < Wd) & (pr >= 0) & (pr < H) & np.isfinite(pz) & (pq == 0) & (pconf >= CONF_MIN)
ok &= WM[pr.clip(0, H - 1), pc.clip(0, Wd - 1)] == 1
ok &= (pz > 0.3) & (pz < 45)

# un esantion = (pixel, trecere): mediana fotonilor
keys = {}
for i in np.nonzero(ok)[0]:
    keys.setdefault((pr[i], pc[i], ptrk[i]), []).append(pz[i])
S_r = np.array([k[0] for k in keys])
S_c = np.array([k[1] for k in keys])
S_t = np.array([k[2] for k in keys])
S_z = np.array([np.median(v) for v in keys.values()])
S_n = np.array([len(v) for v in keys.values()])
print(f"fotoni folositi: {ok.sum()}, esantioane pixel x trecere: {len(S_z)}, treceri: {len(set(S_t))}")


KINDS = ("stumpf", "stumpf2", "lyzenga")


def features(rho, rinf, kind):
    if kind in ("stumpf", "stumpf2"):
        b, g = np.clip(rho[1], 1e-4, None), np.clip(rho[3], 1e-4, None)
        s = np.log(1000 * b) / np.log(1000 * g)
        return s[..., None] if kind == "stumpf" else np.stack([s, s ** 2], -1)
    X = [np.log(np.clip(rho[i] - rinf[i], 1e-4, None)) for i in (1, 2, 3)]
    return np.stack(X, -1)


def bin_weights(z):
    """Ponderi egale pe intervale de 5 m: altfel pixelii de 15-20 m (majoritari) domina
    si modelul supraestimeaza adancimea in apa putin adanca (directia periculoasa)."""
    b = np.minimum((z // 5).astype(int), 4)
    cnt = np.bincount(b, minlength=5).astype(float)
    return 1.0 / cnt[b]


def fit(X, z):
    w = np.sqrt(bin_weights(z))
    A = np.column_stack([X, np.ones(len(z))])
    coef, *_ = np.linalg.lstsq(A * w[:, None], z * w, rcond=None)
    return coef


def predict(X, coef):
    return X @ coef[:-1] + coef[-1]


report = {}
models = {}
for date in DATES:
    ds = gdal.Open(f"{W}/rho_corr_{date}.tif")
    rho = ds.ReadAsArray().astype("float64")
    valid = (rho[0] != NODATA)
    rinf = base[date]["rho_inf"]
    bc = gdal.Open(f"{W}/bottom_class_{date}.tif").ReadAsArray()
    # calibram doar unde fundul se vede (clasele 1-2), exact unde aplicam modelul
    m = valid[S_r, S_c] & (S_z <= Z_MAX_FIT) & np.isin(bc[S_r, S_c], [1, 2])
    if m.sum() < 30:
        print(date, "prea putine esantioane:", m.sum())
        continue
    r_, c_, z_, t_ = S_r[m], S_c[m], S_z[m], S_t[m]
    res = {}
    for kind in KINDS:
        Xall = features(rho[:, r_, c_], rinf, kind)
        pred = np.full(len(z_), np.nan)
        for trk in set(t_):  # leave-one-track-out
            tr = t_ != trk
            if tr.sum() < 20:
                continue
            pred[~tr] = predict(Xall[~tr], fit(Xall[tr], z_[tr]))
        e = pred - z_
        f = np.isfinite(e)
        bins = {}
        for lo, hi in [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25)]:
            bm = f & (z_ >= lo) & (z_ < hi)
            if bm.sum() >= 5:
                bins[f"{lo}-{hi}"] = {"n": int(bm.sum()), "rmse": round(float(np.sqrt(np.mean(e[bm] ** 2))), 2),
                                      "bias": round(float(np.mean(e[bm])), 2)}
        coef = fit(Xall, z_)
        res[kind] = {
            "n": int(f.sum()),
            "rmse_cv": round(float(np.sqrt(np.mean(e[f] ** 2))), 2),
            "mae_cv": round(float(np.mean(np.abs(e[f]))), 2),
            "bias_cv": round(float(np.mean(e[f])), 2),
            "r2_cv": round(float(1 - np.sum(e[f] ** 2) / np.sum((z_[f] - z_[f].mean()) ** 2)), 3),
            "by_depth": bins,
            "coef": [round(float(v), 4) for v in coef],
        }
    # alegem modelul cu cea mai mica eroare in apa < 10 m (relevanta pentru siguranta),
    # penalizand supraestimarea (bias pozitiv = mai adanc decat in realitate)
    def shallow_score(rr):
        bs = [rr["by_depth"][k] for k in ("0-5", "5-10") if k in rr["by_depth"]]
        if not bs:
            return rr["rmse_cv"]
        return np.mean([b["rmse"] + max(b["bias"], 0) for b in bs]) + 0.5 * rr["rmse_cv"]
    best = min(res, key=lambda k: shallow_score(res[k]))
    # incertitudinea in apa < 10 m (RMSE comasat), folosita pentru adancimea conservatoare
    bs = [res[best]["by_depth"][k] for k in ("0-5", "5-10") if k in res[best]["by_depth"]]
    u_shallow = float(np.sqrt(sum(b["n"] * b["rmse"] ** 2 for b in bs) / sum(b["n"] for b in bs))) if bs \
        else res[best]["rmse_cv"]
    report[date] = {"best": best, "u_shallow_m": round(u_shallow, 2), **res}
    models[date] = (best, np.array(res[best]["coef"]), rinf, u_shallow)
    print(date, "->", best, {k: (v["rmse_cv"], v["r2_cv"], v["n"]) for k, v in res.items()})


def write(name, arr):
    out = gdal.GetDriverByName("GTiff").Create(f"{W}/{name}.tif", Wd, H, 1, gdal.GDT_Float32,
                                               ["COMPRESS=DEFLATE", "TILED=YES"])
    out.SetGeoTransform(GT)
    out.SetProjection(WKT)
    b = out.GetRasterBand(1)
    b.SetNoDataValue(NODATA)
    b.WriteArray(arr.astype("float32"))
    b.ComputeStatistics(False)
    out = None


# ---------------------------------------------------------------- aplicare pe toata scena
# fund optic adanc (clasa 3) -> nu se poate citi adancimea; validarea arata ca e > ~18 m
OPT_DEEP_MIN = None
stack = []
stack_safe = []
for date, (kind, coef, rinf, u) in models.items():
    rho = gdal.Open(f"{W}/rho_corr_{date}.tif").ReadAsArray().astype("float64")
    valid = rho[0] != NODATA
    bc = gdal.Open(f"{W}/bottom_class_{date}.tif").ReadAsArray()
    X = features(rho, rinf, kind)
    z = np.clip(predict(X.reshape(-1, X.shape[-1]), coef).reshape(H, Wd), 0, Z_MAX_FIT)
    usable = valid & np.isin(bc, [1, 2])          # fund vizibil luminos -> adancime calibrata
    out = np.where(usable, z, NODATA)
    write(f"sdb_cal_{date}", out)
    stack.append(np.where(usable, z, np.nan))
    stack_safe.append(np.where(usable, np.clip(z - u, 0, None), np.nan))

with np.errstate(all="ignore"):
    zmin = np.nanmin(np.stack(stack), 0)
    zsafe = np.nanmin(np.stack(stack_safe), 0)
write("sdb_cal_min", np.where(np.isfinite(zmin), zmin, NODATA))
# adancimea conservatoare: minimul pe date al (estimare - eroarea tipica in apa < 10 m)
write("sdb_cal_safe", np.where(np.isfinite(zsafe), zsafe, NODATA))

# adancimea minima a apei optic adanci, din ICESat-2 (percentila 5)
bc0 = gdal.Open(f"{W}/bottom_class_conservative.tif").ReadAsArray()
deep_z = S_z[bc0[S_r, S_c] == 3]
dark_z = S_z[bc0[S_r, S_c] == 4]
report["optically_deep_icesat2_depth_p5_p50"] = [round(float(np.percentile(deep_z, p)), 1) for p in (5, 50)] if deep_z.size else None
report["dark_bottom_icesat2_depth_p5_p50"] = [round(float(np.percentile(dark_z, p)), 1) for p in (5, 50)] if dark_z.size else None
report["samples"] = int(len(S_z))
report["tracks"] = sorted(set(S_t.tolist()))
json.dump(report, open(f"{I2}/calibration_report.json", "w"), indent=2)
print(json.dumps({k: v for k, v in report.items() if k != "tracks"}, indent=1))

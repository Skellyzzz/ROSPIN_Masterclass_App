"""Datele 3D ale aplicatiei web, stocate O SINGURA DATA in dale de 50 m (in loc de cate un decupaj per punct).

Rulare (mediul virtual: laspy[lazrs], rasterio, scipy, pillow, geopandas):
    .venv-icesat2/Scripts/python scripts/export_tiles.py   (din folderul proiectului)

Grila: dale de TILE m aliniate la EPSG:25831 (cheia "ix_iy" = floor(E/TILE)_floor(N/TILE)); se exporta doar dalele
atinse de macheta (cercul) vreunui punct. Pentru fiecare dala, in outputs/webapp/tiles/:
  <k>.h      cote int16 (unitate 2 cm), (TILE+1) x (TILE+1) varfuri la 1 m, randul 0 = nord, marginile comune
             cu dalele vecine. Uscat = suprafata LiDAR (cota maxima pe celula), mare = fundul estimat din satelit
             (sdb_cal_safe, conservator, ICESat-2), unde nu se vede -> 18 m
  <k>.jpg    ortofoto PNOA 25 cm pentru exact aceeasi extindere (TEX x TEX px)
  <k>.p0     puncte LiDAR rare (unul pe voxel de 1 m): int16 x3 (2 cm, fata de centrul dalei), RGB u8 x3,
             normala i8 x3, raza fina u8, raza rara u8 (2 cm)  -> 14 octeti/punct; se descarca pentru toata macheta
  <k>.p1     restul punctelor (detaliu): int16 x3, RGB u8 x3, normala i8 x3, raza fina u8 -> 13 octeti/punct;
             se descarca doar pentru dalele de langa saritura
  index.json  marimea dalei, unitati, numarul de puncte pe dala
  spots.json  pentru fiecare punct: originea (desprinderea, E/N), cota desprinderii, intrarea, traseul de inot,
              iesirea si cercul machetei (coordonate locale, m fata de desprindere)
Normalele (PCA pe 10 vecini) si razele discurilor se calculeaza cu o margine de 3 m in jurul dalei, ca sa nu apara
cusaturi la marginea dalelor.
"""
import io
import json
import os
import shutil

import geopandas as gpd
import laspy
import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from scipy import ndimage
from scipy.spatial import cKDTree


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
OUT = f"{ROOT}/outputs/webapp/tiles"
LAZ = [f"{ROOT}/PNOA_2024_BAL_525-4372_H31_NPC03.laz", f"{ROOT}/PNOA_2024_BAL_525-4373_H31_NPC03.laz"]
LID_B = (525000, 4371000, 526000, 4373000)
TILE, TEX, UNIT, BUF, VOX0 = 50, 200, 0.02, 3.0, 1.0
R_MIN, R_MAX, R_PAD = 45.0, 190.0, 16.0          # macheta: raza minima / maxima / margine in jurul scenei
DEEP = 18.0

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

# ------------------------------------------------------------------ puncte LiDAR curatate
dtm_ds = rasterio.open(f"{ROOT}/outputs/lidar/dtm_1m.tif")
DTM = dtm_ds.read(1)
xs, ys, zs, cs, cl = [], [], [], [], []
for f in LAZ:
    las = laspy.read(f)
    c = np.asarray(las.classification)
    z = np.asarray(las.z)
    m = np.isin(c, [1, 2, 3, 4, 5, 6]) | ((c == 12) & (z >= 0.5))   # clasa 12 (suprapunere) doar peste apa
    xs.append(np.asarray(las.x)[m]); ys.append(np.asarray(las.y)[m]); zs.append(z[m]); cl.append(c[m])
    cs.append((np.stack([np.asarray(las.red)[m], np.asarray(las.green)[m], np.asarray(las.blue)[m]], 1) >> 8).astype("u1"))
X, Y, Z = (np.concatenate(a) for a in (xs, ys, zs))
RGB, CL = np.concatenate(cs), np.concatenate(cl)
r_, c_ = rasterio.transform.rowcol(dtm_ds.transform, X, Y)
r_ = np.clip(np.asarray(r_), 0, DTM.shape[0] - 1); c_ = np.clip(np.asarray(c_), 0, DTM.shape[1] - 1)
ref = np.where(DTM[r_, c_] > -1000, DTM[r_, c_], 0.0)
ok = (Z <= ref + 20) & (RGB.astype("i4").sum(1) >= 40)   # aberante (pasari, zgomot) si puncte fara culoare
X, Y, Z, RGB, CL = X[ok], Y[ok], Z[ok], RGB[ok], CL[ok]
o = np.argsort(X)
X, Y, Z, RGB, CL = X[o], Y[o], Z[o], RGB[o], CL[o]
print(f"puncte: {len(X):,}", flush=True)


def window(x0, x1, y0, y1):
    i0, i1 = np.searchsorted(X, x0), np.searchsorted(X, x1)
    idx = np.arange(i0, i1)
    return idx[(Y[idx] >= y0) & (Y[idx] < y1)]


# ------------------------------------------------------------------ punctele de saritura si machetele
gp = f"{ROOT}/outputs/spots/cliff_spots.gpkg"
spots_l = gpd.read_file(gp, layer="spots")
jumps_l = gpd.read_file(gp, layer="jumps")
swim_l = gpd.read_file(gp, layer="swim").set_index("spot_fid")
spots = {}
for i in range(len(spots_l)):
    fid = i + 1
    (tx, ty), (lx, ly) = list(jumps_l.geometry.iloc[i].coords)[:2]
    route = list(swim_l.loc[fid].geometry.coords) if fid in swim_l.index else []
    allx = np.array([tx, lx] + [p[0] for p in route]); ally = np.array([ty, ly] + [p[1] for p in route])
    ccx, ccy = (allx.min() + allx.max()) / 2, (ally.min() + ally.max()) / 2
    cr = max(float(np.hypot(allx - ccx, ally - ccy).max()) + R_PAD, R_MIN)
    if cr > R_MIN:
        cr = min(cr, R_MAX, ccx - LID_B[0], LID_B[2] - ccx, ccy - LID_B[1], LID_B[3] - ccy)
    g0 = window(tx - 1.5, tx + 1.5, ty - 1.5, ty + 1.5)
    g0 = g0[(CL[g0] == 2) & (np.hypot(X[g0] - tx, Y[g0] - ty) <= 1.5)]
    hz = float(np.median(Z[g0])) if g0.size >= 3 else float(spots_l.iloc[i]["height_m"])
    loc = lambda x, y: [round(x - tx, 2), round(y - ty, 2)]   # noqa: E731
    spots[fid] = {"origin": [round(tx, 2), round(ty, 2)], "takeoff": [0.0, 0.0, round(hz, 2)],
                  "entry": loc(lx, ly) + [0.0], "swim": [loc(x, y) for x, y in route],
                  "exit": loc(*route[-1]) if route else None,
                  "circle": [round(ccx - tx, 2), round(ccy - ty, 2), round(cr, 2)]}
json.dump(spots, open(f"{OUT}/spots.json", "w"))

# dalele atinse de vreun cerc
need = set()
for s in spots.values():
    cx, cy, r = s["circle"][0] + s["origin"][0], s["circle"][1] + s["origin"][1], s["circle"][2]
    for ix in range(int((cx - r) // TILE), int((cx + r) // TILE) + 1):
        for iy in range(int((cy - r) // TILE), int((cy + r) // TILE) + 1):
            ex, ey = ix * TILE, iy * TILE
            if ex < LID_B[0] or ey < LID_B[1] or ex + TILE > LID_B[2] or ey + TILE > LID_B[3]:
                continue
            dx = max(ex - cx, 0, cx - (ex + TILE)); dy = max(ey - cy, 0, cy - (ey + TILE))
            if dx * dx + dy * dy <= r * r:
                need.add((ix, iy))
print(f"dale necesare: {len(need)}", flush=True)

# ------------------------------------------------------------------ grila globala de cote (1 m) pe zona LiDAR
NX, NY = LID_B[2] - LID_B[0] + 1, LID_B[3] - LID_B[1] + 1        # varfuri la fiecare metru, randul 0 = nord
tr_v = rasterio.transform.from_origin(LID_B[0] - 0.5, LID_B[3] + 0.5, 1.0, 1.0)


def warp(path, resampling, dtype="float32", fill=np.nan):
    dst = np.full((NY, NX), fill, dtype)
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), dst, dst_transform=tr_v, dst_crs="EPSG:25831", dst_nodata=fill,
                  resampling=resampling)
    return dst


col = np.clip(np.round(X - LID_B[0]).astype(int), 0, NX - 1)
row = np.clip(np.round(LID_B[3] - Y).astype(int), 0, NY - 1)
dsm = np.full(NY * NX, -np.inf, "float32")
np.maximum.at(dsm, row * NX + col, Z.astype("float32"))
dsm = dsm.reshape(NY, NX)
has = np.isfinite(dsm)
sea = warp(f"{ROOT}/outputs/lidar/sea_mask_1m.tif", Resampling.nearest, "uint8", 255) == 1
isl = has & sea                                  # "insule" mici si joase in mare (stropi, barci) -> mare
lab, nl = ndimage.label(isl, structure=np.ones((3, 3)))
if nl:
    ids = np.arange(1, nl + 1)
    sz = ndimage.sum(isl, lab, ids)
    zmax = ndimage.maximum(np.where(isl, dsm, -1e9), lab, ids)
    has &= ~np.isin(lab, ids[(sz < 4.0) | (zmax < 0.8)])
land = has | ~sea
dtm_v = warp(f"{ROOT}/outputs/lidar/dtm_1m.tif", Resampling.bilinear)
surf = np.where(has, dsm, np.where(np.isfinite(dtm_v) & (dtm_v > -1000), dtm_v, 0.3))
surf = np.where(has, surf, ndimage.uniform_filter(surf, 3))
med = ndimage.median_filter(surf, 3)
surf = np.where(surf - med > 2.5, med, surf)     # varfuri izolate
d = warp(f"{ROOT}/outputs/water/sdb_cal_safe.tif", Resampling.bilinear)
d[d < -1000] = np.nan
valid = np.isfinite(d)
dist, (ri, ci) = ndimage.distance_transform_edt(~valid, return_indices=True)
d = np.where(valid, d, np.where(dist <= 30, d[ri, ci], DEEP))
d = ndimage.gaussian_filter(np.clip(d, 0.5, 30), 2.0)
ZZ = np.where(land, surf, -d).astype("float32")
print("cote: gata", flush=True)

# ------------------------------------------------------------------ dalele
ortho = rasterio.open(f"{ROOT}/outputs/ortho/pnoa_ortho_25cm.tif")


def surfels(P, k=10):
    """Normala (PCA pe k vecini, orientata in sus) si raza (~0.9 x distanta medie la 6 vecini) pentru fiecare punct."""
    tree = cKDTree(P)
    dd, nn = tree.query(P, k=min(k, len(P)))
    rad = np.clip(dd[:, 1:7].mean(1) * 0.9, 0.12, 0.9)
    nb = P[nn] - P[nn].mean(1, keepdims=True)
    _, vec = np.linalg.eigh(np.einsum("nki,nkj->nij", nb, nb))
    nrm = vec[:, :, 0]
    nrm[nrm[:, 2] < 0] *= -1
    return nrm, rad


q16 = lambda a: np.clip(np.round(a / UNIT), -32767, 32767).astype("<i2")   # noqa: E731
q8n = lambda a: np.clip(np.round(a * 127), -127, 127).astype("i1")          # noqa: E731
q8r = lambda a: np.clip(np.round(a / UNIT), 1, 255).astype("u1")            # noqa: E731
tiles = {}
sizes = []
for (ix, iy) in sorted(need):
    k = f"{ix}_{iy}"
    E0, N0 = ix * TILE, iy * TILE
    # cote: varfurile [E0, E0+TILE] x [N0, N0+TILE]
    r0, c0 = LID_B[3] - (N0 + TILE), E0 - LID_B[0]
    open(f"{OUT}/{k}.h", "wb").write(q16(ZZ[r0:r0 + TILE + 1, c0:c0 + TILE + 1]).tobytes())
    # textura
    rgb = ortho.read(window=from_bounds(E0, N0, E0 + TILE, N0 + TILE, ortho.transform), out_shape=(3, TEX, TEX),
                     resampling=Resampling.bilinear, boundless=True, fill_value=0)
    b = io.BytesIO()
    Image.fromarray(np.moveaxis(rgb, 0, -1)).save(b, "JPEG", quality=80, optimize=True)
    open(f"{OUT}/{k}.jpg", "wb").write(b.getvalue())
    # puncte: dala + margine (pentru vecini), fara puncte joase izolate
    wi = window(E0 - BUF, E0 + TILE + BUF, N0 - BUF, N0 + TILE + BUF)
    if wi.size < 20:
        tiles[k] = [0, 0]
        continue
    P = np.stack([X[wi], Y[wi], Z[wi]], 1)
    dd4, _ = cKDTree(P).query(P, k=4)
    keep = ~((P[:, 2] < 1.5) & (dd4[:, 1:].mean(1) > 1.2))
    wi, P = wi[keep], P[keep]
    nrm, rad = surfels(P)
    inside = (P[:, 0] >= E0) & (P[:, 0] < E0 + TILE) & (P[:, 1] >= N0) & (P[:, 1] < N0 + TILE)
    # nivelul rar: primul punct din fiecare voxel global de 1 m (acelasi indiferent de dala)
    vk = np.floor(P / VOX0).astype(np.int64)
    _, first = np.unique(vk, axis=0, return_index=True)
    is0 = np.zeros(len(P), bool); is0[first] = True
    _, rad0 = surfels(P[is0]) if is0.sum() >= 10 else (None, np.full(is0.sum(), 0.9))
    rad_c = np.zeros(len(P)); rad_c[is0] = np.clip(rad0 * 1.0, 0.3, 1.6)
    ctr = np.array([E0 + TILE / 2, N0 + TILE / 2, 0.0])
    for name, sel, coarse in (("p0", inside & is0, True), ("p1", inside & ~is0, False)):
        with open(f"{OUT}/{k}.{name}", "wb") as fh:
            fh.write(q16(P[sel] - ctr).tobytes()); fh.write(RGB[wi[sel]].tobytes())
            fh.write(q8n(nrm[sel]).tobytes()); fh.write(q8r(rad[sel]).tobytes())
            if coarse:
                fh.write(q8r(rad_c[sel]).tobytes())
    tiles[k] = [int((inside & is0).sum()), int((inside & ~is0).sum())]

json.dump({"tile": TILE, "unit": UNIT, "hres": 1, "tex_px": TEX, "bounds": LID_B, "tiles": tiles},
          open(f"{OUT}/index.json", "w"))
tot = sum(os.path.getsize(f"{OUT}/{f}") for f in os.listdir(OUT))
p1 = sum(os.path.getsize(f"{OUT}/{f}") for f in os.listdir(OUT) if f.endswith(".p1"))
print(f"dale: {len(tiles)}; total {tot / 1e6:.0f} MB (din care detaliu p1: {p1 / 1e6:.0f} MB)", flush=True)

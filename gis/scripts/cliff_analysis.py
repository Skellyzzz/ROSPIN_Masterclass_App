"""Analiza stancilor din LiDAR PNOA 2024 + produsele de apa Planet -> puncte de saritura evaluate.

Rulare (dupa water_products.py), in QGIS:
    exec(open(QgsProject.instance().homePath() + "/scripts/cliff_analysis.py", encoding="utf-8").read())

Intrari (grila LiDAR 1 m, EPSG:25831):
  outputs/lidar/dtm_1m.tif        TIN din clasele 2 (sol) + 9 (apa); cote ortometrice ~ nivelul marii
  outputs/lidar/ground_z_bin.tif  cota punctelor de sol pe celula (lipsa = nu exista sol)
  outputs/lidar/water_z_bin.tif   cota punctelor de apa pe celula
  outputs/water/*.tif             produse Planet (EPSG:32631, 3 m), reproiectate aici la 1 m

Iesiri:
  outputs/lidar/slope_deg.tif, sea_mask_1m.tif, cliff_height_m.tif, shadow_<data>.tif
  outputs/spots/cliff_spots.gpkg  straturi: spots (puncte de desprindere), jumps (linii desprindere -> intrare in apa),
                                  swim (traseul de inot pana la cel mai apropiat mal bun de urcat), rejected

Atentie: adancimea din satelit este relativa (fara masuratori in situ). Clasificarea este un
filtru de pre-selectie, NU o garantie de siguranta. Orice loc se verifica la fata locului.
"""
import glob
import json
import math
import os

import numpy as np
from osgeo import gdal, ogr, osr
from scipy import ndimage


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
LID = f"{ROOT}/outputs/lidar"
WAT = f"{ROOT}/outputs/water"
SPOTS = f"{ROOT}/outputs/spots"
PS = f"{ROOT}/Mallorca_Coast_psscene_analytic_8b_sr_udm2/PSScene"
os.makedirs(SPOTS, exist_ok=True)
NODATA = -9999.0

DATES = {
    "20260924": "20260924_103622_94_2565",
    "20261014": "20261014_103612_85_2570",
    "20261022": "20261022_104057_02_255b",
}

# ------------------------------------------------------------------ citire
dtm_ds = gdal.Open(f"{LID}/dtm_1m.tif")
GT = dtm_ds.GetGeoTransform()
WKT = dtm_ds.GetProjection()
NY, NX = dtm_ds.RasterYSize, dtm_ds.RasterXSize
BOUNDS = (GT[0], GT[3] + GT[5] * NY, GT[0] + GT[1] * NX, GT[3])
z = dtm_ds.ReadAsArray().astype("float32")
z_valid = z > -1000
z = np.where(z_valid, z, 0.0)  # golurile TIN sunt pe mare (fara puncte) -> ~0 m


def read_bin(name):
    ds = gdal.Open(f"{LID}/{name}.tif")
    a = ds.ReadAsArray().astype("float32")
    return a, a != ds.GetRasterBand(1).GetNoDataValue()


gz, has_ground = read_bin("ground_z_bin")
wz, has_water = read_bin("water_z_bin")
vz, has_veg = read_bin("veg_z_bin")      # vegetatie medie/inalta (clasele 4, 5)


def warp_to_dtm(path, resample="near"):
    ds = gdal.Warp("", path, format="MEM", dstSRS="EPSG:25831", outputBounds=BOUNDS,
                   xRes=1, yRes=1, resampleAlg=resample)
    b = ds.GetRasterBand(1)
    return b.ReadAsArray(), b.GetNoDataValue()


def write(path, arr, dtype=gdal.GDT_Float32, nodata=NODATA):
    ds = gdal.GetDriverByName("GTiff").Create(path, NX, NY, 1, dtype, ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(GT)
    ds.SetProjection(WKT)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    b.ComputeStatistics(False)
    ds = None


# ------------------------------------------------------------------ masca marii la 1 m
planet_water, _ = warp_to_dtm(f"{WAT}/water_mask.tif")
rock = has_ground & (gz > 0.3)                       # sol LiDAR peste nivelul marii
# golurile TIN NU sunt automat mare (pot fi sub vegetatie deasa): apa = Planet sau puncte LiDAR clasa 9
sea = ((planet_water == 1) | has_water) & ~rock & (z < 1.5)
lab, n = ndimage.label(sea)
sizes = ndimage.sum(sea, lab, range(1, n + 1))
sea = lab == (int(np.argmax(sizes)) + 1)
# umple gauri mici fara puncte de sol (barci, spuma), dar pastreaza stancile emerse
holes = ndimage.binary_fill_holes(sea) & ~sea
hl, nh = ndimage.label(holes)
hs = ndimage.sum(holes, hl, range(1, nh + 1))
hg = ndimage.sum(has_ground, hl, range(1, nh + 1))
fill_ids = np.nonzero((hs < 40) & (hg == 0))[0] + 1
sea |= np.isin(hl, fill_ids)
land = ~sea
write(f"{LID}/sea_mask_1m.tif", sea.astype("uint8"), gdal.GDT_Byte, 255)

# distanta la mare + indicele celei mai apropiate celule de mare
dist_sea, (iy, ix) = ndimage.distance_transform_edt(land, return_indices=True)

# panta
gy, gx = np.gradient(z, 1.0)
slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")
write(f"{LID}/slope_deg.tif", np.where(z_valid, slope, NODATA))

# inaltimea stancii: cota terenului abrupt de langa mare (<= 15 m de apa, panta > 45 grade)
cliff_zone = land & (dist_sea <= 15) & (z >= 2) & (ndimage.maximum_filter(slope, 3) > 45)
write(f"{LID}/cliff_height_m.tif", np.where(cliff_zone, z, NODATA).astype("float32"))


# ------------------------------------------------------------------ umbre purtate (pe fiecare data Planet)
def cast_shadow(zz, az_deg, elev_deg, max_dist=80):
    az, el = math.radians(az_deg), math.radians(elev_deg)
    dx, dy = math.sin(az), -math.cos(az)  # coloane spre est, randuri spre sud
    tan_el = math.tan(el)
    shadow = np.zeros(zz.shape, bool)
    H, W = zz.shape
    for s in range(1, max_dist + 1):
        ox, oy = int(round(s * dx)), int(round(s * dy))
        src = np.full(zz.shape, -1e9, "float32")
        ys0, ys1 = max(0, -oy), min(H, H - oy)
        xs0, xs1 = max(0, -ox), min(W, W - ox)
        src[ys0:ys1, xs0:xs1] = zz[ys0 + oy:ys1 + oy, xs0 + ox:xs1 + ox]
        shadow |= src > zz + s * tan_el
    return shadow


shadows = {}
for date, sid in DATES.items():
    p = json.load(open(f"{PS}/{sid}_metadata.json"))["properties"]
    sh = cast_shadow(z, p["sun_azimuth"], p["sun_elevation"])
    shadows[date] = sh
    write(f"{LID}/shadow_{date}.tif", sh.astype("uint8"), gdal.GDT_Byte, 255)

# ------------------------------------------------------------------ produse Planet la 1 m
bottom = {}
sdb = {}
# adancimea calibrata cu ICESat-2 (calibrate_sdb.py) + eroarea tipica in apa < 10 m
CAL = json.load(open(f"{ROOT}/outputs/icesat2/calibration_report.json"))
U = {d: CAL[d]["u_shallow_m"] for d in DATES if d in CAL}
DEEP_MIN = CAL.get("optically_deep_icesat2_depth_p5_p50", [17.0])[0]
for date in DATES:
    b, _ = warp_to_dtm(f"{WAT}/bottom_class_{date}.tif")
    bottom[date] = b
    if date in U:
        s, snd = warp_to_dtm(f"{WAT}/sdb_cal_{date}.tif")
        sdb[date] = np.where(s == snd, np.nan, s)
# fractii pe 1 m din ortofoto 25 cm (ortho_rocks.py); -1 = in afara fasiei de coasta
ORTHO = {}
for nm in ("foam", "rock", "darkobj", "bottomvis"):
    p = f"{ROOT}/outputs/ortho/ortho_{nm}_frac_1m.tif"
    if os.path.exists(p):
        ORTHO[nm] = gdal.Open(p).ReadAsArray()
# tipul fundului din harta bionomica IDEIB (seabed_type.py); 0 = necartografiat
SEABED = None
_sb = f"{ROOT}/outputs/seabed/seabed_type_1m.tif"
if os.path.exists(_sb):
    SEABED = gdal.Open(_sb).ReadAsArray()
SEABED_NAMES = {1: "nisip", 2: "nisip + Posidonia", 3: "Posidonia", 4: "Cymodocea pe nisip",
                5: "stanca cu alge", 6: "stanca cu alge + Posidonia", 9: "alt tip"}
# ordinea de risc a claselor de fund: 1 luminos/putin adanc > 2 vizibil > 4 intunecat vizibil > 3 optic adanc
RANK = {1: 0, 2: 1, 4: 2, 3: 3}
UNRANK = {v: k for k, v in RANK.items()}
psdb_med, psdb_nd = warp_to_dtm(f"{WAT}/psdb_median.tif")
turb_med, turb_nd = warp_to_dtm(f"{WAT}/turbidity_FNU_median.tif")
chl_med, chl_nd = warp_to_dtm(f"{WAT}/chl_mg_m3_median.tif")
ww_freq, ww_nd = warp_to_dtm(f"{WAT}/whitewater_freq.tif")
fa_freq, fa_nd = warp_to_dtm(f"{WAT}/float_algae_freq.tif")

# ------------------------------------------------------------------ candidati de desprindere
H_MIN = 3.0       # m deasupra apei
D_MAX = 6.0       # distanta orizontala maxima pana la apa
BLOCK = 20        # m, un candidat per bloc
cand = land & (z >= H_MIN) & (dist_sea <= D_MAX) & z_valid
# scor: preferam buza stancii (aproape de apa) si inaltime
score = np.where(cand, z - 2.5 * dist_sea, -1e9)

rows, cols = np.nonzero(cand)
best = {}
for r, c in zip(rows, cols):
    k = (r // BLOCK, c // BLOCK)
    if k not in best or score[r, c] > score[best[k]]:
        best[k] = (r, c)
picked = sorted(best.values(), key=lambda rc: -score[rc])
# suprimare non-maxime: minim 15 m intre puncte
final = []
for r, c in picked:
    if all((r - r2) ** 2 + (c - c2) ** 2 >= 15 ** 2 for r2, c2 in final):
        final.append((r, c))

# ------------------------------------------------------------------ iesirea din apa si traseul de inot
# mal bun de urcat: teren jos (<= 2 m), panta < 30 grade, langa mare, care duce undeva (zona de teren
# accesibil, panta < 40, legata de el urca peste 8 m sau are > 300 m2 / atinge marginea zonei) si are >= 4 m2
from scipy.sparse import coo_matrix          # noqa: E402
from scipy.sparse.csgraph import dijkstra    # noqa: E402

# doar unde exista puncte de sol LiDAR reale (>= jumatate din vecinii 3x3): in umbra peretelui TIN-ul
# interpoleaza o suprafata joasa si plata peste apa fara puncte, care ar parea un mal fals
ground_dense = ndimage.uniform_filter(has_ground.astype("float32"), 3) >= 0.5
exit_base = land & z_valid & ground_dense & has_ground & (z <= 2.0) & (slope < 30) & (dist_sea <= 2)
walkable = land & z_valid & (slope < 40)
wl_, nwl = ndimage.label(walkable, structure=np.ones((3, 3)))
idx_ = np.arange(1, nwl + 1)
wl_max = ndimage.maximum(np.where(walkable, z, 0), wl_, idx_)
wl_size = ndimage.sum(walkable, wl_, idx_)
edge_lbl = np.unique(np.concatenate([wl_[0], wl_[-1], wl_[:, 0], wl_[:, -1]]))
good_lbl = idx_[(wl_max >= 8) | (wl_size >= 300) | np.isin(idx_, edge_lbl)]
exit_cells = exit_base & np.isin(wl_, good_lbl)
el_, nel = ndimage.label(exit_cells, structure=np.ones((3, 3)))
el_size = ndimage.sum(exit_cells, el_, np.arange(1, nel + 1))
exit_cells = np.isin(el_, np.nonzero(el_size >= 4)[0] + 1)
el_, nel = ndimage.label(exit_cells, structure=np.ones((3, 3)))
el_ids = np.arange(1, nel + 1)
el_zmed = ndimage.median(np.where(exit_cells, z, 0), el_, el_ids) if nel else []
el_smed = ndimage.median(np.where(exit_cells, slope, 0), el_, el_ids) if nel else []
EXIT_TYPE = {i: ("mal jos, aproape plat (plaja / platforma)" if zm <= 1.2 and sm < 12 else "stanca joasa")
             for i, zm, sm in zip(el_ids, el_zmed, el_smed)}
_, (ey_i, ex_i) = ndimage.distance_transform_edt(~exit_cells, return_indices=True)

# graf pe celulele de mare (8 vecini); costul = lungimea pasului, x1.6 lipit de perete (< 1.5 m de uscat,
# hula loveste peretele) si x2 peste stanci submerse vazute in ortofoto
near_wall = sea & (ndimage.distance_transform_edt(sea) < 1.5)
cell_cost = np.where(near_wall, 1.6, 1.0)
if "rock" in ORTHO:
    cell_cost = np.where(sea & (ORTHO["rock"] > 0.5), cell_cost * 2.0, cell_cost)
sea_id = -np.ones(sea.shape, "int64")
sea_id[sea] = np.arange(int(sea.sum()))
NS = int(sea.sum())
SRC = NS                                       # nod virtual: toate punctele de iesire
_rows, _cols, _w = [], [], []
for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):   # perechi (r, c) - (r + dy, c + dx)
    ra, ca0, ca1 = NY - dy, max(0, -dx), NX - max(0, dx)
    a = sea_id[0:ra, ca0:ca1]
    b = sea_id[dy:dy + ra, ca0 + dx:ca1 + dx]
    ca = cell_cost[0:ra, ca0:ca1]
    cb = cell_cost[dy:dy + ra, ca0 + dx:ca1 + dx]
    m_ = (a >= 0) & (b >= 0)
    L = math.hypot(dy, dx)
    w_ = (ca[m_] + cb[m_]) / 2 * L
    _rows += [a[m_], b[m_]]; _cols += [b[m_], a[m_]]; _w += [w_, w_]
exit_water = sea & ndimage.binary_dilation(exit_cells, structure=np.ones((3, 3)))
ew = sea_id[exit_water]
_rows.append(np.full(ew.size, SRC)); _cols.append(ew); _w.append(np.full(ew.size, 1e-6))
G = coo_matrix((np.concatenate(_w), (np.concatenate(_rows), np.concatenate(_cols))), shape=(NS + 1, NS + 1)).tocsr()
SWIM_D, SWIM_PRED = dijkstra(G, directed=True, indices=SRC, return_predecessors=True)
# lungimea reala (fara penalizari) se masoara pe traseu
sea_r, sea_c = np.nonzero(sea)
print(f"iesiri: {nel} zone de mal bun de urcat; mare: {NS} celule")


def _clear_line(a, b, ends=3.0):
    """Segment drept prin apa, fara sa atinga peretele/stancile (in afara primilor/ultimilor `ends` m)."""
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    for t in np.arange(0, L + 0.01, 0.5):
        rr = int(round(a[0] + (b[0] - a[0]) * t / max(L, 1e-9)))
        cc = int(round(a[1] + (b[1] - a[1]) * t / max(L, 1e-9)))
        if not sea[rr, cc]:
            return False
        if ends < t < L - ends and cell_cost[rr, cc] > 1.0:
            return False
    return True


def smooth_route(pts):
    """Netezire 'linie de vedere': din fiecare punct sare la cel mai departat punct vizibil prin apa."""
    out, i = [pts[0]], 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not _clear_line(pts[i], pts[j]):
            j -= max(1, (j - i) // 8) if j - i > 16 else 1
        out.append(pts[j])
        i = j
    return out


def swim_route(fy, fx):
    """Traseul de inot de la (rand, coloana) pana la cel mai apropiat mal bun de urcat."""
    r0, c0 = int(round(fy)), int(round(fx))
    r0, c0 = min(max(r0, 0), NY - 1), min(max(c0, 0), NX - 1)
    if not sea[r0, c0]:
        _, (yy, xx) = ndimage.distance_transform_edt(~sea[max(0, r0 - 10):r0 + 11, max(0, c0 - 10):c0 + 11],
                                                      return_indices=True)
        oy, ox = max(0, r0 - 10), max(0, c0 - 10)
        r0, c0 = oy + int(yy[r0 - oy, c0 - ox]), ox + int(xx[r0 - oy, c0 - ox])
        if not sea[r0, c0]:
            return None
    n_ = int(sea_id[r0, c0])
    if not np.isfinite(SWIM_D[n_]):
        return None
    path = [n_]
    while SWIM_PRED[path[-1]] != SRC and SWIM_PRED[path[-1]] >= 0:
        path.append(int(SWIM_PRED[path[-1]]))
    pts = [(int(sea_r[k]), int(sea_c[k])) for k in path]
    pts = smooth_route(pts)
    lr, lc = pts[-1]
    er, ec = int(ey_i[lr, lc]), int(ex_i[lr, lc])
    pts.append((er, ec))
    length = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(pts[:-1], pts[1:]))
    return pts, length, EXIT_TYPE.get(int(el_[er, ec]), "stanca joasa")


HEIGHT_CLASSES = [(5, 1, "Incepator"), (10, 2, "Intermediar"), (15, 3, "Avansat"),
                  (20, 4, "Expert"), (1e9, 5, "Extrem")]
LEVEL_NAMES = {1: "Incepator", 2: "Intermediar", 3: "Avansat", 4: "Expert", 5: "Extrem"}
# adancime minima recomandata (orientativ, dupa ghiduri de high diving / cliff diving)
def min_depth(h):
    return 3.0 if h < 5 else 4.0 if h < 10 else 5.0 if h < 20 else 6.0


def px_to_xy(r, c):
    return GT[0] + (c + 0.5) * GT[1], GT[3] + (r + 0.5) * GT[5]


def zat(rr, cc):
    ri, ci = int(round(rr)), int(round(cc))
    if 0 <= ri < NY and 0 <= ci < NX:
        return float(z[ri, ci]), ri, ci
    return None, ri, ci


def profile(r, c, uy, ux, h, d):
    """Profilul sariturii: cat de vertical e peretele, pervaze intermediare, loc de elan in spate."""
    # inainte (spre apa), pas 0.5 m
    ss = np.arange(0, d + 1.01, 0.5)
    zs = np.array([zat(r + s * uy, c + s * ux)[0] or 0.0 for s in ss])
    steep = max((math.degrees(math.atan2(zs[i] - zs[i + 2], 1.0)) for i in range(len(zs) - 2)), default=0.0)
    w = 6  # 3 m orizontal
    vert = max(((zs[i] - zs[i + w]) / max(h, 0.1) for i in range(len(zs) - w)), default=(zs[0] - zs[-1]) / max(h, 0.1))
    # pervaz: celule intre buza si apa, la 0.3 m .. h-1.5 m, aproape orizontale
    ledge_h, ledge_len = 0.0, 0.0
    for s, zz in zip(ss[1:], zs[1:]):
        if s >= d:
            break
        _, ri, ci = zat(r + s * uy, c + s * ux)
        if 0 <= ri < NY and 0 <= ci < NX and 0.3 < zz < h - 1.5 and slope[ri, ci] < 35:
            ledge_h = max(ledge_h, zz)
            ledge_len += 0.5
    # inapoi (spre uscat): pista de elan = teren aproape plat, fara vegetatie inalta, la nivelul buzei
    # panta se masoara intre puncte succesive ale pistei (panta rasterului la buza include peretele)
    # buza e adesea cu 1-2 m sub platou (margine rotunjita): primul pas poate urca pana la 2 m
    run = 0.0
    z_prev = h
    back = [zat(r - s * uy, c - s * ux)[0] for s in (1, 2, 3)]
    crevasse = any(b is not None and b < h - 3 for b in back)
    for s in np.arange(1, 15.01, 1.0):
        zz, ri, ci = zat(r - s * uy, c - s * ux)
        if zz is None or not land[ri, ci]:
            break
        step = zz - z_prev
        if (s == 1 and not (-0.6 <= step <= 2.0)) or (s > 1 and abs(step) > 0.6) or not (-0.6 <= zz - h <= 3.5):
            break
        if has_veg[ri, ci] and vz[ri, ci] - zz > 1.0:
            break
        z_prev = zz
        run = s
    return steep, min(vert, 1.0), ledge_h, ledge_len, run, crevasse


records = []
rejected = []
for r, c in final:
    h = float(z[r, c])
    d = float(dist_sea[r, c])
    sr, sc = int(iy[r, c]), int(ix[r, c])           # cel mai apropiat punct de apa
    vy, vx = sr - r, sc - c
    nrm = math.hypot(vx, vy) or 1.0
    uy, ux = vy / nrm, vx / nrm
    steep, vert, ledge_h, ledge_len, run_up, crevasse = profile(r, c, uy, ux, h, d)
    # filtru "stanca falsa": fara un perete abrupt (>= 55 grade pe 1 m) sau caderea e
    # imprastiata (< 50% din inaltime pe cei mai abrupti 3 m) -> plaja / panta, nu faleza
    if steep < 55 or vert < 0.5:
        x_, y_ = px_to_xy(r, c)
        rejected.append({"x": x_, "y": y_, "height_m": round(h, 1), "clearance_m": round(d, 1),
                         "steepest_deg": round(steep, 0), "vertical_frac": round(vert, 2),
                         "reason": "nu e faleza (perete prea putin abrupt)" if steep < 55 else
                                   "caderea nu e verticala (panta in trepte)"})
        continue
    # punctul de intrare in apa: ~3 m dincolo de linia tarmului, pe directia sariturii
    ly, lx = sr + 3 * uy, sc + 3 * ux
    y0, y1 = max(0, r - 30), min(NY, r + 31)
    x0, x1 = max(0, c - 30), min(NX, c + 31)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    along = (yy - r) * uy + (xx - c) * ux          # distanta pe directia sariturii
    perp = np.abs(-(yy - r) * ux + (xx - c) * uy)  # abaterea laterala
    # culoarul de intrare (unde cade sariturul): 8 m in larg de tarm, +-3 m lateral
    corridor = (along > d + 0.5) & (along <= d + 8) & (perp <= 3)
    rocks_px = int((corridor & land[y0:y1, x0:x1]).sum())
    # ortofoto 25 cm: stanci la suprafata, obiecte intunecate submerse, spuma in culoarul de intrare
    oc = (along > d + 1) & (along <= d + 12) & (perp <= 3) & sea[y0:y1, x0:x1]
    o_stats = {}
    for nm, arr in ORTHO.items():
        v = arr[y0:y1, x0:x1][oc]
        v = v[v >= 0]
        o_stats[nm] = (float(v.sum()), float(v.mean()) if v.size else None)
    # tipul fundului (harta bionomica) in zona de intrare, 1-15 m de tarm, +-4 m lateral
    sb_txt, sb_rock = "necartografiat", None
    if SEABED is not None:
        zc = (along > d + 1) & (along <= d + 15) & (perp <= 4) & sea[y0:y1, x0:x1]
        sv = SEABED[y0:y1, x0:x1][zc]
        sv = sv[sv > 0]
        if sv.size:
            vals, cnts = np.unique(sv, return_counts=True)
            sb_txt = SEABED_NAMES.get(int(vals[np.argmax(cnts)]), "alt tip")
            sb_rock = float(np.isin(sv, [5, 6]).mean())
    # stanca lipita de perete (primii 3 m): prag la baza SAU peretele vazut oblic (ortofoto nu e true-ortho)
    if "rock" in ORTHO:
        ra = ORTHO["rock"][y0:y1, x0:x1]
        near = oc & (along <= d + 3)
        o_rock_base = float(np.clip(ra[near], 0, None).sum())
        o_rock_out = float(np.clip(ra[oc & ~near], 0, None).sum())
    else:
        o_rock_base = o_rock_out = 0.0
    # zona de citire a adancimii din satelit: imaginea Planet e "incetosata" langa stancile
    # luminoase pe ~10-15 m, deci folosim primii pixeli de apa curata pana la 30 m in larg
    sea_zone = (along > d + 1) & (along <= d + 30) & (perp <= 8) & sea[y0:y1, x0:x1]

    # clasa fundului: cea mai putin adanca observata in datele fara umbra
    obs = []
    read_dists = []
    depth_obs = []
    shadowed_dates = 0
    along_z = along[sea_zone]
    for date in DATES:
        bz = bottom[date][y0:y1, x0:x1][sea_zone]
        shz = shadows[date][y0:y1, x0:x1][sea_zone]
        if shz.size and shz.mean() > 0.5:
            shadowed_dates += 1
            continue
        sel = np.isin(bz, [1, 2, 3, 4]) & ~shz
        ok = bz[sel]
        if ok.size >= 9:  # minim un pixel Planet intreg
            read_dists.append(float(np.min(along_z[sel]) - d))
            ranks = np.vectorize(RANK.get)(ok)
            # percentila 10 a riscului (conservator: 10% pixeli putin adanci ajung)
            obs.append(int(np.floor(np.percentile(ranks, 10))))
            if date in sdb:
                sz = sdb[date][y0:y1, x0:x1][sea_zone][sel]
                sz = sz[np.isfinite(sz)]
                if sz.size >= 9:
                    # p10 din pixeli, minus eroarea tipica a modelului in apa < 10 m
                    depth_obs.append((float(np.percentile(sz, 10)) - U[date], float(np.median(sz))))
    bottom_cls = UNRANK[min(obs)] if obs else 0
    depth_est = round(max(min(o[0] for o in depth_obs), 0), 1) if depth_obs else None
    depth_cal = round(min(o[1] for o in depth_obs), 1) if depth_obs else None
    if bottom_cls == 3 and depth_est is None:
        depth_est = DEEP_MIN  # apa optic adanca: ICESat-2 arata > ~17 m

    def zstat(arr, nd, fn=np.nanmedian):
        v = arr[y0:y1, x0:x1][sea_zone].astype("float64")
        v = v[(v != nd) & np.isfinite(v)] if nd is not None else v
        return round(float(fn(v)), 3) if v.size else None

    turb = zstat(turb_med, turb_nd)
    chl = zstat(chl_med, chl_nd)
    psdb = zstat(psdb_med, psdb_nd)
    ww = zstat(ww_freq, ww_nd, np.nanmax)
    fa = zstat(fa_freq, fa_nd, np.nanmax)

    # profilul desprinderii: panta medie a peretelui
    face_angle = math.degrees(math.atan2(h, max(d, 0.5)))
    # iesire din apa: traseul de inot (prin apa, ocolind stancile) pana la cel mai apropiat mal bun de urcat
    sw = swim_route(ly, lx)
    if sw:
        swim_pts, ed, exit_type = sw
    else:
        swim_pts, ed, exit_type = None, None, "nicio iesire gasita in zona LiDAR"

    # ---------------- dificultate
    base = next(lv for lim, lv, _ in HEIGHT_CLASSES if h < lim)
    level = base
    notes = []
    if d > 2.5:
        level += 1
        notes.append(f"trebuie sarit cu elan ~{d:.0f} m pe orizontala (pista {run_up:.0f} m)")
    if ledge_len >= 1.0:
        level += 1
    if ed is None or ed > 60:
        level += 1
        if ed is not None:
            notes.append(f"iesirea din apa e la ~{ed:.0f} m de inot")
    level = min(level, 5)

    # ---------------- siguranta
    reasons_red, reasons_yel = [], []
    if d > 5:
        reasons_red.append(f"apa la {d:.1f} m pe orizontala (prag/stanci la baza)")
    elif d > 3:
        reasons_yel.append(f"apa la {d:.1f} m pe orizontala")
    if d > 2.5 and run_up < 3:
        reasons_red.append(f"nu exista loc de elan (pista {run_up:.0f} m) pentru a ajunge la apa")
    if ledge_len >= 1.0:
        reasons_yel.append(f"pervaz la ~{ledge_h:.1f} m, {ledge_len:.1f} m lat, de depasit")
    if sb_rock is not None and sb_rock >= 0.3 and (depth_est is None or depth_est < need + 3):
        reasons_yel.append(f"fund stancos in zona de intrare ({sb_rock * 100:.0f}%, harta bionomica GOIB)")
    if crevasse:
        reasons_yel.append("crapatura/hau imediat in spatele buzei (acces si desprindere dificile)")
    if rocks_px >= 4:
        reasons_red.append(f"stanci emerse in zona de intrare ({rocks_px} m2)")
    elif rocks_px > 0:
        reasons_yel.append(f"posibile stanci in zona de intrare ({rocks_px} m2)")
    need = min_depth(h)
    if bottom_cls in (1, 2):
        # depth_est este deja conservator (p10 minus eroarea modelului calibrat cu ICESat-2)
        if depth_est is not None and depth_est < need:
            reasons_red.append(f"adancime (conservator) ~{depth_est:.0f} m < {need:.0f} m necesari")
        elif depth_est is not None and depth_est < need + 1:
            reasons_yel.append(f"adancime (conservator) ~{depth_est:.0f} m, la limita ({need:.0f} m necesari)")
        elif depth_est is None:
            reasons_yel.append("fundul se vede din satelit (adancime de verificat)")
        # altfel: fund vizibil dar estimat suficient de adanc -> fara penalizare
        # (in apa limpede din Mediterana fundul se vede pana la ~20 m)
    elif bottom_cls == 4:
        reasons_yel.append("fund stancos/intunecat vizibil (adancime nemasurabila din satelit)")
    elif bottom_cls == 0:
        reasons_yel.append("fara observatie valida a apei (umbra/nori)")
    o_rock = o_stats.get("rock", (0, None))[0]
    o_dark = o_stats.get("darkobj", (0, None))[0]
    o_bvis = o_stats.get("bottomvis", (0, None))[1]
    o_foam = o_stats.get("foam", (0, None))[1]
    if o_rock_out >= 2:
        reasons_red.append(f"stanci la suprafata in zona de intrare, ortofoto 25 cm ({o_rock_out:.0f} m2)")
    elif o_rock_out >= 0.5:
        reasons_yel.append(f"posibile stanci la suprafata in zona de intrare, ortofoto ({o_rock_out:.1f} m2)")
    if o_rock_base >= 1:
        reasons_yel.append(f"prag de stanca la baza peretelui in ortofoto ({o_rock_base:.0f} m2) - trebuie depasit")
    if o_dark >= 1 and (o_bvis or 0) >= 0.3:
        reasons_yel.append(f"posibile roci submerse pe fund luminos (ortofoto, {o_dark:.0f} m2)")
    if o_foam is not None and o_foam >= 0.15:
        reasons_yel.append(f"valuri sparte la baza in ortofoto ({o_foam * 100:.0f}% spuma)")
    if ww is not None and ww >= 0.34:
        reasons_yel.append(f"spuma/valuri in {ww * 100:.0f}% din imagini")
    if fa is not None and fa > 0:
        reasons_yel.append("alge/obiecte plutitoare observate")
    if turb is not None and turb > 5:
        reasons_yel.append(f"apa tulbure ({turb:.1f} FNU)")
    if ed is not None and ed > 150:
        reasons_yel.append(f"inot lung pana la iesire (~{ed:.0f} m)")
    elif ed is None:
        reasons_yel.append("nicio iesire din apa gasita in zona analizata")
    if reasons_red:
        safety, safety_txt = 3, "Nesigur"
    elif reasons_yel:
        safety, safety_txt = 2, "Atentie - verifica"
    else:
        safety, safety_txt = 1, "Promitator"

    x, y = px_to_xy(r, c)
    ex, ey = px_to_xy(ly, lx)
    records.append({
        "x": x, "y": y, "lx": ex, "ly": ey,
        "height_m": round(h, 1),
        "clearance_m": round(d, 1),
        "face_angle_deg": round(face_angle, 0),
        "steepest_deg": round(steep, 0),
        "vertical_frac": round(vert, 2),
        "ledge_h_m": round(ledge_h, 1),
        "ledge_len_m": round(ledge_len, 1),
        "run_up_m": round(run_up, 0),
        "crevasse_behind": int(crevasse),
        "difficulty": level,
        "difficulty_txt": LEVEL_NAMES[level],
        "height_class": LEVEL_NAMES[base],
        "min_depth_req_m": min_depth(h),
        "safety": safety,
        "safety_txt": safety_txt,
        "bottom_class": bottom_cls,
        "bottom_txt": {0: "necunoscut", 1: "fund de nisip luminos (putin adanc)", 2: "fund vizibil",
                       3: "optic adanc (fundul nu se vede)", 4: "fund intunecat vizibil (stanca/Posidonia)"}[bottom_cls],
        "depth_est_m": depth_est,
        "depth_cal_m": depth_cal,
        "seabed_txt": sb_txt,
        "seabed_rock_pct": round(sb_rock * 100, 0) if sb_rock is not None else None,
        "valid_dates": len(obs),
        "depth_read_offshore_m": round(min(read_dists), 0) if read_dists else None,
        "shadowed_dates": shadowed_dates,
        "rocks_landing_m2": rocks_px,
        "ortho_rock_m2": round(o_rock, 1),
        "ortho_rock_base_m2": round(o_rock_base, 1),
        "ortho_rock_out_m2": round(o_rock_out, 1),
        "ortho_darkobj_m2": round(o_dark, 1),
        "ortho_foam_pct": round(o_foam * 100, 0) if o_foam is not None else None,
        "ortho_bottomvis_pct": round(o_bvis * 100, 0) if o_bvis is not None else None,
        "exit_dist_m": round(ed, 0) if ed is not None else None,
        "exit_type": exit_type,
        "_swim": [px_to_xy(rr, cc) for rr, cc in swim_pts] if swim_pts else None,
        "turbidity_FNU": turb,
        "chl_mg_m3": chl,
        "psdb": psdb,
        "whitewater_freq": ww,
        "float_algae_freq": fa,
        "issues": "; ".join(reasons_red + reasons_yel + notes) or "-",
    })

# ------------------------------------------------------------------ scriere GeoPackage
gpkg = f"{SPOTS}/cliff_spots.gpkg"
if os.path.exists(gpkg):
    ogr.GetDriverByName("GPKG").DeleteDataSource(gpkg)
ds = ogr.GetDriverByName("GPKG").CreateDataSource(gpkg)
srs = osr.SpatialReference()
srs.ImportFromEPSG(25831)
fields = [k for k in records[0] if k not in ("x", "y", "lx", "ly", "_swim")] if records else []


def ftype(v):
    return ogr.OFTInteger if isinstance(v, (int, np.integer)) and not isinstance(v, bool) else \
        ogr.OFTReal if isinstance(v, float) else ogr.OFTString


for lname, gtype in [("spots", ogr.wkbPoint), ("jumps", ogr.wkbLineString)]:
    lyr = ds.CreateLayer(lname, srs, gtype)
    for k in fields:
        sample = next((rec[k] for rec in records if rec[k] is not None), "")
        lyr.CreateField(ogr.FieldDefn(k, ftype(sample)))
    for i, rec in enumerate(records):
        f = ogr.Feature(lyr.GetLayerDefn())
        for k in fields:
            if rec[k] is not None:
                f.SetField(k, rec[k])
        g = ogr.Geometry(gtype)
        if gtype == ogr.wkbPoint:
            g.AddPoint_2D(rec["x"], rec["y"])
        else:
            g.AddPoint_2D(rec["x"], rec["y"])
            g.AddPoint_2D(rec["lx"], rec["ly"])
        f.SetGeometry(g)
        lyr.CreateFeature(f)
# traseele de inot de la intrarea in apa pana la iesire (spot_fid = FID-ul punctului)
lyr = ds.CreateLayer("swim", srs, ogr.wkbLineString)
for k, t in (("spot_fid", ogr.OFTInteger), ("swim_m", ogr.OFTReal), ("exit_type", ogr.OFTString)):
    lyr.CreateField(ogr.FieldDefn(k, t))
for i, rec in enumerate(records):
    if not rec["_swim"]:
        continue
    g = ogr.Geometry(ogr.wkbLineString)
    g.AddPoint_2D(rec["lx"], rec["ly"])
    for x_, y_ in rec["_swim"]:
        g.AddPoint_2D(x_, y_)
    g = g.SimplifyPreserveTopology(0.7)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetField("spot_fid", i + 1); f.SetField("swim_m", rec["exit_dist_m"]); f.SetField("exit_type", rec["exit_type"])
    f.SetGeometry(g)
    lyr.CreateFeature(f)
# candidati respinsi (nu sunt faleze), pastrati pentru transparenta
lyr = ds.CreateLayer("rejected", srs, ogr.wkbPoint)
for k in ("height_m", "clearance_m", "steepest_deg", "vertical_frac"):
    lyr.CreateField(ogr.FieldDefn(k, ogr.OFTReal))
lyr.CreateField(ogr.FieldDefn("reason", ogr.OFTString))
for rec in rejected:
    f = ogr.Feature(lyr.GetLayerDefn())
    for k in ("height_m", "clearance_m", "steepest_deg", "vertical_frac", "reason"):
        f.SetField(k, rec[k])
    g = ogr.Geometry(ogr.wkbPoint)
    g.AddPoint_2D(rec["x"], rec["y"])
    f.SetGeometry(g)
    lyr.CreateFeature(f)
ds = None

summary = {
    "rejected_not_cliff": len(rejected),
    "spots": len(records),
    "by_safety": {t: sum(1 for r in records if r["safety_txt"] == t)
                  for t in ("Promitator", "Atentie - verifica", "Nesigur")},
    "by_difficulty": {n: sum(1 for r in records if r["difficulty_txt"] == n) for n in LEVEL_NAMES.values()},
    "height_range": [min(r["height_m"] for r in records), max(r["height_m"] for r in records)] if records else None,
}
json.dump(summary, open(f"{SPOTS}/summary.json", "w"), indent=2)
print(json.dumps(summary, indent=1))

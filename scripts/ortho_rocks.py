"""Detectia stancilor de la baza falezelor din ortofoto PNOA 25 cm (mai 2024).

    exec(open(QgsProject.instance().homePath() + "/scripts/ortho_rocks.py", encoding="utf-8").read())

Clasificare pixel cu pixel, doar in fasia de mare de <= 30 m de tarm (masca LiDAR):
  1 apa cu fund vizibil (fundal local luminos)   2 apa intunecata / adanca
  3 spuma / valuri sparte (alb, nesaturat)       4 stanca la suprafata sau abia acoperita (culoare de stanca, R ~ B)
  5 obiect intunecat submers pe fund luminos (bolovan / stanca / alge)
Iesiri (outputs/ortho/):
  ortho_coast_class_25cm.tif   clasele de mai sus (0 = uscat / in afara fasiei)
  ortho_foam_frac_1m.tif, ortho_rock_frac_1m.tif, ortho_darkobj_frac_1m.tif, ortho_bottomvis_frac_1m.tif
                               fractia fiecarei clase pe celula LiDAR de 1 m (pentru analiza punctelor)

Limitari: ortofoto nu e "true ortho" (peretii inalti se apleaca spre exterior cu cativa metri),
de aceea primul 1 m de langa tarm e ignorat. Imaginea e o singura zi (valurile si soarele din mai 2024).
Peste apa adanca / intunecata stancile submerse NU se pot vedea.
"""
import numpy as np
from osgeo import gdal
from scipy import ndimage


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

O = f"{_ROOT}/outputs/ortho"
L = f"{_ROOT}/outputs/lidar"
PX = 0.25
BAND_M = 30
EDGE_SKIP_M = 1.0

o = gdal.Open(f"{O}/pnoa_ortho_25cm.tif")
OGT, OWKT = o.GetGeoTransform(), o.GetProjection()
rgb = o.ReadAsArray().astype(np.int16)
R, G, B = rgb
H, W = R.shape

# masca marii LiDAR (1 m) adusa pe grila de 25 cm
sea_ds = gdal.Open(f"{L}/sea_mask_1m.tif")
LGT = sea_ds.GetGeoTransform()
sea1 = sea_ds.ReadAsArray() == 1
oy, ox = int(round((OGT[3] - LGT[3]) / PX)), int(round((LGT[0] - OGT[0]) / PX))
sea = np.zeros((H, W), bool)
sea[oy:oy + sea1.shape[0] * 4, ox:ox + sea1.shape[1] * 4] = np.repeat(np.repeat(sea1, 4, 0), 4, 1)
d_land = ndimage.distance_transform_edt(sea) * PX
band = sea & (d_land >= EDGE_SKIP_M) & (d_land <= BAND_M)

V = rgb.max(0)
Vmin = rgb.min(0)
S = (V - Vmin) / np.maximum(V, 1)

# spuma: alb, luminos, nesaturat; blob >= ~0.5 m2
foam = band & (V > 190) & (S < 0.22)
foam = ndimage.binary_opening(foam, iterations=1)

# stanca: culoare apropiata de uscat (in apa R e cu ~35-45 sub B), nu spuma
rock = band & ((R - B) > -15) & ~foam
rock = ndimage.binary_opening(rock, iterations=2)  # blob >= ~1 m2

# fundalul local al apei (medie mascata ~10 m) -> fund vizibil vs apa adanca
water = band & ~foam & ~rock
k = 41
wsum = ndimage.uniform_filter(water.astype("float32"), k)
bg = ndimage.uniform_filter(np.where(water, V, 0).astype("float32"), k) / np.maximum(wsum, 1e-3)
bright_bg = bg > 110                       # apa adanca are V ~80, nisipul putin adanc 150-250
dark = water & bright_bg & (V < 0.65 * bg)
dark = ndimage.binary_opening(dark, iterations=2)

cls = np.zeros((H, W), "uint8")
cls[water] = 2
cls[water & bright_bg] = 1
cls[dark] = 5
cls[foam] = 3
cls[rock] = 4


def write(path, arr, gt, dtype, nodata):
    ds = gdal.GetDriverByName("GTiff").Create(path, arr.shape[1], arr.shape[0], 1, dtype,
                                              ["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(OWKT)
    b = ds.GetRasterBand(1)
    b.SetNoDataValue(nodata)
    b.WriteArray(arr)
    ds = None


write(f"{O}/ortho_coast_class_25cm.tif", cls, OGT, gdal.GDT_Byte, 0)

# fractii pe grila LiDAR de 1 m (blocuri 4x4)
sub = (slice(oy, oy + sea1.shape[0] * 4), slice(ox, ox + sea1.shape[1] * 4))


def frac(mask, denom):
    m = mask[sub].reshape(sea1.shape[0], 4, sea1.shape[1], 4).sum((1, 3)).astype("float32")
    d = denom[sub].reshape(sea1.shape[0], 4, sea1.shape[1], 4).sum((1, 3)).astype("float32")
    return np.where(d > 0, m / np.maximum(d, 1), -1).astype("float32")


inband = cls > 0
for name, m in [("foam", cls == 3), ("rock", cls == 4), ("darkobj", cls == 5), ("bottomvis", (cls == 1) | (cls == 5))]:
    write(f"{O}/ortho_{name}_frac_1m.tif", frac(m, inband), LGT, gdal.GDT_Float32, -1)

n = inband.sum()
print({"pixeli_fasie": int(n), **{nm: round(float((cls == v).sum() / n), 4) for nm, v in
                                   [("fund_vizibil", 1), ("apa_adanca", 2), ("spuma", 3), ("stanca", 4), ("obiect_intunecat", 5)]}})

"""Incarca si stilizeaza rezultatele in proiectul QGIS deschis.

    exec(open(QgsProject.instance().homePath() + "/scripts/load_layers.py", encoding="utf-8").read())
"""
from qgis.core import (Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer, QgsColorRampShader,
                       QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsPalettedRasterRenderer,
                       QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsMarkerSymbol,
                       QgsLineSymbol, QgsStyle, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
                       QgsTextFormat, QgsTextBufferSettings, QgsHillshadeRenderer, QgsPointCloudLayer)
from qgis.PyQt.QtGui import QColor, QFont


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

ROOT = f"{_ROOT}/outputs"
P = QgsProject.instance()
tree = P.layerTreeRoot()

# sterge rezultatele vechi (reincarcare idempotenta)
for gname in ["Puncte de saritura", "Stanci (LiDAR)", "Apa - compozit", "Apa - pe date",
              "Ortofoto PNOA 25 cm (2024)", "Fund, acces, Sentinel-2"]:
    g = tree.findGroup(gname)
    if g:
        P.removeMapLayers([n.layerId() for n in g.findLayers()])
        tree.removeChildNode(g)


def group(name, idx):
    return tree.insertGroup(idx, name)


def add_raster(path, name, grp, visible=False):
    lyr = QgsRasterLayer(path, name)
    if not lyr.isValid():
        print("INVALID", path)
        return None
    P.addMapLayer(lyr, False)
    node = grp.addLayer(lyr)
    node.setItemVisibilityChecked(visible)
    return lyr


def ramp(lyr, ramp_name, vmin, vmax, invert=False, opacity=1.0):
    shader = QgsRasterShader()
    fn = QgsColorRampShader(vmin, vmax)
    r = QgsStyle.defaultStyle().colorRamp(ramp_name)
    if invert:
        r.invert()
    fn.setSourceColorRamp(r)
    fn.setColorRampType(Qgis.ShaderInterpolationMethod.Linear)
    fn.classifyColorRamp(7, 1)
    shader.setRasterShaderFunction(fn)
    rend = QgsSingleBandPseudoColorRenderer(lyr.dataProvider(), 1, shader)
    rend.setClassificationMin(vmin)
    rend.setClassificationMax(vmax)
    lyr.setRenderer(rend)
    lyr.setOpacity(opacity)
    lyr.triggerRepaint()


def paletted(lyr, classes, opacity=1.0):
    cl = [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in classes]
    lyr.setRenderer(QgsPalettedRasterRenderer(lyr.dataProvider(), 1, cl))
    lyr.setOpacity(opacity)
    lyr.triggerRepaint()


BOTTOM = [(1, "#f2e14c", "1 Fund nisipos luminos (putin adanc)"),
          (2, "#5ec7c1", "2 Fund vizibil"),
          (4, "#8a5a44", "4 Fund intunecat vizibil (stanca/Posidonia)"),
          (3, "#123a8a", "3 Optic adanc (fundul nu se vede)"),
          (9, "#9a9a9a", "9 Invalid (spuma/nori/adiacenta)")]

# ---------------------------------------------------------------- puncte de saritura
g_spots = group("Puncte de saritura", 0)
spots = QgsVectorLayer(f"{ROOT}/spots/cliff_spots.gpkg|layername=spots", "Puncte de saritura (siguranta)", "ogr")
jumps = QgsVectorLayer(f"{ROOT}/spots/cliff_spots.gpkg|layername=jumps", "Directie saritura", "ogr")
for lyr in (jumps, spots):
    P.addMapLayer(lyr, False)
    g_spots.addLayer(lyr)

cats = []
for val, color, label in [(1, "#1a9850", "Promitator"), (2, "#fdae61", "Atentie - verifica"),
                          (3, "#d73027", "Nesigur")]:
    sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "outline_color": "white",
                                        "outline_width": "0.4", "size": "3.2"})
    cats.append(QgsRendererCategory(val, sym, label))
spots.setRenderer(QgsCategorizedSymbolRenderer("safety", cats))
lab = QgsPalLayerSettings()
lab.fieldName = "concat(format_number(height_m,0), ' m')"
lab.isExpression = True
fmt = QgsTextFormat()
fmt.setFont(QFont("Arial", 8, QFont.Weight.Bold))
buf = QgsTextBufferSettings()
buf.setEnabled(True)
buf.setSize(0.8)
fmt.setBuffer(buf)
lab.setFormat(fmt)
spots.setLabeling(QgsVectorLayerSimpleLabeling(lab))
spots.setLabelsEnabled(True)
from qgis.core import QgsSingleSymbolRenderer
jumps.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
    {"color": "#ffffff", "width": "0.5", "line_style": "dash"})))

# traseul de inot pana la cel mai apropiat mal bun de urcat (ascuns implicit; se vede pe fiecare punct cu
# filtrul "spot_fid = <FID>" sau in aplicatia web la selectarea punctului)
swim = QgsVectorLayer(f"{ROOT}/spots/cliff_spots.gpkg|layername=swim", "Traseu de inot pana la iesire", "ogr")
if swim.isValid():
    P.addMapLayer(swim, False)
    g_spots.insertLayer(2, swim).setItemVisibilityChecked(False)
    _ss = QgsLineSymbol.createSimple({"color": "#00e5ff", "width": "0.6", "line_style": "dot"})
    from qgis.core import QgsMarkerLineSymbolLayer, QgsMarkerSymbol as _QMS
    _end = QgsMarkerLineSymbolLayer()
    _end.setPlacements(Qgis.MarkerLinePlacement.LastVertex)
    _end.setSubSymbol(_QMS.createSimple({"name": "triangle", "color": "#00e5ff", "outline_color": "#003a40",
                                         "size": "3", "angle": "90"}))
    _end.setRotateSymbols(True)
    _ss.appendSymbolLayer(_end)
    swim.setRenderer(QgsSingleSymbolRenderer(_ss))

# a doua vizualizare: dificultatea (ascunsa implicit)
diff = QgsVectorLayer(f"{ROOT}/spots/cliff_spots.gpkg|layername=spots", "Puncte de saritura (dificultate)", "ogr")
P.addMapLayer(diff, False)
g_spots.addLayer(diff).setItemVisibilityChecked(False)
dcats = []
for val, color, label in [(1, "#2c7bb6", "Incepator (<5 m)"), (2, "#abd9e9", "Intermediar (5-10 m)"),
                          (3, "#ffffbf", "Avansat (10-15 m)"), (4, "#fdae61", "Expert (15-20 m)"),
                          (5, "#d7191c", "Extrem (>20 m)")]:
    dcats.append(QgsRendererCategory(val, QgsMarkerSymbol.createSimple(
        {"name": "triangle", "color": color, "outline_color": "black", "size": "3.6"}), label))
diff.setRenderer(QgsCategorizedSymbolRenderer("difficulty", dcats))

# ---------------------------------------------------------------- stanci
g_cliff = group("Stanci (LiDAR)", 1)
lyr = add_raster(f"{ROOT}/lidar/cliff_height_m.tif", "Inaltimea stancii deasupra apei (m)", g_cliff, True)
ramp(lyr, "Magma", 2, 25)
lyr = add_raster(f"{ROOT}/lidar/slope_deg.tif", "Panta (grade)", g_cliff)
ramp(lyr, "Viridis", 0, 80, opacity=0.8)
lyr = add_raster(f"{ROOT}/lidar/dtm_1m.tif", "Relief umbrit (DTM 1 m)", g_cliff, True)
lyr.setRenderer(QgsHillshadeRenderer(lyr.dataProvider(), 1, 315, 45))
lyr.setOpacity(0.35)
for d in ["20260924", "20261014", "20261022"]:
    lyr = add_raster(f"{ROOT}/lidar/shadow_{d}.tif", f"Umbra stancilor {d}", g_cliff)
    paletted(lyr, [(1, "#000000", "umbra")], 0.5)
lyr = add_raster(f"{ROOT}/lidar/sea_mask_1m.tif", "Masca marii 1 m", g_cliff)
paletted(lyr, [(1, "#3b8bd9", "mare")], 0.5)

rej = QgsVectorLayer(f"{ROOT}/spots/cliff_spots.gpkg|layername=rejected", "Candidati respinsi (nu sunt faleze)", "ogr")
if rej.isValid():
    P.addMapLayer(rej, False)
    g_spots.addLayer(rej).setItemVisibilityChecked(False)
    rej.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "cross", "color": "#777777", "size": "3", "outline_width": "0.6"})))

# ---------------------------------------------------------------- fund, acces, Sentinel-2
import os as _os
g_x = group("Fund, acces, Sentinel-2", 2)
g_x.setExpanded(False)
sb = QgsVectorLayer(f"{ROOT}/seabed/seabed_type.gpkg", "Tipul fundului (harta bionomica GOIB)", "ogr")
if sb.isValid():
    P.addMapLayer(sb, False)
    g_x.addLayer(sb).setItemVisibilityChecked(False)
    sbc = []
    for code, color, lab_ in [(1, "#f3e6a8", "nisip"), (2, "#b8d98a", "nisip + Posidonia"), (3, "#2e7d32", "Posidonia"),
                              (4, "#8bc34a", "Cymodocea pe nisip"), (5, "#8d6e63", "stanca cu alge"),
                              (6, "#5d4037", "stanca cu alge + Posidonia"), (9, "#bdbdbd", "alt tip")]:
        from qgis.core import QgsFillSymbol
        sbc.append(QgsRendererCategory(code, QgsFillSymbol.createSimple(
            {"color": color, "outline_color": "#333333", "outline_width": "0.1"}), lab_))
    sb.setRenderer(QgsCategorizedSymbolRenderer("code", sbc))
    sb.setOpacity(0.6)
ow = QgsVectorLayer(f"{ROOT}/osm/osm_access.gpkg|layername=ways", "Poteci si drumuri (OSM)", "ogr")
if ow.isValid():
    P.addMapLayer(ow, False)
    g_x.addLayer(ow).setItemVisibilityChecked(False)
    oc_ = [QgsRendererCategory("walk", QgsLineSymbol.createSimple({"color": "#e65100", "width": "0.5", "line_style": "dash"}), "poteca / alee"),
           QgsRendererCategory("road", QgsLineSymbol.createSimple({"color": "#424242", "width": "0.8"}), "drum"),
           QgsRendererCategory("other", QgsLineSymbol.createSimple({"color": "#9e9e9e", "width": "0.3"}), "altele")]
    ow.setRenderer(QgsCategorizedSymbolRenderer("kind", oc_))
op = QgsVectorLayer(f"{ROOT}/osm/osm_access.gpkg|layername=parking", "Parcari (OSM)", "ogr")
if op.isValid():
    P.addMapLayer(op, False)
    g_x.addLayer(op).setItemVisibilityChecked(False)
    op.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "square", "color": "#1565c0", "outline_color": "white", "size": "3.5"})))
for nm, title, rmp, lo, hi in [("s2_foam_freq_vara", "Sentinel-2: frecventa spumei vara (2018-2026)", "Reds", 0, 0.3),
                               ("s2_foam_freq_iarna", "Sentinel-2: frecventa spumei iarna", "Reds", 0, 0.3),
                               ("s2_turb_median_vara", "Sentinel-2: turbiditate mediana vara (FNU)", "Turbo", 0, 3),
                               ("s2_turb_p90_vara", "Sentinel-2: turbiditate p90 vara (FNU)", "Turbo", 0, 6)]:
    pth = f"{ROOT}/s2/{nm}.tif"
    if _os.path.exists(pth):
        lyr = add_raster(pth, title, g_x)
        ramp(lyr, rmp, lo, hi)

# ---------------------------------------------------------------- ortofoto 25 cm
g_o = group("Ortofoto PNOA 25 cm (2024)", 3)
lyr = add_raster(f"{ROOT}/ortho/ortho_coast_class_25cm.tif", "Stanci / spuma la baza falezelor (ortofoto)", g_o, True)
if lyr:
    paletted(lyr, [(1, "#00000000", "apa cu fund vizibil"), (2, "#00000000", "apa adanca"),
                   (3, "#ffffff", "spuma / valuri sparte"), (4, "#ff00ff", "stanca la suprafata / prag"),
                   (5, "#ffcc00", "obiect intunecat submers")])
add_raster(f"{ROOT}/ortho/pnoa_ortho_25cm.tif", "Ortofoto PNOA 25 cm (mai 2024)", g_o, True)

# ---------------------------------------------------------------- apa compozit
g_w = group("Apa - compozit", 4)
lyr = add_raster(f"{ROOT}/water/bottom_class_conservative.tif", "Clasa fundului (conservator)", g_w, True)
paletted(lyr, BOTTOM, 0.8)
lyr = add_raster(f"{ROOT}/water/sdb_cal_safe.tif", "Adancime calibrata ICESat-2 - conservator (m)", g_w, True)
ramp(lyr, "Blues", 0, 20)
lyr = add_raster(f"{ROOT}/water/sdb_cal_min.tif", "Adancime calibrata ICESat-2 (m, min pe date)", g_w)
ramp(lyr, "Blues", 0, 20)
lyr = add_raster(f"{ROOT}/water/sdb_sand_m_min.tif", "Adancime necalibrata fund nisip (m) - vechi", g_w)
ramp(lyr, "Blues", 0, 20)
i2 = QgsVectorLayer(f"{ROOT}/icesat2/atl24_photons.gpkg|layername=photons", "ICESat-2 ATL24 fotoni fund (adancime)", "ogr")
if i2.isValid():
    # fixeaza conversia ITRF2020 (+EGM08) -> ETRS89/UTM 31N in proiect, ca QGIS sa nu mai deschida
    # dialogul "Select Transformation" la fiecare incarcare (diferentele intre variante sunt < 1 m)
    from qgis.core import QgsDatumTransform
    _dst = P.crs()
    _tc = P.transformContext()
    if not _tc.hasTransform(i2.crs(), _dst):
        _ops = [o for o in QgsDatumTransform.operations(i2.crs(), _dst) if o.isAvailable]
        _pick = next((o for o in _ops if "ITRF2020 to ETRF2020 (2)" in o.name), _ops[0] if _ops else None)
        if _pick:
            _tc.addCoordinateOperation(i2.crs(), _dst, _pick.proj)
            P.setTransformContext(_tc)
    P.addMapLayer(i2, False)
    g_w.insertLayer(0, i2).setItemVisibilityChecked(False)
    from qgis.core import QgsGraduatedSymbolRenderer, QgsClassificationEqualInterval
    sym = QgsMarkerSymbol.createSimple({"name": "circle", "size": "1.6", "outline_style": "no"})
    gr = QgsGraduatedSymbolRenderer('"surface_h" - "ortho_h"')
    gr.setSourceSymbol(sym)
    gr.setClassificationMethod(QgsClassificationEqualInterval())
    gr.updateClasses(i2, 8)
    gr.updateColorRamp(QgsStyle.defaultStyle().colorRamp("Spectral"))
    i2.setRenderer(gr)
    i2.setSubsetString('"confidence" >= 0.75')
lyr = add_raster(f"{ROOT}/water/psdb_median.tif", "Adancime relativa Stumpf (median)", g_w)
ramp(lyr, "Blues", 1.0, 1.35)
lyr = add_raster(f"{ROOT}/water/turbidity_FNU_median.tif", "Turbiditate FNU (median)", g_w)
ramp(lyr, "Turbo", 0, 6)
lyr = add_raster(f"{ROOT}/water/turbidity_FNU_range.tif", "Variatia turbiditatii intre date (FNU)", g_w)
ramp(lyr, "Reds", 0, 4)
lyr = add_raster(f"{ROOT}/water/chl_mg_m3_median.tif", "Clorofila-a mg/m3 (median, OC3)", g_w)
ramp(lyr, "Viridis", 0.1, 1.0)
lyr = add_raster(f"{ROOT}/water/ndci_median.tif", "NDCI alge (median)", g_w)
ramp(lyr, "RdYlGn", -0.5, 0.2, invert=True)
lyr = add_raster(f"{ROOT}/water/whitewater_freq.tif", "Frecventa spuma/valuri", g_w)
ramp(lyr, "Reds", 0, 1)
lyr = add_raster(f"{ROOT}/water/float_algae_freq.tif", "Frecventa alge plutitoare", g_w)
ramp(lyr, "Greens", 0, 1)
lyr = add_raster(f"{ROOT}/water/dist_shore_m.tif", "Distanta de la tarm (m)", g_w)
ramp(lyr, "Greys", 0, 500)

# ---------------------------------------------------------------- apa pe date
g_d = group("Apa - pe date", 5)
g_d.setExpanded(False)
for d in ["20260924", "20261014", "20261022"]:
    sub = g_d.addGroup(d)
    sub.setExpanded(False)
    sub.setItemVisibilityChecked(False)
    lyr = add_raster(f"{ROOT}/water/bottom_class_{d}.tif", f"Clasa fundului {d}", sub)
    paletted(lyr, BOTTOM, 0.8)
    lyr = add_raster(f"{ROOT}/water/sdb_sand_m_{d}.tif", f"Adancime aprox. {d}", sub)
    ramp(lyr, "Blues", 0, 20)
    lyr = add_raster(f"{ROOT}/water/turbidity_FNU_{d}.tif", f"Turbiditate {d}", sub)
    ramp(lyr, "Turbo", 0, 6)
    lyr = add_raster(f"{ROOT}/water/chl_mg_m3_{d}.tif", f"Clorofila {d}", sub)
    ramp(lyr, "Viridis", 0.1, 1.0)
    lyr = add_raster(f"{ROOT}/water/adjacency_frac_{d}.tif", f"Fractie adiacenta {d}", sub)
    ramp(lyr, "Greys", 0, 0.9)

# grupurile originale jos, punct LiDAR ascuns (greu de randat peste rezultate)
for l in P.mapLayers().values():
    if isinstance(l, QgsPointCloudLayer):
        tree.findLayer(l.id()).setItemVisibilityChecked(False)
for gname in ["Puncte de saritura", "Stanci (LiDAR)", "Apa - compozit"]:
    tree.findGroup(gname).setExpanded(True)
print("incarcat:", len(P.mapLayers()), "straturi")

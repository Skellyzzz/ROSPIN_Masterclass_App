# CLAVADO – produse din date (Mallorca, zona de test)

Zona de test: coasta de est a Mallorcăi (~39.50°N, 3.30°E), 1 × 2 km acoperiți de LiDAR, 4.1 × 3.5 km acoperiți de Planet.
Proiect QGIS: `../cliff_dive_spot_finder.qgz`. Totul se poate regenera cu scripturile din `../scripts/`, rulate în ordinea de mai jos (din consola Python a QGIS):

1. `water_products.py` – produsele de apă din Planet
2. `fetch_icesat2_atl24.py` – descarcă batimetria laser ICESat-2. Nu rulează în QGIS, ci în mediul virtual `../.venv-icesat2` (clientul `sliderule`). CSV-ul în UTM se exportă tot de acolo.
3. `calibrate_sdb.py` – calibrează adâncimea din Planet cu ICESat-2
4. `fetch_pnoa_ortho.py` – descarcă ortofoto PNOA 25 cm (WMS IGN)
5. `ortho_rocks.py` – detectează stâncile, spuma și obiectele submerse de la baza falezelor
6. `seabed_type.py` – tipul fundului din harta bionomică GOIB. Poligoanele se descarcă o singură dată din serviciul REST IDEIB; vezi antetul scriptului.
7. `cliff_analysis.py` – analiza stâncilor din LiDAR și punctele de săritură
8. `wave_exposure.py` – expunerea la valuri (istoric Open-Meteo + forma coastei). Rulează **după** `cliff_analysis.py`, pentru că adaugă câmpuri în același GeoPackage.
9. `osm_access.py` – accesul din OpenStreetMap. Datele vin din `outputs/osm/access_raw.json`, interogarea Overpass e în README la „Acces”. Rulează tot după `cliff_analysis.py`.
10. `s2_timeseries.py` – statistici Sentinel-2 2018–2026 (în `.venv-icesat2`, are nevoie de `rasterio`)
11. `export_app.py` – exportă punctele pentru aplicația web (`outputs/webapp/`)
11b. `export_tiles.py` – datele 3D ale aplicației, în dale comune de 50 m (în `.venv-icesat2`, are nevoie de `laspy[lazrs]`, `scipy` și `pillow`; ~30 s). Rulează după pașii 7–9, pentru că citește punctele și traseele de înot din `cliff_spots.gpkg`.
12. `load_layers.py` – încarcă și stilizează straturile în proiect

Înainte de a rula din nou pașii 1, 3 sau 4 în QGIS, scoate din proiect grupurile cu rezultate. Altfel Windows blochează suprascrierea fișierelor.

DTM-ul (`lidar/dtm_1m.tif`) și rasterele `ground_z_bin` / `water_z_bin` au fost generate cu algoritmii PDAL din QGIS: `exportrastertin` pe clasele 2+9 și `exportraster` pe fiecare clasă.

## Date de intrare

| Sursă | Ce conține |
|---|---|
| PNOA LiDAR 2024 (IGN), 2 foi `525-4372`, `525-4373` | ~15 milioane de puncte, clase ASPRS (2 sol, 9 apă), RGB+NIR, cote ortometrice (≈ nivelul mării) |
| PlanetScope SuperDove 8 benzi SR + UDM2 | 24 sep 2026 (2 scene, mozaic), 14 oct 2026 (26% nori), 22 oct 2026 (acoperire 41%, sclipire a soarelui) |
| Ortofoto PNOA (IGN), WMS `pnoa-ma` | fotografii aeriene din avion, 25 cm, zbor din mai 2024 (nu e „true ortho”: pereții înalți apar ușor aplecați) |
| ICESat-2 ATL24 v007 (NASA), prin serviciul public SlideRule | 2.519 fotoni de fund din 51 de granule (2018–2026); după filtrare (confidence ≥ 0.75, fără flag de calitate, pe apă) rămân 1.624 de fotoni, adică 1.225 de eșantioane pixel × trecere din 22 de treceri |

## Produse

### Puncte de săritură – `spots/cliff_spots.gpkg`
- strat `spots`: punctul de desprindere, cel mai bun dintr-un bloc de 20 × 20 m, cu minimum 15 m între puncte
- strat `jumps`: linia de la punctul de desprindere la punctul de intrare în apă

| Câmp | Semnificație |
|---|---|
| `height_m` | înălțimea punctului de desprindere deasupra apei (LiDAR) |
| `clearance_m` | distanța orizontală până la apă (cât trebuie sărit „în față”) |
| `face_angle_deg` | panta medie a peretelui (90° = vertical) |
| `difficulty` / `difficulty_txt` | 1 Începător (<5 m), 2 Intermediar (5–10), 3 Avansat (10–15), 4 Expert (15–20), 5 Extrem (>20); se adaugă +1 nivel dacă `clearance_m` > 2.5 m și +1 dacă ieșirea din apă e la peste 60 m de înot |
| `min_depth_req_m` | adâncimea minimă orientativă pentru înălțimea respectivă (3 / 4 / 5 / 6 m) |
| `safety` / `safety_txt` | 1 Promițător, 2 Atenție – verifică, 3 Nesigur |
| `issues` | motivele clasificării, în text |
| `bottom_class` / `bottom_txt` | tipul fundului în zona de aterizare (cel mai riscant caz observat) |
| `depth_est_m` | adâncimea **conservatoare** calibrată cu ICESat-2: percentila 10 din zona de aterizare minus eroarea modelului în apa < 10 m. Pentru apă optic adâncă se pune 17.4 m (limita inferioară măsurată de ICESat-2). |
| `depth_cal_m` | adâncimea calibrată tipică (mediana din zonă, fără marjă) |
| `depth_read_offshore_m` | la câți metri de perete a putut fi citită apa din satelit |
| `rocks_landing_m2` | stânci emerse în culoarul de intrare (8 m în larg, ±3 m lateral) |
| `ortho_rock_out_m2` | stâncă la suprafață sau abia acoperită, văzută în ortofoto în zona de intrare (3–12 m de perete). Peste 2 m² → Nesigur. |
| `ortho_rock_base_m2` | stâncă în primii 3 m de la perete: un prag de depășit, sau peretele văzut oblic. Peste 1 m² → Atenție. |
| `ortho_darkobj_m2` | obiecte întunecate submerse pe fund luminos (bolovani / stânci / alge) |
| `ortho_foam_pct` | procentul de spumă în culoarul de intrare (valuri care se sparg la bază) |
| `ortho_bottomvis_pct` | procentul din culoar în care fundul se vede în ortofoto |
| `exit_dist_m` | distanța **de înot** (prin apă, ocolind stâncile) de la locul de intrare în apă până la cel mai apropiat mal bun de urcat; peste 150 m punctul primește „Atenție” |
| `exit_type` | tipul malului de ieșire: „stâncă joasă” sau „mal jos, aproape plat (plajă / platformă)” |
| `turbidity_FNU`, `chl_mg_m3`, `whitewater_freq`, `float_algae_freq` | calitatea apei în zona de aterizare |
| `valid_dates`, `shadowed_dates` | câte imagini au putut fi folosite / câte erau în umbra stâncii |

Regulile de siguranță:
- **Nesigur**: apa e la mai mult de 5 m pe orizontală, există stânci emerse în culoar (≥ 4 m²) sau adâncimea estimată e sub minimul necesar.
- **Atenție**: apa e la 3–5 m, există posibile stânci, adâncimea e la limită, fundul e stâncos/întunecat, nu există observație validă, sunt spumă/valuri în ≥ 34% din imagini, alge sau turbiditate > 5 FNU.
- **Promițător**: niciuna dintre situațiile de mai sus.

### Profilul săriturii, valuri, fund, acces (câmpuri noi în `cliff_spots.gpkg`)
| Câmp | Semnificație |
|---|---|
| `steepest_deg`, `vertical_frac` | cea mai abruptă porțiune de 1 m a peretelui și fracția din înălțime care cade în cei mai abrupți 3 m. Candidații cu < 55° sau < 50% sunt respinși: nu sunt faleze, sunt pante sau plaje. Îi găsești în stratul `rejected`. |
| `ledge_h_m`, `ledge_len_m` | pervaz între buză și apă (înălțime, lățime). Peste 1 m lățime urcă dificultatea cu un nivel și dă „Atenție”. |
| `run_up_m` | loc de elan în spate: teren aproape plat (≤ 0.6 m diferență pe metru), fără vegetație înaltă, până la 15 m. Dacă apa e la peste 2.5 m și pista sub 3 m → Nesigur. |
| `crevasse_behind` | crăpătură sau hău de peste 3 m chiar în spatele buzei |
| `seabed_txt`, `seabed_rock_pct` | tipul fundului în zona de intrare, din harta bionomică GOIB. Fund stâncos ≥ 30%, combinat cu o adâncime la limită → Atenție. |
| `facing_deg`, `open_sector`, `open_mask` | direcția în care privește peretele și direcțiile deschise spre larg (raze de 1.5 km, pas de 5°) |
| `waves_gt05_pct`, `waves_gt1_pct`, `summer_waves_gt05_pct`, `summer_calm_days_pct`, `exposure_txt` | statistici ale valului efectiv la punct (Hs × cos(unghi), doar din direcțiile deschise), pe istoricul Open-Meteo oct 2021 – dec 2025 |
| `dist_path_m`, `dist_road_m`, `dist_parking_m`, `walk_from_parking_m`, `off_trail_m`, `access_txt` | accesul din OpenStreetMap (traseu pe rețeaua de poteci de la parcare + porțiunea în afara potecii) |

Validare cu locuri cunoscute: OSM nu are locuri de cliff diving etichetate în Mallorca (numele „Salt de…” sunt cascade sau stânci din Tramuntana). Validarea trebuie făcută cu o listă de la comunitate.

### Traseul de înot până la ieșire – stratul `swim` din `cliff_spots.gpkg`
Un **mal bun de urcat** e teren cu puncte de sol LiDAR reale, cel mult 2 m peste apă, cu panta sub 30°, la cel mult 2 m de mare, de cel puțin 4 m². În plus, trebuie să ducă undeva: terenul accesibil legat de el (pantă sub 40°) urcă peste 8 m, are peste 300 m² sau atinge marginea zonei. Așa sunt excluse pervazurile izolate de la baza pereților. Cerința de puncte de sol reale contează: în umbra peretelui, LiDAR-ul nu are puncte, iar suprafața interpolată acolo ar părea un mal fals.

Traseul e drumul cel mai scurt prin apă, calculat cu Dijkstra pe grila de 1 m (8 vecini). Penalizări:
- ×1.6 lipit de perete (sub 1.5 m de uscat), unde hula lovește stânca;
- ×2 peste stâncile submerse văzute în ortofoto.

Apoi traseul e netezit în linii drepte prin apă. Câmpurile stratului: `spot_fid` (FID-ul punctului), `swim_m`, `exit_type`.

Limitări: se caută doar ieșiri din zona LiDAR (1 × 2 km). Scările sau frânghiile puse de oameni nu se văd. Un mal „bun” geometric poate fi alunecos sau bătut de valuri: verifică ieșirea înainte să sari.

### Stânci (LiDAR, 1 m) – `lidar/`
- `dtm_1m.tif` – model digital al terenului (TIN din clasele sol + apă)
- `slope_deg.tif` – panta terenului
- `cliff_height_m.tif` – cota terenului abrupt (> 45°) aflat la cel mult 15 m de apă
- `sea_mask_1m.tif` – marea (Planet + punctele LiDAR de apă, fără punctele de sol emerse)
- `shadow_<data>.tif` – umbra purtată a stâncilor, calculată pentru poziția soarelui din fiecare imagine

### Apă (Planet, 3 m) – `water/`
| Produs | Metodă |
|---|---|
| `water_mask`, `dist_shore_m` | NIR < 0.06, componenta conexă a mării |
| `adjacency_frac_<data>` | fracția de lumină reflectată de uscatul vecin (model de amestec liniar pe NIR); această contribuție e scăzută din spectru |
| `turbidity_FNU_*` | Nechad et al. 2009, banda roșie 665 nm |
| `chl_mg_m3_*` | algoritm OC3 (raport albastru/verde) – clorofila-a, adică indicatorul pentru fitoplancton/alge |
| `ndci_*` | Normalized Difference Chlorophyll Index (red-edge vs. roșu) |
| `float_algae_*`, `whitewater_*` | alge sau obiecte plutitoare (NIR + NDVI), respectiv spumă / valuri sparte |
| `psdb_*` | adâncime relativă Stumpf 2003 (fără unitate, crește cu adâncimea) |
| `bottom_class_*` | 1 nisip luminos (puțin adânc), 2 fund vizibil, 3 optic adânc, 4 fund întunecat vizibil (stâncă/Posidonia), 9 invalid |
| `sdb_sand_m_*` | (vechi, necalibrat) adâncime Lyzenga cu o singură bandă, presupunând fund de nisip |
| `rho_corr_<data>` | reflectanța corectată (adiacență + deglint), benzile 1–4, folosită la calibrare |
| `sdb_cal_<data>`, `sdb_cal_min` | **adâncimea calibrată cu ICESat-2** (m), doar unde fundul se vede |
| `sdb_cal_safe` | adâncimea calibrată minus eroarea tipică în apa < 10 m, minimul pe date. E stratul de folosit pentru siguranță. |
| `*_median`, `*_range`, `*_freq`, `*_conservative`, `sdb_sand_m_min` | compozite pe cele 3 date |

Valori tipice în zonă: clorofila-a ~0.3 mg/m³ (apă oligotrofă, foarte limpede) și turbiditatea ~2–4 FNU. Turbiditatea e probabil supraestimată în valoare absolută, pentru că corecția atmosferică Planet nu e făcută pentru apă; folosește-o relativ, ca să compari locurile și datele între ele.

### Alte surse – `waves/`, `osm/`, `seabed/`, `s2/`
- `waves/wave_history_2016_2025.csv`: valuri orare Open-Meteo Marine, punct de grilă 39.375°N 3.375°E. Datele există doar din oct 2021; `wave_rose.json` e roza valurilor.
- `osm/access_raw.json`, `osm/osm_access.gpkg`: drumuri, poteci și parcări. Interogarea Overpass: `way["highway"](39.475,3.265,39.525,3.34); amenity=parking`.
- `seabed/ideib_layer2.geojson`: Posidonia. `seabed/ideib_layer4.geojson`: bionomia LIFE 2006. Ambele din IDEIB `GOIB_Posidonia_IB` (CC BY-SA). `seabed_type_1m.tif` / `.gpkg` e clasificarea în nisip, Posidonia, Cymodocea, stâncă cu alge.
- `waves/wave_monthly_spots.json`: pentru fiecare punct și fiecare lună, procentul de zile calme (valul efectiv maxim între 09 și 19 < 0.5 m) și agitate (≥ 1 m). `waves/sst_monthly.json`: temperatura apei la suprafață pe luni (Open-Meteo Marine, oct 2021 – oct 2026).
- `s2/`: statistici Sentinel-2 L2A 2018–2026 (Earth Search / AWS, 565 de scene fără nori), separat pentru vară (mai–oct) și iarnă: turbiditate mediană și p90, frecvența spumei, numărul de observații. `s2_monthly.json` e climatologia lunară a fâșiei de coastă (≤ 150 m); `s2_spot_stats.json` dă pentru fiecare punct spuma și turbiditatea pe luni. Spuma se definește ca **anomalie** (NIR și albastru cu > 0.04 peste apa largă din aceeași scenă): pragul absolut folosit inițial confunda reflexia soarelui (sunglint, puternică vara la ora trecerii Sentinel-2) cu spuma. `cache_v2/` păstrează fiecare scenă, deci o rerulare durează câteva secunde.

**Luni bune** (în aplicație, calculate de `export_app.py`): o lună e bună pentru un punct dacă (1) ≥ 80% din zile sunt calme la acel punct, (2) apa are în medie ≥ 21 °C și (3) spuma apare în ≤ 25% din imaginile Sentinel-2 ale lunii. Pragurile sunt în `export_app.py` (`CALM_MIN`, `SST_MIN`, `FOAM_MAX`).

### Aplicație web (prototip) – `webapp/`
Aplicația are nevoie de un server web static, fiindcă vizualizarea 3D descarcă fișiere. Local: `py -m http.server 8765 --directory outputs/webapp`. Online merge pe orice găzduire statică (GitHub Pages, Netlify). Deschisă direct ca fișier, harta funcționează, dar fără 3D: punctele se deschid în fișa clasică.

Interfața e gândită pentru telefon. Harta ocupă tot ecranul, iar filtrele și lista sunt într-un panou care urcă de jos (butonul „Filtre și listă”). Pe ecran mare, panoul stă în stânga. Conține:
- harta cu Esri satelit (implicit), ortofoto PNOA sau OSM;
- filtre după siguranță, dificultate și înălțime;
- **macheta 3D a punctului selectat** (etichetele stau la distanță de punctele lor, legate prin linii, ca să nu acopere săritura): harta zboară la punct, ecranul trece prin negru, iar punctul apare ca o **machetă rotundă pe masă**. Terenul e tăiat în cerc și stă pe un soclu de lemn, pe un fundal de studio. Pe margine se vede secțiunea prin stâncă, în straturi, iar unde e mare, coloana de apă de la fund la suprafață, ca o rășină albastră. Cercul cuprinde desprinderea, intrarea și traseul de înot, plus 16 m de margine (raza 45–147 m, mediana 47 m). Macheta e fixă: se poate doar roti, înclina între 25° și 68° și apropia sau depărta cu ±~15%, fără deplasare. Privită de la distanță, nu se mai văd defectele de aproape ale datelor. Butonul de sus comută între trei moduri, iar alegerea se reține:
  - **Hibrid** (implicit): modelul 3D texturat dă corpul solid, iar discurile din norul de puncte stau deasupra ca textură. Discurile sunt trase cu ~35 cm spre cameră, iar suprafața coborâtă cu 25 cm, ca să nu se acopere reciproc. Pe pereții mai abrupți de ~60° rămâne doar modelul, pentru că acolo culoarea punctelor vine din umbrele ortofoto și ar ieși pete negre.
  - **Model 3D**: doar suprafața texturată, ca terenul din Google Earth.
  - **Puncte**: doar norul de puncte LiDAR, desenat ca discuri.
  Modul „Model 3D” nu descarcă punctele deloc.

  Animația: macheta se așază în poziție, apoi se desenează curba săriturii. Un săritor cade pe ea în timp real, cu timpul de cădere și viteza de intrare în apă. Urmează stropul și traseul de înot până la ieșire, iar la final macheta se rotește lent. Atingerea ecranului oprește animația și rotirea automată. „Reluare” repornește animația, iar „← Hartă” sau butonul „înapoi” al telefonului revine la hartă, tot prin negru;
- fișa punctului (jos pe telefon, se deschide la atingere; în dreapta pe ecran mare), cu motive, adâncime, fund, elan, ieșire din apă, expunere, acces și lunile bune (cu mouse-ul pe o lună vezi % zile calme, temperatura apei și spuma);
- **prognoza live a valurilor** (Open-Meteo), calculată pentru fiecare punct după orientarea peretelui și direcțiile deschise spre larg: calm (< 0.5 m), moderat (0.5–1 m) sau agitat (> 1 m), pentru azi, mâine și poimâine.

Curba săriturii e o parabolă de la buză la punctul de intrare, cu o viteză verticală inițială de 1.5 m/s (o desprindere tipică) și g = 9.81 m/s². Rezistența aerului e ignorată, neglijabilă la aceste înălțimi. Ex.: 9.3 m → 1.5 s, ~50 km/h; 22.8 m → 2.3 s, ~77 km/h.

**Stocarea în dale** (`webapp/tiles/`, din `export_tiles.py`). Datele 3D sunt stocate **o singură dată**, în dale de 50 m aliniate la grila EPSG:25831. Se exportă doar dalele atinse de vreo machetă: 258 de dale, 40 MB în total (948 de fișiere). Fiecare machetă cere doar dalele din cercul ei și le asamblează pe loc într-un singur model (o grilă de cote, o textură, un set de puncte), deci fără cusături.

Punctele vecine refolosesc dalele deja descărcate. Exemplu măsurat: macheta #69 (raza ~100 m) a cerut 56 de fișiere, 788 KB. Punctul vecin #93, la 29 m distanță, a mai cerut doar 20 de fișiere noi, 233 KB.

Varianta anterioară, cu fișiere separate pe punct, stoca aceleași date de ~4.5 ori (99 MB). Suma cercurilor era 2.07 km², iar zona reală acoperită doar 0.46 km². Cu dale, un punct nou de săritură nu mai adaugă date.

Fișierele unei dale `ix_iy` (ix = ⌊E/50⌋, iy = ⌊N/50⌋):

| Fișier | Conținut | Mărime tipică |
|---|---|---|
| `ix_iy.h` | cote int16 la 2 cm, 51 × 51 vârfuri la 1 m (marginile comune cu vecinele) | 5 KB |
| `ix_iy.jpg` | ortofoto PNOA 25 cm, 200 × 200 px | 10–20 KB |
| `ix_iy.p0` | puncte rare (unul pe voxel de 1 m), descărcate pentru toată macheta: poziție, RGB, normală, rază fină și rază rară (14 o/punct) | 20–40 KB |
| `ix_iy.p1` | restul punctelor (detaliu), descărcate doar pentru dalele aflate la ≤ 38 m de săritură (13 o/punct) | 50–250 KB (cel mult ~0.8 MB) |
| `index.json` | mărimea dalei, unitățile, numărul de puncte pe dală | |
| `spots.json` | pentru fiecare punct: originea (desprinderea, E/N), cota desprinderii, intrarea, traseul de înot, ieșirea și cercul machetei | |

Normalele și razele discurilor se calculează cu o margine de 3 m în jurul dalei, ca să nu apară cusături. Nivelul rar se alege pe o grilă globală de voxeli, deci e același indiferent de dală.

Pentru o zonă mult mai mare (toată coasta), pasul următor ar fi niveluri de detaliu pentru dalele îndepărtate. Pentru norul de puncte există și formatul `.copc.laz` (îl avem deja), pe care browserul îl poate citi pe bucăți prin HTTP.

**Modelul 3D texturat** are două părți:
- **Uscatul** e suprafața LiDAR: cota cea mai înaltă a punctelor de pe fiecare celulă de 1 m, ca să se vadă muchiile stâncilor și tufișurile. Golurile se umplu din DTM. Punctele aberante (> 20 m peste teren: păsări, zgomot), celulele izolate în mare (stropi, bărci) și vârfurile izolate se elimină. Textura e ortofoto PNOA 25 cm.
- **Marea** arată fundul estimat din satelit (`sdb_cal_safe`, conservator, calibrat cu ICESat-2), netezit pe ~2 m. Unde fundul nu se vede, e pus la 18 m (ICESat-2: > 17.4 m).

**Apa** se comportă ca apa reală. Privită de sus e transparentă și se vede fundul; privită din lateral devine opacă și reflectă cerul (efect Fresnel). Are valuri mici animate și sclipirea soarelui. Tot ce e sub nivelul mării se colorează în albastru închis, mai tare cu adâncimea.

Limitări:
- Pe pereții verticali, textura e întinsă (ortofoto e luat de sus).
- Surplombele nu există în model, pentru că are o singură cotă pe celulă.
- Fundul mării e o estimare din satelit cu eroare de 1–3 m, iar lângă perete e extrapolat.

**Norul de puncte** conține punctele LiDAR din clasele 1–6, plus 12 (suprapunerea benzilor de zbor) peste 0.5 m, cu culorile RGB din LAZ-ul PNOA. Se elimină punctele aberante, cele fără culoare și punctele joase izolate.

Punctele sunt desenate ca **discuri orientate pe suprafață** („surfels”). Normala vine din PCA pe 10 vecini, iar raza e ~0.9 × distanța medie la vecini (0.12–0.9 m). Fiecare disc e umbrit după orientare. Rezultatul e o suprafață continuă, apropiată vizual de Gaussian splatting.

Splatting adevărat (Postshot și altele) cere fotografii din multe unghiuri, de exemplu un zbor cu drona, pe care LiDAR-ul aerian nu le are. Unde LiDAR-ul are puține puncte (pereți verticali), discurile nu pot inventa date.

three.js (~1.2 MB, ~300 KB comprimat de CDN) se încarcă abia la prima deschidere 3D.

Zonele albastre din interiorul uscatului sunt **apă reală**: caletele, plajele, apa din umbra pereților sau peșterile marine prăbușite („avenc”, de ex. la ~30 m est de punctul #29). LiDAR-ul nu primește ecou de la apă, iar punctele de apă nu sunt desenate, așa că acolo se vede planul apei.

Datele aplicației sunt în `spots.js` / `spots.geojson`, generate de `export_app.py`.

### Ortofoto 25 cm – `ortho/`
- `pnoa_ortho_25cm.tif` – ortofoto RGB pentru zona LiDAR + 20 m
- `ortho_coast_class_25cm.tif` – clasificare în fâșia de mare de până la 30 m de țărm (primul 1 m e ignorat). Clasele: 1 apă cu fund vizibil, 2 apă adâncă, 3 spumă, 4 stâncă la suprafață, 5 obiect întunecat submers. Reguli de culoare: în apă roșul e cu 35–45 sub albastru, pe stâncă e aproape egal; spuma e albă și nesaturată; obiectele submerse sunt pete cu < 65% din luminozitatea fundului din jur (fereastră de ~10 m), doar unde fundul e luminos.
- `ortho_*_frac_1m.tif` – fracția fiecărei clase pe celulele LiDAR de 1 m

Limitări: o singură zi (mai 2024), cu valurile și luminozitatea de atunci. Peste apă adâncă sau întunecată stâncile submerse nu se văd. Textura valurilor poate ascunde fundul pe promontoriile expuse.

### Calibrarea adâncimii cu ICESat-2 – `icesat2/`
- `atl24_photons.gpkg` / `.parquet` – fotonii de fund ATL24, cu refracția corectată; adâncimea = `surface_h - ortho_h`
- `atl24_photons_utm31n.csv` – aceiași fotoni în EPSG:32631, folosiți la calibrare
- `calibration_report.json` – coeficienții și erorile modelelor

Am testat 3 modele pe fiecare dată Planet: Stumpf liniar, Stumpf pătratic și Lyzenga cu 3 benzi (log-liniar). Fiecare eșantion are o pondere egală pe intervale de 5 m, altfel fundurile de 15–20 m (majoritare) ar domina ajustarea și modelul ar supraestima adâncimea în apa mică. Se calibrează doar pe pixelii cu fund vizibil. Validarea s-a făcut lăsând deoparte, pe rând, câte o trecere ICESat-2 întreagă:

| Dată | Model ales | RMSE total | R² | RMSE / bias 0–5 m | RMSE / bias 5–10 m | Marja folosită (apă < 10 m) |
|---|---|---|---|---|---|---|
| 24 sep 2026 | Stumpf pătratic | 1.93 m | 0.76 | 0.81 / +0.40 m (n=15) | 1.87 / +0.05 m (n=101) | 1.77 m |
| 14 oct 2026 | Lyzenga | 1.95 m | 0.75 | 1.63 / +1.07 m (n=15) | 2.83 / +0.40 m (n=76) | 2.67 m |
| 22 oct 2026 | Lyzenga | 1.40 m | 0.80 | – | 1.01 / +0.40 m (n=19) | 1.01 m |

Bias pozitiv înseamnă că modelul vede apa mai adâncă decât e în realitate.

ICESat-2 confirmă și clasele de fund: nisip luminos ≈ 3–12 m (mediana 8 m), fund vizibil ≈ 13–20 m, apă optic adâncă **> 17.4 m** (percentila 5). Puținii fotoni de pe fund întunecat sunt la ~21–22 m, adică Posidonia adâncă.

## Limitări (importante pentru siguranță)
1. **Adâncimea e calibrată, dar are încă o eroare de ~1–2.7 m** în apa sub 10 m. Avem doar 15 eșantioane ICESat-2 sub 5 m, deci zona cea mai critică e cel mai slab acoperită. De aceea pentru siguranță se folosește `sdb_cal_safe` / `depth_est_m`, din care am scăzut deja eroarea. Peste fund întunecat (Posidonia, stâncă cu alge) modelul nu se aplică și punctul primește „Atenție”. Fotonii ICESat-2 sunt din 2018–2026, iar imaginile din 2026; nisipul se poate muta între timp.
2. **Primii ~5–15 m de lângă perete** sunt afectați de lumina reflectată de stâncă și de rezoluția de 3 m. Adâncimea de lângă perete este dedusă din apa aflată puțin mai în larg (`depth_read_offshore_m`). Ortofoto de 25 cm vede stâncile la suprafață, pragurile și bolovanii pe fund de nisip, dar **nu vede bolovanii în apă adâncă sau întunecată**.
3. LiDAR-ul topografic (NIR) nu pătrunde în apă și nu vede surplombele.
4. Imaginile sunt din sept–oct 2026; nisipul se mută după furtuni.
5. Clasificarea e un **filtru de pre-selecție**. Niciun loc nu trebuie sărit fără verificarea adâncimii la fața locului (scufundare/sondă) și fără să fie cineva în apă.

## Pași următori recomandați (date gratuite)
- **Validarea adâncimii lângă stânci**: Ecocartografías MITECO pentru Mallorca (batimetrie multibeam de coastă) – ar acoperi exact zona de 0–10 m de lângă pereți, unde ICESat-2 are puține măsurători. EMODnet Bathymetry dă contextul general.
- **Tipul fundului**: hărțile de Posidonia oceanica (Govern de les Illes Balears / EMODnet Seabed Habitats).
- **Valuri, curenți și temperatură în timp real**: SOCIB (sistemul de observare costieră al Balearelor), Puertos del Estado (geamanduri), Copernicus Marine (prognoze de valuri și temperatura mării), Open-Meteo Marine API.
- **Acces**: OpenStreetMap (poteci, parcări), ortofoto PNOA 25 cm.
- **Calitatea apei de îmbăiere**: datele EEA / Ministerio de Sanidad (Náyade) pentru plajele monitorizate.

// Macheta 3D a unui punct de saritura: modelul texturat (suprafata LiDAR + ortofoto, fundul marii din satelit) si/sau
// norul de puncte LiDAR, curba saltului, intrarea in apa si traseul de inot pana la iesire.
// Datele vin din dale comune de 50 m (tiles/, scripts/export_tiles.py): macheta cere doar dalele din cercul ei,
// le asambleaza intr-un singur model, iar punctele vecine refolosesc dalele deja descarcate.
// three.js se incarca doar la prima deschidere.
// Coordonate locale: origine = punctul de desprindere la nivelul marii; three: x = est, y = sus, z = -nord.

const $ = id => document.getElementById(id);
const G = 9.81, KICK = 1.5;          // m/s^2; viteza verticala initiala tipica la desprindere (m/s)

function hasWebGL() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
  catch (e) { return false; }
}
if (!hasWebGL()) window.NO3D = true;

let T = null, Orbit = null, ctx = null, tIndex = null, current = null, seq = null, raf = 0;
const tcache = new Map();            // url -> Promise (fisierele dalelor, comune tuturor machetelor)
const NEAR_R = 38;                   // m: in jurul saltului se descarca si punctele de detaliu (.p1)
// moduri: hibrid (model 3D solid + discurile norului de puncte deasupra), model 3D, doar puncte
const MODES = ["hybrid", "model", "cloud"];
const MODE_NAME = { hybrid: "◐ Hibrid", model: "⛰ Model 3D", cloud: "⁘ Puncte" };
let mode = (() => { try { const m = localStorage.getItem("v3dmode"); return MODES.includes(m) ? m : "hybrid"; }
                    catch (e) { return "hybrid"; } })();

async function loadIndex() {
  if (!tIndex) tIndex = Promise.all([fetch("tiles/index.json").then(r => r.json()),
                                     fetch("tiles/spots.json").then(r => r.json())])
    .then(([idx, spots]) => ({ idx, spots }));
  return tIndex;
}
const getBuf = url => {
  if (!tcache.has(url)) tcache.set(url, fetch(url).then(r => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.arrayBuffer(); }));
  return tcache.get(url);
};
const getImg = url => {
  if (!tcache.has(url)) tcache.set(url, (async () => { const im = new Image(); im.src = url; await im.decode(); return im; })());
  return tcache.get(url);
};
// dalele care ating cercul machetei; "near" = cele de langa salt (primesc si punctele de detaliu)
function tilesFor(meta, I) {
  const TS = I.idx.tile, [ox, oy] = meta.origin, [cx, cy, R] = meta.circle;
  const CX = ox + cx, CY = oy + cy, MX = ox + meta.entry[0] / 2, MY = oy + meta.entry[1] / 2;
  const hits = (ix, iy, x, y, r) => {
    const ex = ix * TS, ey = iy * TS;
    const dx = Math.max(ex - x, 0, x - ex - TS), dy = Math.max(ey - y, 0, y - ey - TS);
    return dx * dx + dy * dy <= r * r;
  };
  const all = [], near = new Set();
  for (let ix = Math.floor((CX - R) / TS); ix <= Math.floor((CX + R) / TS); ix++)
    for (let iy = Math.floor((CY - R) / TS); iy <= Math.floor((CY + R) / TS); iy++) {
      const k = `${ix}_${iy}`;
      if (!(k in I.idx.tiles) || !hits(ix, iy, CX, CY, R)) continue;
      all.push([ix, iy, k]);
      if (hits(ix, iy, MX, MY, NEAR_R)) near.add(k);
    }
  return { all, near };
}
async function fetchBase(id) {
  const I = await loadIndex();
  const { all, near } = tilesFor(I.spots[id], I);
  const pts = mode !== "model";
  return Promise.all(all.map(([, , k]) => {
    const [n0, n1] = I.idx.tiles[k];
    return Promise.all([getBuf(`tiles/${k}.h`), getImg(`tiles/${k}.jpg`),
      pts && n0 ? getBuf(`tiles/${k}.p0`) : null, pts && n1 && near.has(k) ? getBuf(`tiles/${k}.p1`) : null]);
  }));
}
window.prefetch3D = p => { loadIndex(); import("three").catch(() => {}); fetchBase(p.id).catch(() => null); return null; };

// asamblarea machetei din dale: o singura grila de cote, o singura textura, un singur set de puncte
async function assemble(meta, id) {
  const I = await loadIndex();
  const TS = I.idx.tile, U = I.idx.unit, [ox, oy] = meta.origin, [cx, cy, R] = meta.circle;
  const { all, near } = tilesFor(meta, I);
  const data = await fetchBase(id);
  // cote: grila la 1 m (2 m pentru machete foarte mari), aliniata la metri intregi
  const res = Math.max(1, Math.ceil(2 * R / 300));
  const X0 = Math.floor(ox + cx - R - 1), Y1 = Math.ceil(oy + cy + R + 1);
  const nx = Math.floor((2 * R + 2) / res) + 2, ny = nx;
  const Hq = new Int16Array(nx * ny).fill(Math.round(-6 / U));
  const tH = new Map(all.map(([, , k], i) => [k, new Int16Array(data[i][0])]));
  for (let r = 0; r < ny; r++) {
    const N = Y1 - r * res, iy = Math.floor(N / TS), row = (iy + 1) * TS - N;
    for (let c = 0; c < nx; c++) {
      const E = X0 + c * res, ix = Math.floor(E / TS), th = tH.get(`${ix}_${iy}`);
      if (th) Hq[r * nx + c] = th[row * (TS + 1) + (E - ix * TS)];
    }
  }
  const m = { x0: X0 - ox, y1: Y1 - oy, res, nx, ny, unit: U };
  // textura: fiecare dala desenata la locul ei (cel mult 4 px/m = 25 cm, cel mult 2048 px)
  const W = (nx - 1) * res, sc = Math.min(4, 2048 / W);
  const cv = document.createElement("canvas");
  cv.width = cv.height = Math.round(W * sc);
  const g2 = cv.getContext("2d");
  g2.fillStyle = "#1b5f78";
  g2.fillRect(0, 0, cv.width, cv.height);
  all.forEach(([ix, iy], i) => g2.drawImage(data[i][1], (ix * TS - X0) * sc, (Y1 - (iy + 1) * TS) * sc, TS * sc, TS * sc));
  // puncte: rare (.p0) peste tot, de detaliu (.p1) langa salt; pozitii mutate fata de desprindere
  let n = 0;
  all.forEach(([, , k], i) => { const [n0, n1] = I.idx.tiles[k]; if (data[i][2]) n += n0; if (data[i][3]) n += n1; });
  let cloud = null;
  if (n) {
    const out = new ArrayBuffer(n * 13);
    const Q = new Int16Array(out, 0, n * 3), Cc = new Uint8Array(out, n * 6, n * 3);
    const Nr = new Int8Array(out, n * 9, n * 3), Rd = new Uint8Array(out, n * 12, n);
    let o = 0;
    const put = (buf, cnt, ix, iy, coarse) => {
      const q = new Int16Array(buf, 0, cnt * 3), col = new Uint8Array(buf, cnt * 6, cnt * 3);
      const nr = new Int8Array(buf, cnt * 9, cnt * 3), rf = new Uint8Array(buf, cnt * 12, cnt);
      const rc = coarse ? new Uint8Array(buf, cnt * 13, cnt) : rf;
      const dx = Math.round((ix * TS + TS / 2 - ox) / U), dy = Math.round((iy * TS + TS / 2 - oy) / U);
      for (let j = 0; j < cnt; j++, o++) {
        Q[3 * o] = q[3 * j] + dx; Q[3 * o + 1] = q[3 * j + 1] + dy; Q[3 * o + 2] = q[3 * j + 2];
        Cc[3 * o] = col[3 * j]; Cc[3 * o + 1] = col[3 * j + 1]; Cc[3 * o + 2] = col[3 * j + 2];
        Nr[3 * o] = nr[3 * j]; Nr[3 * o + 1] = nr[3 * j + 1]; Nr[3 * o + 2] = nr[3 * j + 2];
        Rd[o] = rc[j];
      }
    };
    all.forEach(([ix, iy, k], i) => {
      const [n0, n1] = I.idx.tiles[k];
      const detail = !!data[i][3];
      if (data[i][2]) put(data[i][2], n0, ix, iy, !detail);   // fara detaliu: discuri rare, mai mari
      if (detail) put(data[i][3], n1, ix, iy, false);
    });
    cloud = { buf: out, meta: { n, unit: U } };
  }
  return { dem: Hq.buffer, canvas: cv, m, cloud };
}

async function init() {
  if (ctx) return ctx;
  T = await import("three");
  ({ OrbitControls: Orbit } = await import("three/addons/controls/OrbitControls.js"));
  T.ColorManagement.enabled = false;             // culorile LiDAR (sRGB) trec neschimbate
  const canvas = $("c3d");
  const renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 0);           // fundalul de "studio" vine din CSS
  renderer.outputColorSpace = T.LinearSRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));   // ecrane foarte dense: mai putini pixeli de calculat
  const scene = new T.Scene();                    // macheta pe masa: fara cer si fara ceata
  const camera = new T.PerspectiveCamera(40, 1, 1, 5000);
  const controls = new Orbit(camera, canvas);
  // macheta fixa: se poate doar roti, inclina putin si apropia putin; fara deplasare
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, rotateSpeed: 0.55,
    zoomSpeed: 0.6, minPolarAngle: 25 * Math.PI / 180, maxPolarAngle: 68 * Math.PI / 180,
    autoRotate: false, autoRotateSpeed: 0.35 });
  controls.addEventListener("start", () => { if (seq) seq.skip = true; controls.autoRotate = false; });
  const clip = { value: new T.Vector3(0, 0, 1e6) };   // (x, z, raza) ale cercului machetei, comun tuturor materialelor
  const water = new T.Mesh(new T.PlaneGeometry(1000, 1000), waterMaterial(clip));
  water.rotation.x = -Math.PI / 2;
  water.renderOrder = 2;
  scene.add(water);
  // lumina pentru modelul texturat (norul de puncte nu e afectat): cer + soare de dimineata din ESE
  scene.add(new T.HemisphereLight(0xffffff, 0x3c4650, 2.1));
  const sun = new T.DirectionalLight(0xfff4e0, 1.7);
  sun.position.set(120, 110, 50);
  scene.add(sun);
  const dyn = new T.Group();
  scene.add(dyn);
  ctx = { renderer, scene, camera, controls, dyn, canvas, water, clip };
  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    // centrul imaginii = centrul zonei libere (deasupra fisei pe telefon, in stanga ei pe ecran mare)
    const sheet = $("sheet");
    if (w <= 760) {
      const peek = $("sheetHandle").offsetHeight || 120;
      camera.aspect = w / (h + peek);
      camera.setViewOffset(w, h + peek, 0, peek, w, h);
      ctx.free = { w, h: h - peek, fullH: h + peek };
    } else {
      const side = (sheet.offsetWidth || 380) + 14;
      camera.aspect = (w + side) / h;
      camera.setViewOffset(w + side, h, side, 0, w, h);
      ctx.free = { w: w - side, h, fullH: h };
    }
    camera.updateProjectionMatrix();
  };
  window.addEventListener("resize", resize);
  ctx.resize = resize;
  return ctx;
}

// ------------------------------------------------------------------ apa
// Ca apa reala: privita de sus e transparenta (se vede fundul), privita din lateral devine opaca si reflecta cerul
// (Fresnel); valuri mici animate (suma de sinusoide -> normale) si sclipirea soarelui.
function waterMaterial(clip) {
  const m = new T.ShaderMaterial({
    transparent: true, depthWrite: false, fog: true,
    uniforms: T.UniformsUtils.merge([T.UniformsLib.fog, {
      uTime: { value: 0 }, uMinA: { value: 0.35 },
      uDeep: { value: new T.Color(0x0b4660) }, uShallow: { value: new T.Color(0x23859e) },
      uSky: { value: new T.Color(0xb9d8ea) }, uSun: { value: new T.Vector3(0.62, 0.55, 0.26).normalize() } }]),
    vertexShader: `
      varying vec3 vW;
      #include <fog_pars_vertex>
      void main() {
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vW = wp.xyz;
        vec4 mvPosition = viewMatrix * wp;
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader: `
      uniform float uTime, uMinA;
      uniform vec3 uDeep, uShallow, uSky, uSun, uClip;
      varying vec3 vW;
      #include <fog_pars_fragment>
      float wav(vec2 p, float t) {
        return sin(dot(p, vec2(0.21, 0.13)) + t * 0.9) * 0.50
             + sin(dot(p, vec2(-0.17, 0.29)) * 1.3 + t * 1.3) * 0.35
             + sin(dot(p, vec2(0.37, -0.11)) * 2.1 + t * 1.7) * 0.20
             + sin(dot(p, vec2(-0.60, -0.45)) * 3.3 + t * 2.3) * 0.12
             + sin(dot(p, vec2(0.90, 0.70)) * 5.1 + t * 3.1) * 0.06;
      }
      void main() {
        if (distance(vW.xz, uClip.xy) > uClip.z) discard;
        vec2 p = vW.xz;
        float e = 0.2;
        float dx = wav(p + vec2(e, 0.0), uTime) - wav(p - vec2(e, 0.0), uTime);
        float dz = wav(p + vec2(0.0, e), uTime) - wav(p - vec2(0.0, e), uTime);
        vec3 n = normalize(vec3(-dx * 0.55, 1.0, -dz * 0.55));
        vec3 v = normalize(cameraPosition - vW);
        float c = clamp(dot(n, v), 0.0, 1.0);
        float fres = 0.02 + 0.98 * pow(1.0 - c, 5.0);
        float graze = 1.0 - clamp(v.y, 0.0, 1.0);          // 0 privit de sus, 1 privit din lateral
        vec3 col = mix(uShallow, uDeep, 0.35 + 0.4 * graze);
        col = mix(col, uSky, clamp(fres * 1.1, 0.0, 0.85));
        vec3 h = normalize(uSun + v);
        col += vec3(1.0, 0.97, 0.9) * pow(max(dot(n, h), 0.0), 220.0) * 0.9;
        float a = mix(uMinA, 0.97, smoothstep(0.15, 0.75, graze));
        gl_FragColor = vec4(col, a);
        #include <fog_fragment>
      }`
  });
  m.uniforms.uClip = clip;
  return m;
}

// tot ce e sub nivelul marii se coloreaza treptat in albastru inchis (lumina scade cu adancimea)
function underwaterTint(mat) {
  mat.onBeforeCompile = sh => {
    sh.uniforms.uClip = ctx.clip;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying float vH;\nvarying vec2 vXZ;")
      .replace("#include <worldpos_vertex>", "#include <worldpos_vertex>\nvH = transformed.y;\nvXZ = (modelMatrix * vec4(transformed, 1.0)).xz;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vH;\nvarying vec2 vXZ;\nuniform vec3 uClip;")
      .replace("#include <clipping_planes_fragment>", "if (distance(vXZ, uClip.xy) > uClip.z) discard;\n#include <clipping_planes_fragment>")
      .replace("#include <dithering_fragment>", `#include <dithering_fragment>
        if (vH < 0.0) {
          float k = clamp(-vH / 10.0, 0.0, 1.0);
          gl_FragColor.rgb = mix(gl_FragColor.rgb * vec3(0.55, 0.82, 0.9), vec3(0.03, 0.2, 0.28), 0.15 + 0.68 * k);
        }`);
  };
  return mat;
}

// ------------------------------------------------------------------ geometrie
const V = (x, y, z) => new T.Vector3(x, z, -y);   // (est, nord, sus) -> three

function buildCloud(buf, meta) {
  if (meta.fmt === 2) return buildSplats(buf, meta);
  const n = meta.n, u = meta.unit;
  const q = new Int16Array(buf, 0, n * 3);
  const col = new Uint8Array(buf, n * 6, n * 3);
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[3 * i] = q[3 * i] * u;
    pos[3 * i + 1] = q[3 * i + 2] * u;
    pos[3 * i + 2] = -q[3 * i + 1] * u;
  }
  const g = new T.BufferGeometry();
  g.setAttribute("position", new T.BufferAttribute(pos, 3));
  g.setAttribute("color", new T.BufferAttribute(col, 3, true));
  const m = new T.PointsMaterial({ size: 1.25, vertexColors: true, sizeAttenuation: true, map: discTexture(), alphaTest: 0.5 });
  const pts = new T.Points(g, m);
  pts.userData.isCloud = true;
  return pts;
}

// discuri orientate pe suprafata ("surfels"): fiecare punct LiDAR devine un disc perpendicular pe normala locala,
// cu raza ~ distanta la vecini -> suprafata continua, fara goluri, cu umbrire dupa orientare
function buildSplats(buf, meta) {
  const n = meta.n, u = meta.unit;
  const q = new Int16Array(buf, 0, n * 3);
  const col = new Uint8Array(buf, n * 6, n * 3);
  const nr = new Int8Array(buf, n * 9, n * 3);
  const rd = new Uint8Array(buf, n * 12, n);
  const pos = new Float32Array(n * 3), nrm = new Float32Array(n * 3), rad = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    pos[3 * i] = q[3 * i] * u; pos[3 * i + 1] = q[3 * i + 2] * u; pos[3 * i + 2] = -q[3 * i + 1] * u;
    nrm[3 * i] = nr[3 * i] / 127; nrm[3 * i + 1] = nr[3 * i + 2] / 127; nrm[3 * i + 2] = -nr[3 * i + 1] / 127;
    rad[i] = rd[i] * u;
  }
  const g = new T.InstancedBufferGeometry();
  g.setAttribute("position", new T.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.setAttribute("iPos", new T.InstancedBufferAttribute(pos, 3));
  g.setAttribute("iCol", new T.InstancedBufferAttribute(col, 3, true));
  g.setAttribute("iNrm", new T.InstancedBufferAttribute(nrm, 3));
  g.setAttribute("iRad", new T.InstancedBufferAttribute(rad, 1));
  g.instanceCount = n;
  const m = new T.ShaderMaterial({
    fog: true,
    uniforms: T.UniformsUtils.merge([T.UniformsLib.fog, { uScale: { value: 1.15 }, uLift: { value: 0.0 }, uMinUp: { value: 0.0 },
      uSun: { value: new T.Vector3(0.62, 0.55, 0.26).normalize() } }]),
    vertexShader: `
      attribute vec3 iPos, iCol, iNrm;
      attribute float iRad;
      uniform float uScale, uLift, uMinUp;
      uniform vec3 uSun;
      varying vec3 vCol;
      varying vec2 vUv;
      varying vec2 vXZ;
      #include <fog_pars_vertex>
      void main() {
        vXZ = iPos.xz;
        vec3 nn = normalize(iNrm);
        vec3 t = normalize(abs(nn.y) < 0.95 ? cross(nn, vec3(0.0, 1.0, 0.0)) : cross(nn, vec3(1.0, 0.0, 0.0)));
        vec3 b = cross(nn, t);
        vec3 wp = iPos + (t * position.x + b * position.y) * iRad * uScale;
        vec4 mvLift = viewMatrix * vec4(wp, 1.0);
        vUv = position.xy;
        // culoarea LiDAR are deja umbrele din ortofoto; adaugam relieful dupa orientarea discului
        float sh = 0.72 + 0.38 * abs(dot(nn, uSun));
        // umbrele din ortofoto sunt foarte inchise: le deschidem usor (gamma 0.8) ca sa se potriveasca cu modelul
        vCol = pow(iCol, vec3(0.8)) * sh;
        vec4 mvPosition = mvLift;
        mvPosition.xyz -= normalize(mvPosition.xyz) * uLift;
        gl_Position = projectionMatrix * mvPosition;
        // in modul hibrid, pe pereti abrupti (culoare luata din umbra ortofoto) ramane doar modelul
        if (abs(nn.y) < uMinUp) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        #include <fog_vertex>
      }`,
    fragmentShader: `
      varying vec3 vCol;
      varying vec2 vUv;
      varying vec2 vXZ;
      uniform vec3 uClip;
      #include <fog_pars_fragment>
      void main() {
        if (dot(vUv, vUv) > 1.0 || distance(vXZ, uClip.xy) > uClip.z) discard;
        gl_FragColor = vec4(vCol, 1.0);
        #include <fog_fragment>
      }`,
    side: T.DoubleSide
  });
  m.uniforms.uClip = ctx.clip;
  const mesh = new T.Mesh(g, m);
  mesh.frustumCulled = false;
  mesh.userData.isSplats = true;
  return mesh;
}

let _disc = null;
function discTexture() {             // puncte rotunde (discuri) in loc de patrate
  if (_disc) return _disc;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#fff";
  g.beginPath(); g.arc(32, 32, 30, 0, Math.PI * 2); g.fill();
  _disc = new T.CanvasTexture(c);
  return _disc;
}

// model 3D: grila de cote (randul 0 = nord) cu ortofoto drapat; marea = fundul estimat din satelit
async function buildTerrain([dem, src], m) {
  const W = (m.nx - 1) * m.res, H = (m.ny - 1) * m.res;
  const g = new T.PlaneGeometry(W, H, m.nx - 1, m.ny - 1);
  g.rotateX(-Math.PI / 2);                        // (x, y, 0) -> (x, 0, -y): randul 0 ajunge la nord
  const q = new Int16Array(dem);
  const pos = g.attributes.position.array;
  for (let k = 0; k < m.nx * m.ny; k++) pos[3 * k + 1] = q[k] * m.unit;
  g.translate(m.x0 + W / 2, 0, -(m.y1 - H / 2));
  g.computeVertexNormals();
  const tex = new T.CanvasTexture(src);
  tex.colorSpace = T.NoColorSpace;
  tex.anisotropy = Math.min(ctx.renderer.capabilities.getMaxAnisotropy(), 8);
  tex.needsUpdate = true;
  const mesh = new T.Mesh(g, underwaterTint(new T.MeshLambertMaterial({ map: tex })));
  return mesh;
}

// cota (bilinear) din grila modelului, in coordonate three (x = est, z = -nord)
function heightSampler(dem, m) {
  const q = new Int16Array(dem);
  return (x, z) => {
    const c = Math.min(Math.max((x - m.x0) / m.res, 0), m.nx - 1.001);
    const r = Math.min(Math.max((m.y1 + z) / m.res, 0), m.ny - 1.001);
    const c0 = Math.floor(c), r0 = Math.floor(r), fc = c - c0, fr = r - r0;
    const at = (rr, cc) => q[rr * m.nx + cc] * m.unit;
    return (at(r0, c0) * (1 - fc) + at(r0, c0 + 1) * fc) * (1 - fr) + (at(r0 + 1, c0) * (1 - fc) + at(r0 + 1, c0 + 1) * fc) * fr;
  };
}

// macheta: marginea taiata (sectiune prin stanca, cu straturi) + coloana de apa ca rasina + soclul de lemn
function buildDiorama(hAt, cx, cz, R, yOff) {
  const grp = new T.Group();
  const N = 240, ROWS = 7;
  const tops = [];
  for (let i = 0; i <= N; i++) {
    const a = i / N * Math.PI * 2;
    const x = cx + R * Math.cos(a), z = cz + R * Math.sin(a);
    tops.push([x, hAt(x, z) + yOff, z]);
  }
  const minH = Math.min(...tops.map(t => t[1]));
  const base = Math.min(minH, -3) - Math.max(R * 0.05, 3);
  // stanca: ROWS randuri intre cota de sus si baza, culori in straturi (calcar deschis -> roca inchisa)
  const P = [], Cc = [], I = [];
  for (let i = 0; i <= N; i++) {
    const [x, top, z] = tops[i];
    const t0 = top;                                // pe mare, marginea porneste de la fund
    for (let k = 0; k <= ROWS; k++) {
      const f = k / ROWS, y = t0 + (base - t0) * f;
      P.push(x, y, z);
      const band = 0.94 + 0.09 * Math.sin(y * 1.7 + 0.6 * Math.sin(i * 0.21)) + (k % 2 ? -0.03 : 0.02);
      const top_ = top >= 0 ? [0.70, 0.64, 0.54] : [0.62, 0.57, 0.47];
      const bot = [0.24, 0.21, 0.19];
      Cc.push(...top_.map((v, j) => (v + (bot[j] - v) * Math.pow(f, 0.8)) * band));
    }
  }
  for (let i = 0; i < N; i++) for (let k = 0; k < ROWS; k++) {
    const a = i * (ROWS + 1) + k, b = (i + 1) * (ROWS + 1) + k;
    I.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const g = new T.BufferGeometry();
  g.setAttribute("position", new T.Float32BufferAttribute(P, 3));
  g.setAttribute("color", new T.Float32BufferAttribute(Cc, 3));
  g.setIndex(I);
  g.computeVertexNormals();
  grp.add(new T.Mesh(g, new T.MeshLambertMaterial({ vertexColors: true, side: T.DoubleSide })));
  // apa: de la fund pana la suprafata, translucida (ca rasina intr-o macheta)
  const WP = [], WC = [], WI = [];
  for (let i = 0; i <= N; i++) {
    const [x, top, z] = tops[i];
    const bottom = Math.min(top, 0);
    WP.push(x, 0, z, x, bottom, z);
    WC.push(0.16, 0.52, 0.62, 0.03, 0.2, 0.3);
  }
  for (let i = 0; i < N; i++) { const a = 2 * i, b = 2 * i + 2; WI.push(a, b, a + 1, b, b + 1, a + 1); }
  const wg = new T.BufferGeometry();
  wg.setAttribute("position", new T.Float32BufferAttribute(WP, 3));
  wg.setAttribute("color", new T.Float32BufferAttribute(WC, 3));
  wg.setIndex(WI);
  const wm = new T.Mesh(wg, new T.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.72,
    side: T.DoubleSide, depthWrite: false }));
  wm.renderOrder = 1;
  grp.add(wm);
  // soclul (lemn inchis) si o banda subtire deschisa sub teren
  const sh = Math.max(R * 0.07, 4);
  const plinth = new T.Mesh(new T.CylinderGeometry(R * 1.035, R * 1.07, sh, 128),
    new T.MeshLambertMaterial({ color: 0x3b2d24 }));
  plinth.position.set(cx, base - sh / 2, cz);
  grp.add(plinth);
  const lipRing = new T.Mesh(new T.CylinderGeometry(R * 1.036, R * 1.036, Math.max(R * 0.008, 0.5), 128, 1, true),
    new T.MeshLambertMaterial({ color: 0xc9b8a0, side: T.DoubleSide }));
  lipRing.position.set(cx, base + 0.01, cz);
  grp.add(lipRing);
  grp.userData.base = base;
  return grp;
}

async function buildBase(meta, id) {
  let obj;
  const c = meta.circle || [0, 0, 60];
  ctx.clip.value.set(c[0], -c[1], c[2]);         // (x = est, z = -nord, raza)
  const A = await assemble(meta, id);
  if (mode === "hybrid" && A.cloud) {
    // suprafata texturata da "corpul" (nu se mai vede prin ea), discurile LiDAR dau textura deasupra;
    // polygonOffset impinge suprafata putin in spate, ca discurile de pe ea sa castige la adancime
    obj = new T.Group();
    const terr = await buildTerrain([A.dem, A.canvas], A.m);
    Object.assign(terr.material, { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 4 });
    terr.position.y = -0.25;                     // suprafata (cota maxima pe celula) putin sub puncte
    obj.add(terr);
    const spl = buildSplats(A.cloud.buf, A.cloud.meta);
    spl.userData.scaleMin = 0.8;                 // discuri mai mici: macheta se priveste de la distanta
    if (spl.material.uniforms) {
      spl.material.uniforms.uLift.value = 0.35;   // discurile in fata suprafetei
      spl.material.uniforms.uMinUp.value = 0.5;   // fara discuri pe pereti mai abrupti de ~60 grade
    }
    obj.add(spl);
  } else if (mode !== "cloud" || !A.cloud) obj = await buildTerrain([A.dem, A.canvas], A.m);
  else obj = buildSplats(A.cloud.buf, A.cloud.meta);
  // marginea machetei, din cotele asamblate (in toate modurile)
  const yOff = mode === "hybrid" && A.cloud ? -0.25 : 0;
  const dio = buildDiorama(heightSampler(A.dem, A.m), c[0], -c[1], c[2], yOff);
  if (!obj.isGroup) { const g = new T.Group(); g.add(obj); obj = g; }
  obj.add(dio);
  obj.userData.base = true;
  ctx.water.material.uniforms.uMinA.value = mode === "cloud" ? 0.6 : 0.35;
  return obj;
}
function modeLabel() {
  $("mode3d").textContent = MODE_NAME[mode];
  $("mode3d").title = "Schimba modul: Hibrid / Model 3D / Puncte";
}
function disposeObj(o) {
  o.traverse(x => {
    if (x.geometry) x.geometry.dispose();
    if (x.material) { if (x.material.map) x.material.map.dispose(); x.material.dispose(); }
  });
}

function jumpCurve(meta) {
  const h = meta.takeoff[2];
  const [ex, ey] = meta.entry;
  const D = Math.hypot(ex, ey);
  const tf = (KICK + Math.sqrt(KICK * KICK + 2 * G * h)) / G;          // timpul de cadere
  const vh = D / tf, vz = KICK - G * tf;
  const pts = [];
  for (let k = 0; k <= 48; k++) {
    const t = tf * k / 48, f = t / tf;
    pts.push(V(ex * f, ey * f, Math.max(h + KICK * t - G * t * t / 2, 0)));
  }
  return { curve: new T.CatmullRomCurve3(pts), tf, speed: Math.hypot(vh, vz) * 3.6, D };
}

function swimCurve(meta) {
  if (!meta.swim || meta.swim.length < 2) return null;
  const path = new T.CurvePath();
  let L = 0;
  for (let i = 0; i < meta.swim.length - 1; i++) {
    const a = meta.swim[i], b = meta.swim[i + 1];
    path.add(new T.LineCurve3(V(a[0], a[1], 0.25), V(b[0], b[1], 0.25)));
    L += Math.hypot(b[0] - a[0], b[1] - a[1]);
  }
  return { path, L };
}

function tube(curve, segs, radius, color) {
  const g = new T.TubeGeometry(curve, segs, radius, 8, false);
  const m = new T.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, depthTest: true });
  const mesh = new T.Mesh(g, m);
  mesh.renderOrder = 3;
  g.setDrawRange(0, 0);
  mesh.userData.total = g.index.count;
  return mesh;
}
const grow = (mesh, f) => mesh.geometry.setDrawRange(0, Math.floor(mesh.userData.total * Math.min(Math.max(f, 0), 1) / 3) * 3);

// ------------------------------------------------------------------ etichete HTML care urmaresc puncte 3D
// Etichetele stau la distanta de punctul lor, legate printr-o linie subtire, ca sa nu acopere saritura:
// desprinderea in partea opusa saltului, intrarea in prelungirea lui, iesirea deasupra; daca se suprapun,
// se imping una pe alta pe verticala.
const labels = [];
const SVGNS = "http://www.w3.org/2000/svg";
function label(html, cls, pos, kind) {
  const el = document.createElement("div");
  el.className = "lbl " + (cls || "");
  el.innerHTML = html;
  $("labels").appendChild(el);
  let svg = $("leaders");
  if (!svg) {
    svg = document.createElementNS(SVGNS, "svg");
    svg.id = "leaders";
    $("labels").appendChild(svg);
  }
  const line = document.createElementNS(SVGNS, "line");
  const dot = document.createElementNS(SVGNS, "circle");
  dot.setAttribute("r", "3");
  svg.append(line, dot);
  const o = { el, pos, on: false, kind, line, dot };
  labels.push(o);
  return o;
}
function placeLabels() {
  const { camera, canvas } = ctx;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const fw = ctx.free && w > 760 ? ctx.free.w : w;           // pe ecran mare, fisa ocupa dreapta
  const fh = ctx.free && w <= 760 ? ctx.free.h : h;          // pe telefon, fisa ocupa jos
  const items = [];
  for (const l of labels) {
    const v = l.pos.clone().project(camera);
    const vis = l.on && v.z < 1 && Math.abs(v.x) < 1.2 && Math.abs(v.y) < 1.2;
    l.el.classList.toggle("show", vis);
    l.line.style.display = l.dot.style.display = vis ? "" : "none";
    if (vis) items.push({ l, ax: (v.x + 1) / 2 * w, ay: (1 - v.y) / 2 * h, w: l.el.offsetWidth, h: l.el.offsetHeight });
  }
  if (!items.length) return;
  // directia saltului pe ecran (de la desprindere la intrare)
  const tk = items.find(i => i.l.kind === "take"), en = items.find(i => i.l.kind === "entry");
  let sx = 1, sy = 0;
  if (tk && en) { const L = Math.hypot(en.ax - tk.ax, en.ay - tk.ay) || 1; sx = (en.ax - tk.ax) / L; sy = (en.ay - tk.ay) / L; }
  const side = sx >= 0 ? 1 : -1;
  const GAP = 52;
  for (const it of items) {
    let dx = 0, dy = -1;
    if (it.l.kind === "take") { dx = -side * 0.9; dy = -0.75; }      // sus, in partea opusa saltului
    else if (it.l.kind === "entry") { dx = side * 0.9; dy = 0.55; }  // jos, in prelungirea saltului
    const n = Math.hypot(dx, dy);
    const cx = it.ax + dx / n * GAP, cy = it.ay + dy / n * GAP;
    it.x = dx > 0.2 ? cx : dx < -0.2 ? cx - it.w : cx - it.w / 2;
    it.y = cy - it.h / 2;
  }
  for (let k = 0; k < 24; k++) {             // separare: impinge pe verticala etichetele care se suprapun
    let moved = false;
    for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
      const a = items[i], b = items[j], pad = 6;
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) + pad;
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) + pad;
      if (ox > 0 && oy > 0) {
        const up = a.y + a.h / 2 <= b.y + b.h / 2 ? a : b, dn = up === a ? b : a;
        up.y -= oy / 2; dn.y += oy / 2; moved = true;
      }
    }
    if (!moved) break;
  }
  for (const it of items) {
    it.x = Math.min(Math.max(it.x, 6), fw - it.w - 6);
    it.y = Math.min(Math.max(it.y, 56), fh - it.h - 6);
    it.l.el.style.transform = `translate(${it.x}px, ${it.y}px)`;
    // linia: de la punct la cel mai apropiat punct al etichetei
    const px = Math.min(Math.max(it.ax, it.x), it.x + it.w), py = Math.min(Math.max(it.ay, it.y), it.y + it.h);
    it.l.line.setAttribute("x1", it.ax); it.l.line.setAttribute("y1", it.ay);
    it.l.line.setAttribute("x2", px); it.l.line.setAttribute("y2", py);
    it.l.dot.setAttribute("cx", it.ax); it.l.dot.setAttribute("cy", it.ay);
  }
}
function clearScene() {
  for (const o of [...ctx.dyn.children]) {
    ctx.dyn.remove(o);
    o.traverse(x => {
      if (x.geometry) x.geometry.dispose();
      if (x.material) { if (x.material.map) x.material.map.dispose(); x.material.dispose(); }
    });
  }
  labels.length = 0;
  $("labels").innerHTML = "";
}

// ------------------------------------------------------------------ animatia
const ease = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

function cameraMove(from, to, dur) {
  return { kind: "cam", from, to, dur };
}

function buildSequence(meta, p) {
  const { camera, controls, dyn } = ctx;
  const h = meta.takeoff[2];
  const J = jumpCurve(meta);
  const S = swimCurve(meta);
  const take = V(0, 0, h), entry = V(meta.entry[0], meta.entry[1], 0);
  // directia saltului (spre larg) si perpendiculara ei, in plan orizontal
  const fwd = new T.Vector3(entry.x - take.x, 0, entry.z - take.z);
  if (fwd.length() < 0.1) fwd.set(1, 0, 0);
  fwd.normalize();
  const side = new T.Vector3(-fwd.z, 0, fwd.x);
  const mid = take.clone().lerp(entry, 0.5).setY(h * 0.45);
  const view1 = {
    pos: mid.clone().addScaledVector(fwd, h * 1.5 + 22).addScaledVector(side, h * 0.8 + 10).setY(h * 0.75 + 7),
    tgt: mid
  };
  // macheta: camera fixa pe o sfera in jurul cercului, privind din larg, la ~38 grade deasupra orizontului
  const cc = meta.circle || [0, 0, 60];
  const R = cc[2], ctr = new T.Vector3(cc[0], Math.max(h * 0.3, 2), -cc[1]);
  const fr0 = ctx.free || { w: 1, h: 1, fullH: 1 };
  const kk = Math.tan(camera.fov * Math.PI / 360) / (fr0.fullH / 2);
  const half0 = Math.min(Math.atan(kk * fr0.w / 2), Math.atan(kk * fr0.h / 2));
  const D = Math.hypot(R * 1.08, h * 0.6 + R * 0.12) / Math.sin(half0) * 1.12;
  const dirAt = (az, el) => fwd.clone().applyAxisAngle(new T.Vector3(0, 1, 0), az).multiplyScalar(Math.cos(el)).setY(Math.sin(el));
  const home = { pos: ctr.clone().addScaledVector(dirAt(0.35, 38 * Math.PI / 180), D), tgt: ctr };
  const top = { pos: ctr.clone().addScaledVector(dirAt(-0.45, 55 * Math.PI / 180), D * 1.18), tgt: ctr };
  Object.assign(controls, { minDistance: D * 0.72, maxDistance: D * 1.12, autoRotate: false });
  const S_ = Math.min(Math.max(R / 50, 1), 3);    // marimea obiectelor dupa scara machetei
  // a doua incadrare: tot traseul (desprindere -> iesire), vazut oblic din larg
  let view2 = null;
  if (false) {
    // toata scena (desprindere -> iesire) incape in zona libera a ecranului, vazuta din larg sub ~50 grade
    const sphere = new T.Sphere();
    new T.Box3().setFromPoints([take, entry, ...meta.swim.map(q => V(q[0], q[1], 0))]).getBoundingSphere(sphere);
    const r = Math.max(sphere.radius, 18);
    // unghiurile (jumatate) ale zonei libere de pe ecran, cu pixeli patrati
    const fr = ctx.free || { w: 1, h: 1, fullH: 1 };
    const k = Math.tan(camera.fov * Math.PI / 360) / (fr.fullH / 2);
    const half = Math.min(Math.atan(k * fr.w / 2), Math.atan(k * fr.h / 2));
    const dist = r / Math.sin(half) * 1.1;
    const el = 50 * Math.PI / 180;
    const dir = fwd.clone().multiplyScalar(Math.cos(el)).addScaledVector(side, 0.25 * Math.cos(el)).setY(Math.sin(el)).normalize();
    const c = sphere.center.clone().setY(1);
    view2 = { pos: c.clone().addScaledVector(dir, dist), tgt: c };
  }
  // obiectele
  const arc = tube(J.curve, 96, Math.max(0.22, R / 120), 0xff7a1a);
  dyn.add(arc);
  const diver = new T.Mesh(new T.SphereGeometry(Math.max(0.6, R / 70), 16, 12), new T.MeshBasicMaterial({ color: 0xffd23f }));
  diver.visible = false;
  dyn.add(diver);
  const lip = new T.Mesh(new T.SphereGeometry(Math.max(0.55, R / 85), 16, 12), new T.MeshBasicMaterial({ color: 0xff7a1a }));
  lip.position.copy(take);
  dyn.add(lip);
  const splash = new T.Mesh(new T.RingGeometry(0.6 * S_, 1.0 * S_, 40), new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false }));
  splash.rotation.x = -Math.PI / 2;
  splash.position.copy(entry).setY(0.05);
  dyn.add(splash);
  let swimTube = null, pin = null, exitPos = null;
  if (S) {
    swimTube = tube(S.path, Math.min(Math.max(Math.round(S.L / 1.2), 24), 500), Math.max(0.35, R / 140), 0x00e5ff);
    dyn.add(swimTube);
    const e = meta.swim[meta.swim.length - 1];
    exitPos = V(e[0], e[1], 0);
    pin = new T.Mesh(new T.ConeGeometry(1.3 * S_, 3.2 * S_, 20), new T.MeshBasicMaterial({ color: 0x00e5ff }));
    pin.rotation.x = Math.PI;
    pin.position.copy(exitPos).setY(3.4 * S_);
    pin.visible = false;
    dyn.add(pin);
  }
  const esc = t => String(t ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const exitShort = (p.exit_type || "").replace(/^mal jos, aproape plat.*$/, "mal jos / plaja");
  const Ltake = label(`<b>Desprindere</b> · ${(p.height_m ?? h).toFixed(1)} m`, "jump", take.clone(), "take");
  const Lentry = label(`<b>Intrare</b> · ${J.tf.toFixed(1)} s · ${Math.round(J.speed)} km/h`, "jump", entry.clone(), "entry");
  const Lexit = S ? label(`<b>Iesire</b> · ~${Math.round(p.exit_dist_m ?? S.L)} m inot<br><small>${esc(exitShort)}</small>`,
    "swim", exitPos.clone(), "exit") : null;

  // pasii: [durata, functie(f in 0..1)]
  const steps = [
    [1.8, f => { const e = ease(f); camera.position.lerpVectors(top.pos, home.pos, e); controls.target.copy(ctr); }],
    [0.7, f => { Ltake.on = true; grow(arc, f); }],
    [J.tf, f => { diver.visible = true; diver.position.copy(J.curve.getPoint(f)); }],
    [0.9, f => { diver.visible = false; Lentry.on = true; splash.scale.setScalar(1 + f * 5); splash.material.opacity = 0.9 * (1 - f); }],
  ];
  if (S) {
    steps.push([Math.min(Math.max(S.L / 60, 1.2), 3.2), f => { grow(swimTube, f); }]);
    steps.push([0.4, f => { pin.visible = true; pin.position.y = (3.4 + (1 - f) * 4) * S_; Lexit.on = true; }]);
  }
  const finish = () => {   // utilizatorul a atins ecranul: tot desenul apare imediat, camera ramane a lui
    grow(arc, 1); Ltake.on = Lentry.on = true; diver.visible = false; splash.material.opacity = 0;
    if (S) { grow(swimTube, 1); pin.visible = true; pin.position.y = 3.4 * S_; Lexit.on = true; }
  };
  steps.push([0.01, () => { controls.autoRotate = true; }]);   // la final macheta se roteste lent, pana o atingi
  camera.position.copy(top.pos);
  controls.target.copy(ctr);
  return { steps, i: 0, t0: null, skip: false, finish, done: false, view1 };
}

function frame(now) {
  raf = requestAnimationFrame(frame);
  const { renderer, scene, camera, controls } = ctx;
  if (seq && !seq.done) {
    if (seq.skip) { seq.finish(); seq.done = true; }
    else {
      if (seq.t0 === null) seq.t0 = now;
      let [dur, fn] = seq.steps[seq.i];
      let f = (now - seq.t0) / 1000 / dur;
      fn(Math.min(f, 1));
      if (f >= 1) { seq.i++; seq.t0 = now; if (seq.i >= seq.steps.length) seq.done = true; }
    }
  }
  controls.enabled = !seq || seq.done;
  controls.update();
  ctx.water.material.uniforms.uTime.value = now / 1000;
  // puncte mai mari cand camera e departe, ca norul sa nu "dispara" in vederile de ansamblu
  let spl = null, cloud = null;
  ctx.dyn.traverse(o => { if (o.userData.isSplats) spl = o; else if (o.userData.isCloud) cloud = o; });
  if (spl) {                                   // departe: discuri putin mai mari (fara goluri)
    const lo = spl.userData.scaleMin ?? 1.15;
    spl.material.uniforms.uScale.value = Math.min(Math.max(camera.position.distanceTo(controls.target) / 220, lo), 1.25);
  }
  if (cloud) cloud.material.size = Math.min(Math.max(camera.position.distanceTo(controls.target) / 65, 1.25), 6.0);
  renderer.render(scene, camera);
  placeLabels();
}

// ------------------------------------------------------------------ deschidere / inchidere
// trecere prin negru intre harta si macheta
function dip(on, ms) {
  const f = $("fade");
  f.style.transitionDuration = (ms || (on ? 350 : 550)) + "ms";
  f.classList.toggle("on", on);
  return new Promise(r => setTimeout(r, ms || (on ? 360 : 560)));
}
window.dip = dip;

async function open3D(p, pre) {
  const v = $("v3d");
  current = p;
  const slow = setTimeout(() => { $("fadeMsg").textContent = "Se pregateste macheta…"; }, 450);
  const sh = window.sheetHtml(p);
  $("sheetHead").innerHTML = sh.head;
  $("sheetBody").innerHTML = sh.body;
  $("sheet").classList.remove("open");
  requestAnimationFrame(() => $("sheet").style.setProperty("--peek", ($("sheetHandle").offsetHeight + 2) + "px"));
  v.classList.add("on");
  v.setAttribute("aria-hidden", "false");
  $("loading3d").textContent = mode === "cloud" ? "Se incarca norul de puncte…" : "Se incarca modelul 3D…";
  $("loading3d").style.display = "block";
  if (!history.state || history.state.v3d !== p.id) history.pushState({ v3d: p.id }, "", `#punct-${p.id}`);
  try {
    const [c, I] = await Promise.all([init(), loadIndex(), fetchBase(p.id)]);
    if (current !== p) return;
    const meta = I.spots[p.id];
    if (!meta) throw new Error("fara date 3D");
    const base = await buildBase(meta, p.id);
    if (current !== p) return;
    ctx.resize();
    clearScene();
    ctx.dyn.add(base);
    seq = buildSequence(meta, p);
    $("loading3d").style.display = "none";
    if (!raf) raf = requestAnimationFrame(frame);
    clearTimeout(slow);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));   // primul cadru desenat
    $("fadeMsg").textContent = "";
    dip(false);
  } catch (e) {
    console.error(e);
    clearTimeout(slow);
    $("fadeMsg").textContent = "";
    $("loading3d").textContent = "3D indisponibil pentru acest punct (fara conexiune?).";
    dip(false);
  }
}
async function close3D(fromHistory) {
  const v = $("v3d");
  if (!v.classList.contains("on") || v.dataset.closing) return;
  v.dataset.closing = "1";
  if (!fromHistory && history.state && history.state.v3d) history.back();
  await dip(true, 300);
  v.classList.remove("on");
  v.setAttribute("aria-hidden", "true");
  delete v.dataset.closing;
  current = null;
  cancelAnimationFrame(raf); raf = 0;
  if (ctx) clearScene();
  dip(false, 450);
}
window.open3D = open3D;

$("back3d").addEventListener("click", () => close3D(false));
$("replay3d").addEventListener("click", () => { if (current) open3D(current); });
// comutare hibrid -> model 3D -> puncte, fara sa reporneasca animatia
$("mode3d").addEventListener("click", async () => {
  mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
  try { localStorage.setItem("v3dmode", mode); } catch (e) { /* fara stocare: ramane doar pe sesiune */ }
  modeLabel();
  if (!current || !ctx) return;
  const p = current, I = await loadIndex();
  const base = await buildBase(I.spots[p.id], p.id);
  if (current !== p) return;
  for (const o of ctx.dyn.children.filter(o => o.userData.base)) { ctx.dyn.remove(o); disposeObj(o); }
  ctx.dyn.add(base);
});
modeLabel();
$("sheetHandle").addEventListener("click", () => $("sheet").classList.toggle("open"));
window.addEventListener("popstate", () => close3D(true));
window.addEventListener("keydown", e => { if (e.key === "Escape") close3D(false); });

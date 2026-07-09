/* Arlington GLUP historical map browser.
 *
 * Single-map mode: one edition visible, timeline picks the year.
 * Compare mode: two synced maps split by a draggable divider.
 * State (year, compare year, camera) lives in the URL hash.
 */

const BASE_STYLE = "https://tiles.openfreemap.org/styles/positron";
const START = { center: [-77.095, 38.878], zoom: 11.7 };
const ATTRIB = 'Maps © <a href="https://www.arlingtonva.us/Government/Projects/Plans-Studies/General-Land-Use-Plan/Maps">Arlington County</a>';
// GLUP overlays ship as one .pmtiles archive per year, read via HTTP range
// requests — no tile server. Override TILES_BASE (absolute URL, trailing
// slash) to host the archives elsewhere, e.g. an R2 bucket.
const TILES_BASE = window.TILES_BASE || "";

const pmProtocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", pmProtocol.tile);

const SOURCE_URLS = {}; // year -> original PDF/JPG, filled from manifest below
fetch("sources.json").then(r => r.ok ? r.json() : {}).then(d => Object.assign(SOURCE_URLS, d));

let editions = {};   // index.json: year -> {path, minzoom, maxzoom, bounds}
let years = [];
let yearA, yearB;
let comparing = false;

const $ = id => document.getElementById(id);

async function init() {
  editions = await (await fetch("tiles/index.json")).json();
  years = Object.keys(editions).sort();
  yearA = years[years.length - 1];
  yearB = years[0];

  const hash = parseHash();
  if (hash.year && years.includes(hash.year)) yearA = hash.year;
  if (hash.compare && years.includes(hash.compare)) { yearB = hash.compare; comparing = true; }

  const mapA = mkMap("mapA");
  const mapB = mkMap("mapB");
  window._maps = { A: mapA, B: mapB };

  syncMaps(mapA, mapB);
  buildTimeline();
  buildCompareSelects();
  wireControls();
  initLegend();
  mapA.on("click", onMapClick);
  mapB.on("click", onMapClick);

  mapA.on("load", () => { addEditions(mapA); showYear("A", yearA); });
  mapB.on("load", () => { addEditions(mapB); showYear("B", yearB); });
  if (comparing) enterCompare(true);
  updateChrome();
}

function mkMap(container) {
  const m = new maplibregl.Map({
    container,
    style: BASE_STYLE,
    center: START.center,
    zoom: START.zoom,
    hash: container === "mapA" ? "map" : false,
    attributionControl: false,
  });
  m.addControl(new maplibregl.AttributionControl({ customAttribution: ATTRIB }), "bottom-right");
  if (container === "mapA") {
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.FullscreenControl({ container: document.body }), "top-right");
  }
  return m;
}

function addEditions(map) {
  for (const y of years) {
    const e = editions[y];
    const archive = new URL(TILES_BASE + e.path + ".pmtiles",
                            location.href).href;
    map.addSource("glup-" + y, {
      type: "raster",
      url: "pmtiles://" + archive,
      tileSize: 256,
      bounds: e.bounds,
    });
    map.addLayer({
      id: "glup-" + y,
      type: "raster",
      source: "glup-" + y,
      layout: { visibility: "none" },
      paint: {
        "raster-opacity": Number($("opacity").value) / 100,
        "raster-fade-duration": 0,
      },
    });
  }
}

function showYear(side, year) {
  const map = window._maps[side];
  if (side === "A") yearA = year; else yearB = year;
  if (map.getLayer("glup-" + year)) {
    for (const y of years) {
      map.setLayoutProperty("glup-" + y, "visibility",
        y === year ? "visible" : "none");
    }
  } // else: not added yet; the load handler calls us again
  updateChrome();
}

/* ---- sync two maps without feedback loops ---- */
function syncMaps(a, b) {
  let busy = false;
  const follow = (src, dst) => () => {
    if (busy || !comparing) return;
    busy = true;
    dst.jumpTo({
      center: src.getCenter(), zoom: src.getZoom(),
      bearing: src.getBearing(), pitch: src.getPitch(),
    });
    busy = false;
  };
  a.on("move", follow(a, b));
  b.on("move", follow(b, a));
}

/* ---- timeline ---- */
function buildTimeline() {
  const tl = $("timeline");
  tl.innerHTML = "";
  const y0 = +years[0], y1 = +years[years.length - 1];
  for (const y of years) {
    const dot = document.createElement("button");
    dot.className = "tl-dot";
    dot.dataset.year = y;
    dot.style.left = (3 + 94 * (+y - y0) / (y1 - y0)) + "%";
    dot.title = y;
    const label = document.createElement("span");
    label.textContent = y;
    dot.appendChild(label);
    dot.onclick = () => showYear("A", y);
    tl.appendChild(dot);
  }
}

function buildCompareSelects() {
  for (const [sel, side] of [[$("yearA"), "A"], [$("yearB"), "B"]]) {
    sel.innerHTML = years.map(y => `<option>${y}</option>`).join("");
    sel.onchange = () => showYear(side, sel.value);
  }
}

/* ---- compare mode ---- */
function enterCompare(on) {
  comparing = on;
  $("wrapB").classList.toggle("hidden", !on);
  $("divider").classList.toggle("hidden", !on);
  $("compare-years").classList.toggle("hidden", !on);
  $("compare-btn").classList.toggle("active", on);
  $("timeline").classList.toggle("hidden", on);
  if (on) {
    setSplit(0.5);
    const b = window._maps.B;
    b.resize();
    b.jumpTo({
      center: window._maps.A.getCenter(), zoom: window._maps.A.getZoom(),
      bearing: window._maps.A.getBearing(), pitch: window._maps.A.getPitch(),
    });
  } else {
    $("wrapA").style.clipPath = "";
  }
  updateChrome();
}

function setSplit(f) {
  f = Math.min(0.95, Math.max(0.05, f));
  const px = f * window.innerWidth;
  $("wrapA").style.clipPath = `inset(0 ${window.innerWidth - px}px 0 0)`;
  $("wrapB").style.clipPath = `inset(0 0 0 ${px}px)`;
  $("divider").style.left = px + "px";
}

function wireDivider() {
  let dragging = false;
  $("divider").addEventListener("pointerdown", e => {
    dragging = true;
    $("divider").setPointerCapture(e.pointerId);
  });
  window.addEventListener("pointermove", e => {
    if (dragging) setSplit(e.clientX / window.innerWidth);
  });
  window.addEventListener("pointerup", () => (dragging = false));
}

/* ---- chrome ---- */
function wireControls() {
  $("opacity").oninput = () => {
    const v = Number($("opacity").value) / 100;
    for (const m of Object.values(window._maps)) {
      if (!m.isStyleLoaded()) continue;
      for (const y of years) m.setPaintProperty("glup-" + y, "raster-opacity", v);
    }
  };
  $("compare-btn").onclick = () => enterCompare(!comparing);
  $("history-close").onclick = clearSelection;
  wireDivider();
  window.addEventListener("keydown", e => {
    if (e.key === "Escape") { clearSelection(); return; }
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
    const i = years.indexOf(yearA) + (e.key === "ArrowRight" ? 1 : -1);
    if (i >= 0 && i < years.length) showYear("A", years[i]);
  });
}

function updateChrome() {
  $("title-year").textContent = comparing ? `${yearA} vs ${yearB}` : yearA;
  document.querySelectorAll(".tl-dot").forEach(d =>
    d.classList.toggle("active", d.dataset.year === yearA));
  $("yearA").value = yearA;
  $("yearB").value = yearB;
  const src = SOURCE_URLS[yearA];
  $("source-link").style.display = src ? "" : "none";
  if (src) $("source-link").href = src;
  renderLegend();
  renderHistory();
  writeHash();
}

/* ---- legend panel ----
 * legends.json: year -> [{code, name, color}] in printed-legend order,
 * colors sampled from each edition's own sheet swatches (so the chips
 * match that year's print, not a normalized palette). */
let LEGENDS = null;

async function initLegend() {
  try {
    LEGENDS = await (await fetch("data/legends.json")).json();
  } catch { return; }
  $("legend-head").onclick = () => {
    $("legend").classList.toggle("collapsed");
    $("legend-arrow").textContent =
      $("legend").classList.contains("collapsed") ? "▸" : "▾";
  };
  if (window.innerWidth < 700) $("legend-head").onclick();
  renderLegend();
}

function legendBlock(year) {
  const rows = (LEGENDS[year] || []).map(c =>
    `<div class="lg-row"><span class="chip" style="background:${c.color}"></span>${c.name}</div>`
  ).join("");
  return `<div class="lg-block"><div class="lg-year">${year}</div>${rows}</div>`;
}

function renderLegend() {
  if (!LEGENDS) return;
  $("legend-body").innerHTML =
    comparing ? legendBlock(yearA) + legendBlock(yearB) : legendBlock(yearA);
}

/* ---- parcel click -> designation history ----
 * Static lookup, no server: a half-resolution (16 ft/px) PNG carries the
 * parcel index in its RGB bytes; history.json carries per-parcel RPC,
 * half-grid bbox, and a base-36 string of per-year class indices into
 * that year's legend. Click -> EPSG:2283 via proj4 -> grid pixel -> id. */
const SP_VA_N =
  "+proj=lcc +lat_0=37.6666666666667 +lon_0=-78.5 +lat_1=39.2 " +
  "+lat_2=38.0333333333333 +x_0=3500000.0001016 +y_0=2000000.0001016 " +
  "+ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=us-ft +no_defs";
let HIST = null;       // history.json
let idsCtx = null;     // canvas 2d context over parcel_ids.png
let histLoading = null;
let selParcel = 0;

function ensureParcelData() {
  if (histLoading) return histLoading;
  histLoading = (async () => {
    const [doc, blob] = await Promise.all([
      fetch("data/history.json").then(r => r.json()),
      fetch("data/parcel_ids.png").then(r => r.blob()),
    ]);
    const bmp = await createImageBitmap(blob);
    const cv = document.createElement("canvas");
    cv.width = bmp.width; cv.height = bmp.height;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(bmp, 0, 0);
    HIST = doc;
    idsCtx = ctx;
  })();
  return histLoading;
}

function lngLatToGrid(lngLat) {
  const [E, N] = proj4("WGS84", SP_VA_N, [lngLat.lng, lngLat.lat]);
  const m = HIST.meta;
  return [Math.floor((E - m.x0) / m.tr), Math.floor((m.y1 - N) / m.tr)];
}

function gridToLngLat(x, y) {
  const m = HIST.meta;
  return proj4(SP_VA_N, "WGS84", [m.x0 + x * m.tr, m.y1 - y * m.tr]);
}

function parcelAt(x, y) {
  const m = HIST.meta;
  if (x < 0 || y < 0 || x >= m.w || y >= m.h) return 0;
  const d = idsCtx.getImageData(x, y, 1, 1).data;
  return d[0] | (d[1] << 8) | (d[2] << 16);
}

async function onMapClick(e) {
  await ensureParcelData();
  const [x, y] = lngLatToGrid(e.lngLat);
  const id = parcelAt(x, y);
  if (!id) { clearSelection(); return; }
  selParcel = id;
  highlightParcel(id);
  renderHistory();
  $("history").classList.remove("hidden");
}

function clearSelection() {
  selParcel = 0;
  $("history").classList.add("hidden");
  for (const m of Object.values(window._maps)) {
    if (m.getLayer("parcel-hl")) {
      m.setLayoutProperty("parcel-hl", "visibility", "none");
    }
  }
}

function highlightParcel(id) {
  const bb = HIST.bbox[id];
  if (!bb) return;
  const [x0, y0, x1, y1] = bb;
  const w = x1 - x0 + 1, h = y1 - y0 + 1;
  const src = idsCtx.getImageData(x0, y0, w, h).data;
  const cv = document.createElement("canvas");
  cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d");
  const out = ctx.createImageData(w, h);
  const mine = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const pid = src[i * 4] | (src[i * 4 + 1] << 8) | (src[i * 4 + 2] << 16);
    mine[i] = pid === id ? 1 : 0;
  }
  for (let py = 0; py < h; py++) {
    for (let px = 0; px < w; px++) {
      const i = py * w + px;
      if (!mine[i]) continue;
      const edge = px === 0 || py === 0 || px === w - 1 || py === h - 1 ||
        !mine[i - 1] || !mine[i + 1] || !mine[i - w] || !mine[i + w];
      out.data[i * 4] = 36; out.data[i * 4 + 1] = 116;
      out.data[i * 4 + 2] = 255; out.data[i * 4 + 3] = edge ? 255 : 90;
    }
  }
  ctx.putImageData(out, 0, 0);
  const url = cv.toDataURL();
  const coords = [
    gridToLngLat(x0, y0), gridToLngLat(x1 + 1, y0),
    gridToLngLat(x1 + 1, y1 + 1), gridToLngLat(x0, y1 + 1),
  ];
  for (const m of Object.values(window._maps)) {
    try {
      if (m.getSource("parcel-hl")) {
        m.getSource("parcel-hl").updateImage({ url, coordinates: coords });
        m.setLayoutProperty("parcel-hl", "visibility", "visible");
      } else {
        m.addSource("parcel-hl", { type: "image", url, coordinates: coords });
        m.addLayer({
          id: "parcel-hl", type: "raster", source: "parcel-hl",
          paint: { "raster-fade-duration": 0, "raster-resampling": "nearest" },
        });
      }
    } catch { /* style not ready on the hidden map yet */ }
  }
}

function renderHistory() {
  if (!HIST || !selParcel) return;
  const rpc = HIST.rpc[selParcel];
  $("history-title").textContent = rpc ? "RPC " + rpc : "Parcel";
  const hh = HIST.hist[selParcel];
  const rows = HIST.years.map((year, yi) => {
    const idx = parseInt(hh[yi], 36);
    const cls = idx ? (LEGENDS[year] || [])[idx - 1] : null;
    const chip = cls
      ? `<span class="chip" style="background:${cls.color}"></span>`
      : `<span class="chip chip-none"></span>`;
    const name = cls ? cls.name : "unclassified";
    const cur = year === yearA ? " current" : "";
    return `<div class="h-row${cur}" data-year="${year}">` +
           `<span class="h-year">${year}</span>${chip}` +
           `<span class="h-name">${name}</span></div>`;
  }).join("");
  $("history-body").innerHTML = rows;
  $("history-body").querySelectorAll(".h-row").forEach(r => {
    r.onclick = () => showYear("A", r.dataset.year);
  });
}

/* ---- hash state (alongside maplibre's #map=z/lat/lng) ---- */
function parseHash() {
  const m = location.hash.match(/year=(\d{4})/);
  const c = location.hash.match(/compare=(\d{4})/);
  return { year: m && m[1], compare: c && c[1] };
}

function writeHash() {
  let h = location.hash.replace(/&?(year|compare)=\d{4}/g, "");
  if (!h.startsWith("#")) h = "#" + h;
  h += (h.length > 1 ? "&" : "") + "year=" + yearA;
  if (comparing) h += "&compare=" + yearB;
  history.replaceState(null, "", h);
}

init();

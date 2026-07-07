# Arlington GLUP historical map viewer — pipeline notes (2026-07-06)

Goal: automatic georeferencing of all 21 GLUP editions (1961–2024) from
https://www.arlingtonva.us/Government/Projects/Plans-Studies/General-Land-Use-Plan/Maps
plus a static MapLibre viewer (like the Charlottesville historical zoning
viewer, but no Mapbox/Observable dependency).

## Source facts
- arlingtonva.us 403s plain curl; needs full browser headers (see scripts/download.sh).
  S3-hosted files (arlingtonva.s3.amazonaws.com) download fine.
- **2011 link on the county page serves the 2013 file** (identical md5). True 2011
  edition not obtained; viewer shows 2013 only. Could try Wayback Machine later.
- The "2020" edition is the April 2021 PDF (labeled by adoption year).
- GeoPDFs (embedded CRS EPSG:2283 + neatline): 2016, 2017, 2018, 2020, 2021, 2022,
  2024 (fronts; backs too where present). Extract georef directly via GDAL.
- 2019 + 2023 lost georef via Illustrator/Acrobat re-save. 2004/2013/2014 plain.
- 1961–1996 are scans (JPG).
- **Backs are "Major Planning Corridors" inset sheets — not spatially meaningful.**
  Fronts only in the viewer.
- Sheet orientation: 1987+ printed north-up; 1983 and older rotated ~40°.
  1987 was the cartographic break year (new base map + orientation).

## Georeferencing pipeline (scripts/)
1. `download.sh` → sources/ (manifest.tsv driven)
2. `extract.py` → work/rgb (300dpi renders; pdftoppm for non-geo PDFs, GDAL for
   GeoPDFs) + work/georef for GeoPDF years
3. `georef.py` → chain-match each remaining edition to nearest-era anchor:
   - SIFT (RootSIFT, nfeatures=50k, ratio 0.8) + RANSAC homography → GCPs
   - fallback: `corr_match.py` coarse rotation×scale phase-correlation sweep +
     2-iteration grid template matching (NCC on **street masks** = top-hat +
     blur; gradient images too noisy across style changes)
   - GCPs → gdal_translate -gcp + gdalwarp -tps → EPSG:2283 GeoTIFF w/ alpha
4. `tiles.py` → gdal2tiles XYZ z10–16 (native max zoom per edition) → web/tiles/
5. web/ = MapLibre viewer (timeline, opacity, swipe compare, hash state)

## Architecture v2 (after user caught pre-2013 all misplaced)
- **TIGER street centerlines are the ground truth** (work/ref/ref_streets.tif,
  scripts/make_ref.sh: TIGER 51013 roads rasterized to county bbox @16ft/px).
  1. Every accepted warp must verify vs TIGER: street mask phase-corr,
     offset ≤150ft, resp ≥0.04 (good editions measure 0.08–0.19).
  2. Editions match DIRECTLY against the TIGER raster (pass 2 "tiger"):
     coarse = brute-force angle (3° steps) × sheet-width (5 scales)
     TM_CCOEFF_NORMED template matching of street masks at 64ft/px —
     phase correlation CANNOT do this (partial overlap: sheet ⊃ county);
     template matching is built for it. Then the standard 2-iter fine grid.
  3. SIFT chain (pass 1) kept for easy pairs (dense GCPs = best warp
     quality); sheet-to-sheet corr is pass 3.
- **My eyeball QA of 50% blends failed 3 times** — flagged wrong ones as
  aligned. Only the numeric verify caught it (user caught it first, in the
  actual viewer, at National Airport).
- 138-inlier SIFT matches can be furniture locks CLUSTERED in a few cells:
  spread_pick cell count is the tell → MIN_GCP_COVERAGE gate (20 cells sift).
  5-GCP TPS from a cluster = garbage warp with plausible-looking extent.
- North-up sheets tuck legend/notes INSIDE the county bbox (diamond corner
  voids) — masking/cropping anchors to the bbox does NOT remove furniture,
  which is why anchor-raster verification failed (furniture correlates).
- Orientation histograms for rotation seeding fail (mixed street-grid
  families: county ±37° + DC north-aligned). Brute force is 30s. Just sweep.

## Hard-won lessons
- **Verify every chain link against modern ground truth (2024), not just its
  own anchor.** A wrong link looks fine vs its anchor and corrupts everything
  downstream. I shipped 3 wrong chains before instituting audit-all-vs-2024.
- **Validation gates > preprocessing tweaks.** The final architecture:
  (1) center_gate: county bbox EDGE MIDPOINTS (≈ diamond county's N/E/S/W
  extremes — NOT bbox corners, which rotate off-sheet legitimately) must
  map inside the sheet via a SIMILARITY fit (homography fitted to clustered
  points extrapolates wildly); (2) post-warp extent check: warped raster
  must contain the county bbox (catches TPS extrapolation blowups).
  With those two, weak matchers can be allowed to try multiple candidates.
- corr coarse stage returns TOP-K candidates; fine stage + gate verify each.
  Single-best coarse peak is fragile (right answer often rank 2-4).
- **Sheet furniture is the #1 false-match source.** Editions share layout
  (title top-right, legend left, insets), so SIFT/NCC lock furniture-to-furniture
  and produce self-consistent but shifted results (1996→2004 was off ~1.5km NE
  with 108 "good" inliers). Fix: mask anchor to county bbox (COUNTY_BBOX in
  georef.py, EPSG:2283) in BOTH sift and corr paths. QA every link vs 2024, not
  just its own anchor.
- 1983↔1987 unSIFTable (style+rotation jump): needed corr_match. NCC scores
  across styles are weak (~0.2) — use best-peak-per-cell + RANSAC consensus,
  not absolute score thresholds. Street masks >> gradient images.
- cv2 5.0 dropped AKAZE/BRISK; SIFT + ORB remain.
- gdalinfo "GeoTransform" only printed when rotated; north-up shows "Origin".
  Detect georef via NEATLINE + (Origin|GeoTransform).
- OpenCV imread of warped 4-band tif: use IMREAD_GRAYSCALE (alpha→black ok).
- venv: .venv with opencv-python-headless (system python 3.13, GDAL 3.4.1 CLI).

## QA
- work/qa/{name}_vs_{anchor}.jpg = 50/50 georeferenced blends. Also generate
  vs 2024 for every year (make_qa(name, "2024-front")) to catch chain drift.
- report.tsv: name, anchor(method), points, rms_px.

## PUBLISHED (2026-07-06)
- Live: https://rorystolzenberg.github.io/arlington-glup-history/
- Repo: github.com/RoryStolzenberg/arlington-glup-history (Pages from /docs
  on main; gh account must be RoryStolzenberg — `gh auth switch`).
- web/ renamed to docs/. Tiles = per-year .pmtiles archives (224 MB total)
  in docs/tiles/; XYZ dirs stay local-only (gitignored) as pmtiles input.
- Pipeline additions: pngquant pass (999→360 MB XYZ), scripts/pmtiles_build.py
  (mb-util + go-pmtiles; PMTILES env for binary path). Viewer uses pmtiles
  protocol; TILES_BASE global allows moving archives to R2 later.
- GitHub Pages DOES serve range requests (verified 206 on live pmtiles).
- Local preview: `npx serve docs` (python http.server lacks Range support).

## FINAL STATE (2026-07-06, after v2 rebuild)
- ALL 21 editions verified vs TIGER: global offset ≤30 ft, resp 0.043–0.194
  (verify.py table). Old scans (1961–1983) ≈15–30 ft; modern ≤7 ft.
- Method mix: GeoPDF extract (2016–2024), SIFT chain (2013/2014/2019/2023,
  2004←1996, 1990←1996, 1987←1990, 1979←1983, 1975←1979, 1964/1961←1966),
  TIGER-direct template matching (1996, 1983, 1966).
- 2004 was the hardest: SIFT vs 2013/2014/2016 = clustered furniture locks;
  TIGER-direct weak (pale residential streets extract poorly); solved by
  SIFT vs sibling 1996 (221 inliers, +13/+12 ft).
- Old rotated sheets need width hypotheses down to 30000 ft in tiger_coarse
  (portrait sheet ≈34000 ft across, county rotated ~37°).
- Viewer + tiles rebuilt and spot-checked at National Airport (2004, 1990,
  1961 all align at 55% opacity).

## State (end of 2026-07-06 session)
- DONE: all 21 fronts georeferenced AND visually verified vs 2024 (every
  QA blend inspected). 1983 + 1961 went through the corr fallback
  (22–32 GCPs); everything else SIFT with hundreds-to-thousands of inliers.
- DONE: all 21 editions tiled (web/tiles/, 999 MB, z10–16/15).
- DONE: viewer tested with Playwright (year switch, arrows, opacity,
  compare swipe, URL hash) — no console errors. Fixed init bug: guard
  showYear on map.getLayer(), not isStyleLoaded() (false inside load
  handler right after addLayer).
- Serving locally: python3 -m http.server 8631 in web/.
- NOT done / ideas: hosting (tiles are 999 MB — pngquant could ~1/3 it, or
  cap z15 ≈ 1/4); legend crops per year like Cville viewer; real 2011 via
  Wayback; opacity keyboard shortcut; mobile testing.

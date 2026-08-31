# Web viewer (docs/, GitHub Pages)

Live: https://rorystolzenberg.github.io/arlington-glup-history/
Repo: github.com/RoryStolzenberg/arlington-glup-history — Pages serves
`/docs` on `main`. **Pushing requires the RoryStolzenberg account:
`gh auth switch --user RoryStolzenberg`** (default account 403s).

## Structure

Static site, no build step: `index.html`, `app.js`, `style.css`.
Libraries via unpkg script tags: maplibre-gl 4.7.1, pmtiles 3.2.1,
proj4 2.11.0. Base map: OpenFreeMap positron.

- **Editions**: one raster source+layer per year from
  `docs/tiles/{year}.pmtiles` (HTTP range requests, no server).
  `docs/tiles/index.json` = year → {path, zoom range, WGS84 bounds}.
- **Modes**: single year with timeline dots; compare mode = two synced
  maps behind a draggable clip-path divider. State in the URL hash
  (`#map=z/lat/lng&year=YYYY[&compare=YYYY]`).
- **Legend panel** (bottom left): renders `data/legends.json` — each
  edition's classes in printed order, chips sampled from that sheet's own
  swatches. Shows both years in compare mode; collapsed by default on
  mobile.
- **Parcel history**: click → proj4 to EPSG:2283 (proj string in app.js,
  verified vs gdaltransform) → 16 ft grid px → parcel index decoded from
  `data/parcel_ids.png` RGB bytes (canvas getImageData; half-res keeps the
  canvas under iOS's ~16.7 Mpx limit) → `data/history.json` row → side
  panel with the 21-edition timeline (rows switch the map year) + a
  bbox-masked image-source highlight on the map. Esc / empty click clears.

## Data files (`docs/data/`, from scripts/webdata.py)

- `history.json`: `{years, meta{x0,y1,tr,w,h,crs}, rpc[], hist[], bbox[]}`
  — `hist[i]` is a 21-char base-36 string, one digit per year: 0 =
  unclassified/ambiguous, else 1+index into that year's legend classes.
  `bbox[i]` in half-grid px, null for parcels too small for the half grid.
- `parcel_ids.png`: parcel index in RGB (R low byte, G mid, B high).
- `legends.json`: year → [{code, name, color}] (sheet-sampled hex).

**Regenerate with `scripts/webdata.py` whenever classifications change.**

## Operations

- Local preview: `npx serve docs` (python http.server lacks Range support
  — pmtiles won't load).
- Testing: Playwright via **system python3** (the venv lacks it); test
  scripts in `_junk/uitest*.py` cover legend render, click → history,
  compare mode, mobile viewport, and the live site.
- GitHub Pages quirk: etags are (deploy-time, size) and rotate on every
  push; the pmtiles client validates etags across range requests, so an
  open session can transiently fail to render a year right after a deploy
  until hard refresh. Transient by design; don't chase it.
- Sibling repo: the Charlottesville zoning viewer (Planning/Historical
  Zoning) shares this viewer's design — port improvements across.

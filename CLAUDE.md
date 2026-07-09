# Arlington GLUP Historical Map Viewer

Automatic georeferencing of Arlington County's General Land Use Plan map
editions (1961–2024) + a static MapLibre web viewer to browse/compare them.

## Memory files
- `memory/2026-07-06-pipeline-notes.md` — pipeline design, source facts,
  false-match lessons (READ FIRST in new sessions)

## Layout
- `sources/` — original PDFs/JPGs (gitignored) + manifest.tsv
- `scripts/` — download.sh, extract.py, georef.py, corr_match.py, tiles.py
- `work/` — rgb/ (plain renders), georef/ (EPSG:2283 GeoTIFFs), qa/ (blends)
- `docs/` — static viewer, served by GitHub Pages (index.html/app.js/
  style.css, data/ for parcel-history lookup; tiles/ pmtiles committed,
  XYZ dirs gitignored)
- `experiments/` — one-off matching experiments
- `_junk/` — gitignored session diagnostics (probe/QA scripts + rendered
  images rescued from the ephemeral scratchpad; see its README)
- Python: `.venv/bin/python` (opencv); GDAL via CLI tools

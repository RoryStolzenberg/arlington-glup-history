# Arlington GLUP Historical Map Viewer

Every edition of Arlington County's General Land Use Plan map (21 editions,
1961–2024), auto-georeferenced, color-classified into per-parcel
designations, and published as a static MapLibre viewer:
https://rorystolzenberg.github.io/arlington-glup-history/
(GitHub Pages from `/docs` on `main`).

**Status: both pipelines COMPLETE for all 21 editions** — georeferencing
verified ≤30 ft, classification validated per era, viewer has per-year
legends + click-a-parcel designation history. Active phase: acreage/
capacity analysis and viewer polish.

## Documentation (notes/ — read the shard for the stage you're touching)

- `notes/architecture.md` — end-to-end data flow, grids/CRS, what's
  committed vs regenerable. Start here for any structural question.
- `notes/georeferencing.md` — method mix + verification (done; only for
  new editions/rescans).
- `notes/classification.md` — classifier algorithm, legend-config schema,
  era quirks, tuning workflow. **Required reading before touching
  classify.py or classify/legends/*.json.**
- `notes/viewer.md` — site structure, docs/data formats, testing,
  publishing.
- `notes/analysis-outputs.md` — acreage/density CSVs and the caveats that
  must accompany any cross-year comparison.
- `memory/2026-07-06-pipeline-notes.md` — raw session log (war stories,
  chronological); notes/ is the curated distillation.

## Layout

- `sources/` — original PDFs/JPGs (gitignored) + manifest.tsv
- `scripts/` — pipeline: download.sh → extract.py → georef.py/corr_match.py
  → verify.py → tiles.py → pmtiles_build.py; refs: parcels.py, make_ref.sh;
  classification: classify.py; viewer data: webdata.py
- `classify/` — legends/{year}.json (hand-tuned configs) + analysis CSVs
- `work/` — gitignored, regenerable: rgb/, georef/, qa/, ref/, classify/
- `docs/` — the published site (index.html/app.js/style.css, data/,
  tiles/*.pmtiles committed; XYZ dirs gitignored)
- `notes/` — curated docs · `memory/` — session logs · `experiments/` —
  one-offs · `_junk/` — gitignored diagnostic scripts + QA imagery (README
  inside)

## Environment & conventions

- Python: `.venv/bin/python` (opencv, numpy — NO playwright/PIL);
  **system `python3`** has playwright + PIL. GDAL via CLI tools.
- Run python with `-u`; GDAL TIFF warnings on work/ rasters are noise.
- **Pushing**: `gh auth switch --user RoryStolzenberg` first (the default
  account 403s on the arlington-glup-history remote).
- Local site preview: `npx serve docs` (http.server lacks Range support).
- After changing any classification: rerun `scripts/classify.py {years}`
  then `scripts/webdata.py`, and eyeball the county comparison before
  showing results (isolated one-parcel classes are almost always errors —
  GLUP designations are big contiguous swathes).
- Sibling repo: Cville zoning viewer (Planning/Historical Zoning) — keep
  viewer improvements in sync.

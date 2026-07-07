# Arlington GLUP History

Interactive browser for every published edition of Arlington County,
Virginia's **General Land Use Plan** map, 1961–2024 — georeferenced onto a
modern basemap so you can watch six decades of planning decisions play out.

**Live viewer:** https://rorystolzenberg.github.io/arlington-glup-history/

- Click the timeline (or use ←/→) to switch years
- Drag the **overlay** slider to fade against today's streets
- **compare** gives a draggable side-by-side of any two years

## Where the maps come from

Arlington publishes scans and PDFs of 21 GLUP editions on its
[Historical GLUP Maps](https://www.arlingtonva.us/Government/Projects/Plans-Studies/General-Land-Use-Plan/Maps)
page. The 2016–2024 PDFs are GeoPDFs with embedded georeferencing; everything
older — down to the 1961 original, a rotated scan of a paper foldout — was
georeferenced automatically by this repo's pipeline:

1. **GeoPDF extraction** (GDAL) for editions that carry coordinates.
2. **SIFT feature matching** between stylistically-similar neighboring
   editions, RANSAC-filtered into thin-plate-spline control points.
3. **Street-network template matching** against a rasterized
   [TIGER](https://www.census.gov/geography/tiger-data.html) road centerline
   reference for editions too different in style for feature matching
   (brute-force rotation × scale search, then grid NCC refinement).
4. Every result must pass **quantitative verification**: phase correlation
   of its street mask against the TIGER reference, accepted only within
   150 ft. Final audited global offsets: ≤ 7 ft for 2013–2024, ≤ 15 ft for
   1987–2004, ≤ 30 ft for the 1961–1983 scans (`scripts/verify.py`).

Tiles ship as one [PMTiles](https://protomaps.com/docs/pmtiles) archive per
year — static files read via HTTP range requests, no tile server.

## Repo layout

- `docs/` — the static site (MapLibre GL + pmtiles) and tile archives
- `scripts/` — the pipeline: `download.sh` → `extract.py` → `georef.py`
  (+ `corr_match.py`) → `tiles.py` → `pmtiles_build.py`; `verify.py` audits;
  `make_ref.sh` builds the TIGER reference
- `memory/` — engineering notes, including the false-match failure modes
  worth reading before touching the matcher

## Rebuilding

```
scripts/download.sh              # fetch source PDFs/JPGs (browser headers)
python scripts/extract.py        # render + extract GeoPDF georeferencing
scripts/make_ref.sh              # TIGER street reference
python scripts/georef.py         # auto-georeference everything else
python scripts/verify.py         # audit vs TIGER — read this table
python scripts/tiles.py          # XYZ tiles (docs/tiles/{year}/)
python scripts/pmtiles_build.py  # pack into docs/tiles/{year}.pmtiles
```

Local preview needs a range-request-capable server: `npx serve docs`.

## Known caveats

- The county page's "2011" link serves the 2013 file (identical md5), so
  2011 is absent here.
- Back pages (Major Planning Corridors insets) aren't geographic and are
  excluded.
- Scan-era editions can be locally off by tens of feet — paper stretch and
  1960s drafting are what they are.

Map sheets © Arlington County. Basemap © [OpenFreeMap](https://openfreemap.org)
/ © OpenStreetMap contributors. Roads reference: US Census TIGER/Line.

# Architecture: data flow end to end

Two pipelines share one coordinate system and meet in the web viewer.

```
sources/            (county PDFs/JPGs, download.sh + manifest.tsv)
   │ extract.py
work/rgb/           plain sheet renders          {year}-{side}.tif
work/georef/        EPSG:2283 GeoTIFFs           {year}-front.tif
   │ tiles.py → pmtiles_build.py                       │ classify.py
docs/tiles/         {year}.pmtiles           work/classify/  raw/parcel tifs,
   │                                              csv, qa png
   │                                                   │ webdata.py
docs/  (GitHub Pages viewer)  ◄────────────  docs/data/  history.json,
                                             parcel_ids.png, legends.json
```

## Coordinate systems and grids

Everything meets on the **county grid**: EPSG:2283 (NAD83 / Virginia North,
US survey ft), bbox `(11859230, 6984963, 11902486, 7028535)`, at three
resolutions:

| grid | res | size | used by |
|---|---|---|---|
| classify grid | 8 ft/px | 5407×5446 | classify.py, parcel_ids.tif, county_mask.tif, all `work/classify/` rasters |
| verify grid | 16 ft/px | 2704×2723 | ref_streets.tif (TIGER), verify.py |
| web grid | 16 ft/px | 2704×2724 | docs/data/parcel_ids.png (classify grid `[::2,::2]`) |

Coordinate conversions: grid px `(x, y)` → E = x0 + (x+0.5)·tr,
N = y1 − (y+0.5)·tr. The viewer does the same in JS via proj4 (string in
docs/app.js, verified within 0.9 ft of gdaltransform).

Three coordinate spaces appear in configs and scripts — don't mix them:
- **sheet pixels**: positions on `work/rgb/{year}-front.tif` (legend swatch
  coords in `classify/legends/*.json` "classes").
- **county-grid pixels** (8 ft): `map_samples`, `negatives`, `regions` in
  legend configs — these are geographic, so the same coords describe the
  same place in every year.
- **lat/lng**: viewer only.

## Reference data (`work/ref/`, built once)

- `parcels.py` → `parcels.gpkg`, `parcel_ids.tif` (uint32 parcel index,
  1-based, 0 = ROW/none), `parcel_index.json` (index → RPCMSTR). Arlington
  REA parcel polygons, current vintage — history is "what did the plan paint
  at this location", using today's parcel fabric.
- `make_ref.sh` → `ref_streets.tif`: TIGER 2023 street centerlines
  rasterized at 16 ft/px; the absolute georeferencing reference and the
  street-buffer mask for classification.
- `county_mask.tif` / `county*.geojson`: county polygon on the grids.

## Repository vs work products

`work/` is gitignored and fully regenerable from `sources/` + scripts.
Committed truth: scripts, `classify/legends/*.json` (hand-tuned),
`classify/*.csv` (analysis outputs), `docs/` (site incl. pmtiles + data),
`notes/`, `memory/`. `_junk/` (gitignored) holds session diagnostic scripts
and rendered QA imagery — see its README.

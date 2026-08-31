# Georeferencing the 21 editions

Status: COMPLETE and verified. All 21 fronts ≤30 ft global offset vs TIGER
(modern editions ≤7 ft). Only revisit this stage for a new edition or a
rescan. Deep war stories: `memory/2026-07-06-pipeline-notes.md`.

## Method mix (per edition)

1. **GeoPDF extract** (2016–2024): the county PDFs embed georeferencing;
   `extract.py` renders through GDAL so the geotransform scales with DPI.
2. **SIFT chain** (`georef.py`): feature-match against an already-
   georeferenced *anchor* edition, chained era-to-era so each pair is
   stylistically close: 2013/2014/2019/2023 ← GeoPDF era; 2004←1996,
   1990←1996, 1987←1990, 1979←1983, 1975←1979, 1964/1961←1966. RANSAC
   homography → GCPs → `gdalwarp -tps`.
3. **TIGER-direct template matching** (1996, 1983, 1966): street-mask
   correlation against `ref_streets.tif` when no good sibling exists.
4. **Correlation fallback** (`corr_match.py`, used for 1983 + 1961):
   rotation×scale phase-correlation sweep, then grid template matching —
   for pairs whose symbology differs too much for SIFT (22–32 GCPs).

## Verification

`verify.py`: warp every edition to the common grid, phase-correlate street
masks (whole + 2×2 quadrants) against the 2024 ground truth. Correct
editions show |offset| < ~100 ft in all cells; a wrong one shows large or
inconsistent offsets. Every edition was ALSO visually approved via
`work/qa/` 50/50 blends (spot-check anchor: National Airport runways).

## Lessons that will bite again

- Old rotated sheets are portrait, county rotated ~37°; the coarse sweep
  needs width hypotheses down to 30,000 ft.
- 2004 was the hardest: SIFT vs digital-era editions locks onto page
  furniture (legend boxes), TIGER-direct is weak (pale residential streets
  extract poorly). Solution: SIFT vs its stylistic sibling 1996.
- Chain anchors by *era style*, not by date proximity.
- Georef residual (≤30 ft ≈ up to 4 classify-grid px) is why parcel voting
  erodes parcel edges (EDGE_ERODE) — paint bleeds across parcel lines.

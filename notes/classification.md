# Color classification: sheets → per-parcel designations

Status: COMPLETE for all 21 editions (validated per era). This doc is the
reference for how the classifier works, the legend-config schema, per-era
quirks, and the tuning workflow — read it before touching `classify.py` or
any `classify/legends/*.json`.

## Algorithm (classify.py, per year)

1. **Exemplars.** Sample each class's Lab color from its legend swatch on
   the sheet render (`work/rgb`) — the legend is printed/scanned through the
   same process as the map, so it's perfect per-edition training data.
   Configs may add `map_samples` (extra exemplars at known county-grid
   spots, for spatial print drift) and `negatives` (exemplars of class 0 at
   smear colors). A pixel takes the nearest exemplar (Lab distance, L
   weighted 0.6, a/b 1.0), cut off at MAX_LAB_DIST=22.
2. **Cuts**, in order: distance cutoff → white cut (L>90 & chroma <
   `white_chroma`) → black cut (L < `black_l` & chroma < 18) → ink halo
   (dilated unblurred-black mask; kills the blur ring around text/lines) →
   county mask → `regions` (region-bound classes zeroed elsewhere) →
   morphological opening r=2 per class ("designations are big swathes";
   `textured` classes exempt). Classes in `dark` skip the black cut and
   halo (for near-black fills like 1987 res-high stipple) but must be
   region-bound.
3. **Parcel vote.** Each parcel (parcel_ids.tif) takes the plurality class
   among its *interior* classified pixels (edges eroded EDGE_ERODE=2 px so
   georef bleed can't vote; parcels with <16 interior px fall back to all
   pixels). Classes sharing a `family` pool their votes (winner = top class
   within the winning family). A parcel is left unresolved if the winning
   share < MIXED_SHARE=0.65 or it has <4 classified px.
4. **Raw passthrough.** Unresolved/non-parcel pixels keep their per-pixel
   class, except where street-like: within the dilated TIGER buffer, or
   where the paper+ink fraction in a 15 px window exceeds
   `solid_max_street` (default 0.20) — gray fills and street-network-on-
   paper have the same blurred color.

Outputs: `work/classify/{year}_{raw,parcel}.tif`, `{year}_qa.png`,
`{year}_parcels.csv` (rpc, code, share, pixels), acreage on stdout.
**After any classification change, rerun `scripts/webdata.py`** so the
viewer's parcel-history data matches.

## Legend config schema (`classify/legends/{year}.json`)

| key | space | meaning |
|---|---|---|
| `classes[]` | sheet px | `{code, name, x, y}` swatch centers; optional `family` groups near-identical tints for the vote |
| `sample_radius` | sheet px | half-size of the swatch median box (12–14) |
| `blur` | — | `{median, gauss}`. Scans: median-only (Gaussian smears white streets + black casings into fake gray). Modern inkjet: needs Gaussian |
| `black_l` | — | black-cut L threshold (42 for label-heavy prints, default 30) |
| `white_chroma` | — | white-cut chroma threshold; must EXCEED the paper's chroma or paper classifies as gray/gov (1964 cream paper ⇒ 12; digital ⇒ 5) |
| `ink_halo` | px | halo dilation radius (default 3; 2 for dense-ink offset prints) |
| `map_samples[]` | county-grid px | `{code, x, y}` extra exemplars; `map_sample_radius` (default 5) |
| `negatives[]` | county-grid px | `{x, y}` class-0 exemplars at smear colors |
| `regions` | county-grid px | `{code: [[x0,y0,x1,y1],…]}` allowed boxes; class zeroed outside |
| `textured` | — | class codes exempt from opening (1961 crosshatch) |
| `dark` | — | class codes exempt from black cut + halo (must be region-bound) |
| `solid_max_street` | — | raw-passthrough gate override (0.55 for 1975–83: their public-ownership stipple reads as street-ness; without it the cemetery/airport/Pentagon drop out) |
| `flat_field` | — | SHELVED illumination correction, default off. Read the post-mortem in classify.py before ever enabling |

county-grid coords are geographic — reusable across years (1961's Rosslyn
region boxes seeded 1964/66's).

## Era guide

- **1961/1964/1966 — 12-class lithographs.** Motel merged into General
  Business (same red, M symbol only); Office Buildings = red crosshatch,
  region-bound + textured + family with com-general. Small green squares
  are REAL (mapped playgrounds). Open-space subclass split
  (public/semi/greenway) is print-dependent — cemetery reads public on
  1964, semi on 1961/66; **report the open-space family total** (stable:
  ~2.6–2.9k ac). 1966 is a dull print: res-low vs res-lowmed 8.6 Lab apart.
- **1975/1979 — 15-class** (modern set minus mixed-use). 1975 oah-low
  printed with an asterisk = "no property classified" and classifies to
  exactly 0 ac. Black tree-stipple = public ownership overlay. 1979
  corridor red prints dull brick (L 40–58) far from its vivid swatch —
  fixed with com-general + svc-commercial map samples; darkest bricks
  (L 40–48) remain ambiguous vs res-highmed maroon.
- **1983 — 15 of 17.** The two striped mixed-use classes are black stripes
  over the base color (medians 2.7 / 9 Lab from res-highmed / com-general)
  — chromatically inseparable, OMITTED; 1983 MU acreage counts under the
  base classes (footnote any table). 1979's Colonial Village purple
  special district has no legend class → honest unclassified hole.
- **1987/1990/1996 — 18-class offset prints.** res-high is a black stipple
  → `dark` + regions. Pale oah-low sits inside the default white cut →
  per-edition `white_chroma`. ~1.1–1.6k ac of parcels stay unassigned
  (building-footprint ink + pale splits) — era floor.
- **2004 → digital era.** Auto-probed swatch columns; stable within 1–2%
  YoY. 2021→2022 shifts (res-highmed 129→71, oah-high 197→275) are real
  amendments, verified on the sheets.

## Tuning workflow (when something looks wrong)

Diagnostic scripts live in `_junk/` (see its README; they run from repo
root and cache `grid{year}.npy` warps beside themselves):
probe/boxprobe/gridcrop (legend reading) → cmp/zoom (county + crop
comparisons) → diag (pixel Lab + nearest exemplar + street_frac) → flecks
(isolated-parcel finder). Iterate config → `classify.py {year}` →
self-review the county comparison at high zoom (hunt isolated one-parcel
classes) → check acreage against era neighbors (`classify/acreage_trend.csv`).

Hard-won rules:
- **The desaturated-zone trap**: faded yellow wash, pale gov gray, and
  stipple-green blends all live at L 70–88 / chroma 5–20. Any map sample or
  negative anchored there steals neighboring classes wholesale (one such
  anchor took 1975 public from 2,155 → 245 ac). Never anchor there unless
  competing classes' real print colors are probed and >10 Lab away; prefer
  accepting scattered-fleck residual (~50–300 ac/yr).
- Verify every candidate map_sample/negative color with a probe before
  committing it; a fleck's *visual* position is a bad guide.
- Isolated small parcels of a class are usually errors ("big swathes"
  prior) — but not always: playgrounds (60s) and Crystal City res-high
  towers (1983) are real. Judge against the source.
- Never raise the vote floor to kill flecks (moth-eats small real lots);
  fix the color model instead.

## Validation anchors

2024 vs official od_GLUP_Sectors: ≈0.8× official across classes (excluded
street ROW share); semi-public 0.98×. oah-low runs ~40% high (pale bleed).
Known residuals: 1961 wash-band gray patches; greenway absorbed into
semi-public; mid-era unassigned floor; paint-vs-parcel MIXED_SHARE floor;
per-parcel one-year blips (e.g. a 2023 unclassified between OAH years).

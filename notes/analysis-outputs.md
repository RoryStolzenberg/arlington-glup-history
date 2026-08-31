# Analysis outputs and their caveats

The consumer-facing products of the classification, and what to footnote
when using them. Purpose: designation acreage over time → zoned-capacity
trends (the friend's ask); dream feature (shipped): click a parcel → its
21-edition designation history.

## Committed data (classify/)

- `acreage_trend.csv` — 21 years × class, acres (parcel-voted + raw
  passthrough; street ROW excluded, hence ≈0.8× official county totals).
  Regenerate: `_junk/trend.py`.
- `density_crosswalk.csv` — per year × class: the density/intensity text
  as printed on each sheet's legend (du/ac, FAR, hotel), with
  `source=sheet` for the 9 directly-read change-point years and
  `source=era` where carried from an identical-design sibling.

## Cross-year comparison rules

- Class *codes* are stable within eras but ranges moved:
  Low 0–8 → 1–10; Low-Med 16–30 → 16–36 (1987); Medium 31→37 lower bound
  (1987); High-Med went FAR-based in 1983; OAH-low apt 90→72 (1979); OAH
  hotel 135→110 and OAH-high to FAR basis (1987). The 2004 sheet prints
  Medium "32–72" — likely misprint of 37 (recorded as printed).
- **1961–66 does not map cleanly onto 1975+**: "High Medium 14–39
  multi-family" straddles the later Low-Med/Medium split; gross-acre vs
  net basis differs. For visualization we map by nearest density band
  (see `_junk/stdmaps.py` ALIAS); for capacity analysis the crosswalk
  judgment belongs to the domain expert.
- Trust the **open-space family total**, not the public/semi/greenway
  split, in 1961–66. Cemetery/airport sit in gov for 1975–83 (their
  prints draw them Ft-Myer-gray + ownership stipple) but public/green
  elsewhere — a known print artifact, not a redesignation.
- Digital era (2013+) is stable to 1–2% YoY; jumps there are real
  amendments (verified: 2021→22 res-highmed 129→71, oah-high 197→275).
  1983 mixed-use acreage is counted under res-highmed / com-general
  (striped overprint, see classification.md).

## Renderers (_junk/)

- `classheets.py {years}` — per-class pixel contact sheet per year
  (`classpx_{year}.png`): one panel per designation + unclassified.
- `consolidated.py {year}` — single map, sheet-native colors + acreage
  legend (`classmap_{year}.png`).
- `stdmaps.py` — all years in one standardized density-band palette +
  animated GIF (`stdmap_{year}.png`, `glup_1961_2024.gif`). Old-era codes
  are remapped by density band so legend redesigns don't read as fake
  county-wide change.

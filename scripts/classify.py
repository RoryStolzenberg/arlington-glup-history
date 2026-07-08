#!/usr/bin/env python3
"""Classify each edition's pixels into GLUP designations by legend color.

For each year with a classify/legends/{year}.json config:
  1. Sample class exemplar colors from the legend swatches on the SHEET
     render (work/rgb) — the swatches are printed/scanned through the same
     process as the map, so they are perfect per-edition training data.
     Old lithographs drift spatially (washed-out corners, ink density), so
     configs may add "map_samples": extra exemplars sampled from known
     locations on the county grid itself; each class takes the minimum
     distance over all of its exemplars.
  2. Warp the georeferenced edition onto the 8 ft/px county grid, blur away
     print noise, and label each pixel by nearest exemplar in Lab space
     (with white-paper / black-ink exclusion and a max-distance cutoff).
     Blur is per-edition ("blur": {"median": N, "gauss": sigma}): modern
     inkjet halftone needs a heavy Gaussian; scanned lithographs must NOT be
     Gaussian-blurred or white streets + black casings smear into a gray
     that is indistinguishable from real gray fills.
     Near-neutral (gray) classes additionally require a locally SOLID fill:
     where the unclassified-white fraction in a small window is high (street
     network on bare paper), gray assignments are rejected.
  3. Snap to parcels: each parcel (work/ref/parcel_ids.tif) takes the
     plurality class among its classified pixels — text labels, symbols and
     boundary lines get outvoted.

Outputs per year:
  work/classify/{year}_raw.tif     uint8 class ids, raw per-pixel
  work/classify/{year}_parcel.tif  uint8 class ids, parcel-snapped
  work/classify/{year}_qa.png      parcel-snapped render in legend colors
  work/classify/{year}_parcels.csv rpc, class code, share, pixels
  acreage summary on stdout

Usage: classify.py [years...]  (default: every year with a legend config)
"""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LEGENDS = ROOT / "classify" / "legends"
OUT = ROOT / "work" / "classify"
BBOX = (11859230, 6984963, 11902486, 7028535)
TR = 8                     # ft/px, must match work/ref/parcel_ids.tif
MAX_LAB_DIST = 22.0        # nearest-exemplar cutoff (Lab units)
WHITE_L, WHITE_CHROMA = 90.0, 9.0   # unpainted paper / streets
BLACK_L = 30.0                       # ink lines & text
MIN_PARCEL_SHARE = 0.4     # plurality must cover this share of classified px
ACRES_PER_PX = (TR * TR) / 43560.0
BLACK_CHROMA = 18.0        # ink is neutral; dark saturated fills are paint
STREET_DILATE = 3          # px dilation of the TIGER street mask (8 ft/px)
FF_CELL = 256              # px cell for the flat-field illumination grid
FF_GAIN_MAX = 1.35         # never brighten more than this (wash is mild)
INK_HALO = 3               # px dilation of black ink excluded (blur ring)
SOLID_WIN = 15             # px window for the solid-fill (street-ness) test
SOLID_MAX_STREET = 0.20    # reject raw px where paper+ink fraction exceeds
OPEN_RADIUS = 2            # px: designations are big swathes; kill smaller
LARGE_PARCEL_PX = 4000     # ~6 acres: big tracts may straddle designations
LARGE_PARCEL_SHARE = 0.6   # ...so only snap them when one class dominates


def to_lab(img_bgr):
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32) * \
        np.float32([100 / 255, 1, 1]) - np.float32([0, 128, 128])


def sample_swatches(year, cfg):
    """Exemplar Lab color per class from the sheet render's legend."""
    sheet = cv2.imread(str(ROOT / "work" / "rgb" / f"{year}-front.tif"),
                       cv2.IMREAD_COLOR)
    sheet = cv2.medianBlur(sheet, 5)
    lab = to_lab(sheet)
    r = cfg["sample_radius"]
    out = []
    for c in cfg["classes"]:
        patch = lab[c["y"] - r:c["y"] + r, c["x"] - r:c["x"] + r]
        med = np.median(patch.reshape(-1, 3), axis=0)
        bgr_patch = sheet[c["y"] - r:c["y"] + r, c["x"] - r:c["x"] + r]
        med_bgr = np.median(bgr_patch.reshape(-1, 3), axis=0)
        out.append((c["code"], c["name"], med, med_bgr))
    return out


def flat_field(img, streets):
    """Divide out uneven scan illumination (old photographed wall maps
    have shadowed/washed bands where bare paper reads as gray — the same
    gray as painted fills).

    SHELVED, off by default ("flat_field" per-edition config flag).
    Measured on 1961: both a bright-neutral-pixel anchor and this TIGER
    street-infill anchor overcorrect large gray fills (Fort Myer 79->87
    resp. 79->91: the map draws no white infill for the base's internal
    roads, so the anchor samples the gray fill itself) while
    undercorrecting the deep wash (paper 78->84, not ~96). True gray (83)
    and paper (96) are 13 L apart, the wash spans ~18 — any estimator
    error flips one, and erasing real gov-gray costs ~30x more acreage
    than the wash's false-gray patches. If a worse scan forces this on:
    fit a low-order polynomial only to trusted bright anchors and raise
    the white cutoff for corrected editions.
    """
    lab = to_lab(img)
    h, w = lab.shape[:2]
    gh, gw = (h + FF_CELL - 1) // FF_CELL, (w + FF_CELL - 1) // FF_CELL
    field = np.zeros((gh, gw), np.float32)
    for gy in range(gh):
        for gx in range(gw):
            sl = np.s_[gy * FF_CELL:(gy + 1) * FF_CELL,
                       gx * FF_CELL:(gx + 1) * FF_CELL]
            m = streets[sl] > 0
            if m.sum() > 200:
                field[gy, gx] = np.percentile(lab[sl][..., 0][m], 95)
    # cells without streets (river, margins): nearest measured neighbor
    if (field == 0).any():
        ys, xs = np.nonzero(field == 0)
        gys, gxs = np.nonzero(field > 0)
        for y, x in zip(ys, xs):
            d = (gys - y) ** 2 + (gxs - x) ** 2
            field[y, x] = field[gys[d.argmin()], gxs[d.argmin()]]
    field = cv2.GaussianBlur(field, (0, 0), 1.0)
    target = float(np.percentile(field, 90))
    gain = np.clip(target / np.maximum(field, 1), 1.0, FF_GAIN_MAX)
    gain = cv2.resize(gain, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(img.astype(np.float32) * gain[..., None],
                   0, 255).astype(np.uint8)


def county_grid_rgb(year):
    with tempfile.TemporaryDirectory() as td:
        grid = Path(td) / "grid.tif"
        subprocess.run(
            ["gdalwarp", "-q", "-te", *[str(v) for v in BBOX],
             "-tr", str(TR), str(TR), "-r", "bilinear",
             str(ROOT / "work" / "georef" / f"{year}-front.tif"),
             str(grid)], check=True)
        img = cv2.imread(str(grid), cv2.IMREAD_COLOR)
    return img


def classify_year(year, parcel_ids, parcel_rpc, county_mask, tiger_streets):
    cfg = json.loads((LEGENDS / f"{year}.json").read_text())
    swatches = sample_swatches(year, cfg)
    print(f"=== {year}: {len(swatches)} classes")
    for code, _, lab, _ in swatches:
        print(f"  {code:18s} Lab=({lab[0]:5.1f},{lab[1]:+5.1f},{lab[2]:+5.1f})")

    blur = cfg.get("blur", {"median": 5, "gauss": 2.0})
    img = county_grid_rgb(year)
    if cfg.get("flat_field"):
        img = flat_field(img, tiger_streets)
    lab0 = to_lab(img)               # unblurred: ink/paper keep their value
    if blur.get("median"):
        img = cv2.medianBlur(img, blur["median"])
    if blur.get("gauss"):
        img = cv2.GaussianBlur(img, (0, 0), blur["gauss"])
    lab = to_lab(img)
    h, w = lab.shape[:2]

    # exemplar list: legend swatches + optional on-map samples (grid px)
    code_idx = {s[0]: i for i, s in enumerate(swatches)}
    ex_lab = [s[2] for s in swatches]
    ex_cls = list(range(len(swatches)))
    r = cfg.get("map_sample_radius", 5)
    # negatives: colors that mimic a class but mean "no designation"
    # (e.g. black text over yellow smears to the exact hue of the greens);
    # they compete as exemplars of class 0
    for ms in cfg.get("map_samples", []) + cfg.get("negatives", []):
        med = np.median(
            lab[ms["y"] - r:ms["y"] + r, ms["x"] - r:ms["x"] + r]
            .reshape(-1, 3), axis=0)
        code = ms.get("code")
        print(f"  +map {code or 'NEGATIVE':14s} ({ms['x']},{ms['y']}) "
              f"Lab=({med[0]:5.1f},{med[1]:+5.1f},{med[2]:+5.1f})")
        ex_lab.append(med)
        ex_cls.append(code_idx[code] if code else -1)
    ex_lab = np.float32(ex_lab)
    ex_cls = np.int32(ex_cls)

    # nearest exemplar; a/b weighted over L (prints fade uniformly in
    # lightness but keep hue)
    weights = np.float32([0.6, 1.0, 1.0])
    flat = lab.reshape(-1, 3)
    bestd = np.full(flat.shape[0], np.inf, np.float32)
    bestex = np.zeros(flat.shape[0], np.uint16)
    for i, e in enumerate(ex_lab):
        d = np.linalg.norm((flat - e) * weights, axis=1)
        m = d < bestd
        bestd[m] = d[m]
        bestex[m] = i
    cls = (ex_cls[bestex] + 1).astype(np.uint8)  # 1-based; 0 = unclassified
    chroma = np.hypot(flat[:, 1], flat[:, 2])
    # scanned ink is much lighter than true black, and near-white classes
    # (2024 oah-low) force a tight white chroma bound — both per-edition
    black_l = cfg.get("black_l", BLACK_L)
    white_chroma = cfg.get("white_chroma", WHITE_CHROMA)
    cls[bestd > MAX_LAB_DIST] = 0
    cls[(flat[:, 0] > WHITE_L) & (chroma < white_chroma)] = 0
    cls[(flat[:, 0] < black_l) & (chroma < BLACK_CHROMA)] = 0

    # ink masks come from the UNBLURRED image: the median filter eats thin
    # street casings entirely, leaving a colored smear with no black nearby
    flat0 = lab0.reshape(-1, 3)
    chroma0 = np.hypot(flat0[:, 1], flat0[:, 2])
    white0 = (flat0[:, 0] > WHITE_L) & (chroma0 < white_chroma)
    black0 = (flat0[:, 0] < black_l) & (chroma0 < BLACK_CHROMA)
    # ink blur ring: pixels bordering black lines/text read as a darkened
    # smear of the underlying paint and match the darker classes
    k = 2 * INK_HALO + 1
    halo = cv2.dilate(black0.reshape(h, w).astype(np.uint8),
                      np.ones((k, k), np.uint8))
    cls[halo.ravel() > 0] = 0

    # street-ness: fraction of bare-paper/ink pixels in a window. Gray fills
    # and street-network-on-paper have the same blurred color, so raw
    # (non-parcel) pixels are only kept where the fill is locally solid.
    # Inside parcels color is trusted — a parcel is never a road.
    street_frac = cv2.boxFilter(
        (white0 | black0).reshape(h, w).astype(np.float32), -1,
        (SOLID_WIN, SOLID_WIN))

    cls = cls.reshape(h, w)
    cls[county_mask == 0] = 0        # outside Arlington: water, DC, margins
    street_frac = street_frac.reshape(h, w)

    # some classes are only legible in known places (the com-office red
    # crosshatch reads identically to label ink over red everywhere else)
    for code, boxes in cfg.get("regions", {}).items():
        allowed = np.zeros((h, w), bool)
        for x0, y0, x1, y1 in boxes:
            allowed[y0:y1, x0:x1] = True
        cls[(cls == code_idx[code] + 1) & ~allowed] = 0

    # GLUP designations are big contiguous swathes: anything that survives
    # the ink halo but is only a few pixels wide (label glyphs, symbols,
    # street casings) is print noise, not a designation. Classes drawn as
    # a hatch pattern ("textured") fragment by nature and are exempt —
    # they should be geographically bounded via "regions" instead.
    kern = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * OPEN_RADIUS + 1, 2 * OPEN_RADIUS + 1))
    textured = {code_idx[c] + 1 for c in cfg.get("textured", [])}
    for c in range(1, len(swatches) + 1):
        if c in textured:
            continue
        m = (cls == c).astype(np.uint8)
        if not m.any():
            continue
        opened = cv2.morphologyEx(m, cv2.MORPH_OPEN, kern)
        cls[(m > 0) & (opened == 0)] = 0

    OUT.mkdir(parents=True, exist_ok=True)
    write_tif(OUT / f"{year}_raw.tif", cls)

    # parcel plurality vote
    pid = parcel_ids.ravel()
    c = cls.ravel().astype(np.int64)
    n_class = len(swatches) + 1
    combo = pid.astype(np.int64) * n_class + c
    counts = np.bincount(combo, minlength=(parcel_ids.max() + 1) * n_class)
    counts = counts.reshape(-1, n_class)          # [parcel, class] px counts
    classified = counts[:, 1:]                    # drop unclassified col
    totals = classified.sum(axis=1)
    parcel_px = np.bincount(pid, minlength=counts.shape[0])

    # vote by class FAMILY, then take the top class within the winning
    # family: near-identical tints (the 1961 greens) otherwise split a
    # parcel's vote three ways and lose to noise or fall under the share
    # threshold ("family" in the legend config, default = own class)
    fams = [c.get("family", c["code"]) for c in cfg["classes"]]
    fam_ids = {f: i for i, f in enumerate(dict.fromkeys(fams))}
    fam_of = np.array([fam_ids[f] for f in fams])
    famcounts = np.zeros((counts.shape[0], len(fam_ids)), np.int64)
    for ci in range(len(fams)):
        famcounts[:, fam_of[ci]] += classified[:, ci]
    top_fam = famcounts.argmax(axis=1)
    in_top_fam = fam_of[None, :] == top_fam[:, None]
    winner = np.where(in_top_fam, classified, 0).argmax(axis=1) + 1
    share = np.where(totals > 0,
                     famcounts.max(axis=1) / np.maximum(totals, 1), 0)
    # the totals floor also catches genuinely unpainted (white) parcels:
    # the white cut (plus negative exemplars) leaves them nothing to vote
    # with, while even a tiny painted lot keeps a handful of valid pixels
    winner[(share < MIN_PARCEL_SHARE) | (totals < 4)] = 0
    # a big tract can legitimately straddle several designations (the 1961
    # Four Mile Run corridor parcel is green upstream, industrial at
    # Shirlington); winner-take-all would paint it one color end to end
    large_mixed = (parcel_px > LARGE_PARCEL_PX) & (share < LARGE_PARCEL_SHARE)
    winner[large_mixed] = 0

    # outside parcels (ROW, federal land, water) keep raw pixels, but not
    # on streets: road ROW carries no designation, and the drawn street
    # (casings + infill) smears into colors that mimic the darker classes.
    # TIGER centerlines say where the streets are; also require a locally
    # solid fill for whatever remains.
    parcel_cls = winner.astype(np.uint8)[parcel_ids]
    raw_keep = cls.copy()
    raw_keep[street_frac > SOLID_MAX_STREET] = 0
    raw_keep[tiger_streets > 0] = 0
    keep_raw = (parcel_ids == 0) | large_mixed[parcel_ids]
    parcel_cls[keep_raw] = raw_keep[keep_raw]
    write_tif(OUT / f"{year}_parcel.tif", parcel_cls)

    # QA render in legend colors
    palette = np.zeros((n_class, 3), np.uint8)
    for i, s in enumerate(swatches):
        palette[i + 1] = s[3]
    qa = palette[parcel_cls]
    qa[parcel_cls == 0] = 245
    cv2.imwrite(str(OUT / f"{year}_qa.png"),
                cv2.resize(qa, (w // 2, h // 2),
                           interpolation=cv2.INTER_NEAREST))

    # per-parcel table + acreage
    with open(OUT / f"{year}_parcels.csv", "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["rpc", "class", "share", "pixels"])
        for i in np.nonzero(totals)[0]:
            code = swatches[winner[i] - 1][0] if winner[i] else "ambiguous"
            cw.writerow([parcel_rpc.get(str(i), ""), code,
                         f"{share[i]:.2f}", int(totals[i])])

    print(f"  {'designation':30s} {'acres':>9s}")
    px = np.bincount(parcel_cls.ravel(), minlength=n_class)
    for i, s in enumerate(swatches):
        print(f"  {s[0]:30s} {px[i + 1] * ACRES_PER_PX:9.0f}")
    print(f"  {'(unclassified/ROW/water)':30s} {px[0] * ACRES_PER_PX:9.0f}",
          flush=True)


def write_tif(path, arr):
    tmp = path.with_suffix(".png")
    cv2.imwrite(str(tmp), arr)
    subprocess.run(
        ["gdal_translate", "-q", "-a_srs", "EPSG:2283", "-a_ullr",
         str(BBOX[0]), str(BBOX[3]), str(BBOX[2]), str(BBOX[1]),
         "-co", "COMPRESS=DEFLATE", str(tmp), str(path)], check=True)
    tmp.unlink()


def main():
    years = sys.argv[1:] or sorted(p.stem for p in LEGENDS.glob("*.json"))
    parcel_ids = cv2.imread(str(ROOT / "work" / "ref" / "parcel_ids.tif"),
                            cv2.IMREAD_UNCHANGED).astype(np.int64)
    parcel_rpc = json.loads(
        (ROOT / "work" / "ref" / "parcel_index.json").read_text())
    county_mask = cv2.imread(str(ROOT / "work" / "ref" / "county_mask.tif"),
                             cv2.IMREAD_UNCHANGED)
    tiger = cv2.imread(str(ROOT / "work" / "ref" / "ref_streets.tif"),
                       cv2.IMREAD_UNCHANGED)
    tiger = cv2.resize(tiger, (parcel_ids.shape[1], parcel_ids.shape[0]),
                       interpolation=cv2.INTER_NEAREST)
    k = 2 * STREET_DILATE + 1
    tiger = cv2.dilate(tiger, np.ones((k, k), np.uint8))
    for year in years:
        classify_year(year, parcel_ids, parcel_rpc, county_mask, tiger)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Classify each edition's pixels into GLUP designations by legend color.

For each year with a classify/legends/{year}.json config:
  1. Sample class exemplar colors from the legend swatches on the SHEET
     render (work/rgb) — the swatches are printed/scanned through the same
     process as the map, so they are perfect per-edition training data.
  2. Warp the georeferenced edition onto the 8 ft/px county grid, blur away
     halftone screens, and label each pixel by nearest exemplar in Lab space
     (with white-paper / black-ink exclusion and a max-distance cutoff).
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
MIN_PARCEL_SHARE = 0.5     # plurality must cover this share of classified px
ACRES_PER_PX = (TR * TR) / 43560.0


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


def classify_year(year, parcel_ids, parcel_rpc, county_mask):
    cfg = json.loads((LEGENDS / f"{year}.json").read_text())
    swatches = sample_swatches(year, cfg)
    print(f"=== {year}: {len(swatches)} classes")
    for code, _, lab, _ in swatches:
        print(f"  {code:18s} Lab=({lab[0]:5.1f},{lab[1]:+5.1f},{lab[2]:+5.1f})")

    img = county_grid_rgb(year)
    img = cv2.medianBlur(img, 5)
    img = cv2.GaussianBlur(img, (0, 0), 2.0)
    lab = to_lab(img)
    h, w = lab.shape[:2]

    # distance to each exemplar; a/b weighted over L (prints fade uniformly
    # in lightness but keep hue)
    weights = np.float32([0.6, 1.0, 1.0])
    flat = lab.reshape(-1, 3)
    dists = np.stack([
        np.linalg.norm((flat - s[2]) * weights, axis=1) for s in swatches])
    best = np.argmin(dists, axis=0).astype(np.uint8)
    bestd = dists[best, np.arange(flat.shape[0])]
    cls = (best + 1).astype(np.uint8)            # 1-based; 0 = unclassified
    chroma = np.hypot(flat[:, 1], flat[:, 2])
    cls[bestd > MAX_LAB_DIST] = 0
    cls[(flat[:, 0] > WHITE_L) & (chroma < WHITE_CHROMA)] = 0
    cls[flat[:, 0] < BLACK_L] = 0
    cls = cls.reshape(h, w)
    cls[county_mask == 0] = 0        # outside Arlington: water, DC, margins

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
    winner = classified.argmax(axis=1) + 1
    share = np.where(totals > 0,
                     classified.max(axis=1) / np.maximum(totals, 1), 0)
    winner[(share < MIN_PARCEL_SHARE) | (totals < 4)] = 0

    parcel_cls = winner.astype(np.uint8)[parcel_ids]
    parcel_cls[parcel_ids == 0] = cls[parcel_ids == 0]  # ROW etc: keep raw
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
    for year in years:
        classify_year(year, parcel_ids, parcel_rpc, county_mask)


if __name__ == "__main__":
    main()

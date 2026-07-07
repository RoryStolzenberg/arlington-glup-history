#!/usr/bin/env python3
"""Quantitative georeferencing audit: measure each edition's misalignment
against the 2024 GeoPDF ground truth.

Every edition is warped onto a common county-bbox grid; street masks are
phase-correlated (whole image + 2x2 quadrants). Reports offset in feet.
A correct edition shows |offset| under ~100 ft in all cells; a shifted or
rotated one shows large / inconsistent offsets.

Usage: verify.py [names...]   (default: all *-front in work/georef)
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corr_match import streets
from georef import COUNTY_BBOX

ROOT = Path(__file__).resolve().parent.parent
GEOREF = ROOT / "work" / "georef"
VER = ROOT / "work" / "verify"

TR = 16  # ft per pixel on the comparison grid


def county_grid(name):
    """Warp edition onto the common county grid (cached)."""
    VER.mkdir(exist_ok=True)
    out = VER / f"{name}.tif"
    if not out.exists():
        x0, y0, x1, y1 = COUNTY_BBOX
        subprocess.run(
            ["gdalwarp", "-q", "-te", str(x0), str(y0), str(x1), str(y1),
             "-tr", str(TR), str(TR), "-r", "bilinear",
             str(GEOREF / f"{name}.tif"), str(out)], check=True)
    img = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    return img


def offset(a, b):
    """Phase-correlation shift (b relative to a), px."""
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(
        a.astype(np.float32), b.astype(np.float32), win)
    return dx, dy, resp


def main():
    names = sys.argv[1:] or sorted(
        p.stem for p in GEOREF.glob("*-front.tif") if not p.stem.startswith("_"))
    # absolute reference: TIGER street centerlines (see scripts/make_ref.sh).
    # Never verify against another edition's raster: north-up sheets tuck
    # legend/notes text INSIDE the county bbox and furniture dominates.
    rimg = cv2.imread(str(ROOT / "work" / "ref" / "ref_streets.tif"),
                      cv2.IMREAD_GRAYSCALE)
    soft = cv2.GaussianBlur(rimg.astype(np.float32) / 255, (0, 0), 3.0)
    ref = soft / (soft.max() + 1e-6)
    h, w = ref.shape
    print(f"grid {w}x{h} @ {TR} ft/px vs TIGER roads; offsets in FEET "
          f"(dx east+, dy south+)")
    print(f"{'edition':14s} {'full_dx':>8s} {'full_dy':>8s} {'resp':>6s}  "
          f"quadrant offsets (dx,dy)")
    for name in names:
        try:
            img = streets(county_grid(name))
        except Exception as e:
            print(f"{name:14s} ERROR {e}")
            continue
        dx, dy, resp = offset(ref, img)
        cells = []
        for qy in range(2):
            for qx in range(2):
                ra = ref[qy * h // 2:(qy + 1) * h // 2,
                         qx * w // 2:(qx + 1) * w // 2]
                rb = img[qy * h // 2:(qy + 1) * h // 2,
                         qx * w // 2:(qx + 1) * w // 2]
                qdx, qdy, qresp = offset(ra, rb)
                cells.append(f"({qdx * TR:+5.0f},{qdy * TR:+5.0f})"
                             if qresp > 0.03 else "(  low sig  )")
        flag = " <-- BAD" if max(abs(dx), abs(dy)) * TR > 150 else ""
        print(f"{name:14s} {dx * TR:8.0f} {dy * TR:8.0f} {resp:6.3f}  "
              f"{' '.join(cells)}{flag}", flush=True)


if __name__ == "__main__":
    main()

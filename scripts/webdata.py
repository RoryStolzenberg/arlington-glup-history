#!/usr/bin/env python3
"""Export static data for the web viewer's parcel-history + legend UI.

Writes to docs/data/:
  parcel_ids.png   half-resolution (16 ft/px) county grid with the parcel
                   index encoded in RGB (R = low byte, G = mid, B = high).
                   Half res keeps the canvas under iOS's ~16.7 Mpx limit.
  history.json     years, grid metadata, and per-parcel: RPC, half-grid
                   bbox, and a 21-char base-36 string of per-year class
                   indices (0 = unclassified/ambiguous, i+1 = i-th class
                   in that year's legend config).
  legends.json     per year: [{code, name, color}] in printed legend
                   order, colors sampled from the sheet swatches.
"""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import classify  # noqa: E402  (sample_swatches, BBOX)

OUT = ROOT / "docs" / "data"
LEGENDS = ROOT / "classify" / "legends"
CLASSIFY_OUT = ROOT / "work" / "classify"

B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def main():
    OUT.mkdir(exist_ok=True)
    years = sorted(p.stem for p in LEGENDS.glob("*.json"))

    ids = cv2.imread(str(ROOT / "work" / "ref" / "parcel_ids.tif"),
                     cv2.IMREAD_UNCHANGED).astype(np.int64)
    half = ids[::2, ::2]
    h, w = half.shape
    png = np.zeros((h, w, 3), np.uint8)
    png[..., 2] = half & 255          # R
    png[..., 1] = (half >> 8) & 255   # G
    png[..., 0] = (half >> 16) & 255  # B
    cv2.imwrite(str(OUT / "parcel_ids.png"), png)

    rpc_map = json.loads(
        (ROOT / "work" / "ref" / "parcel_index.json").read_text())
    n = max(int(k) for k in rpc_map) + 1

    # per-parcel bbox on the half grid (parcels smaller than one half-res
    # pixel drop out of the raster and stay null = not clickable)
    ys, xs = np.nonzero(half > 0)
    pid = half[ys, xs]
    bx0 = np.full(n, w, np.int32); by0 = np.full(n, h, np.int32)
    bx1 = np.full(n, -1, np.int32); by1 = np.full(n, -1, np.int32)
    np.minimum.at(bx0, pid, xs); np.minimum.at(by0, pid, ys)
    np.maximum.at(bx1, pid, xs); np.maximum.at(by1, pid, ys)

    legends = {}
    hist = [["0"] * len(years) for _ in range(n)]
    for yi, year in enumerate(years):
        cfg = json.loads((LEGENDS / f"{year}.json").read_text())
        sw = classify.sample_swatches(year, cfg)
        legends[year] = [
            {"code": code, "name": name,
             "color": "#%02x%02x%02x" % (int(bgr[2]), int(bgr[1]),
                                         int(bgr[0]))}
            for code, name, _, bgr in sw]
        code_idx = {s[0]: i for i, s in enumerate(sw)}
        by_rpc = {}
        with open(CLASSIFY_OUT / f"{year}_parcels.csv") as f:
            for row in csv.DictReader(f):
                by_rpc[row["rpc"]] = row["class"]
        for k, rpc in rpc_map.items():
            code = by_rpc.get(rpc)
            if code and code in code_idx:
                hist[int(k)][yi] = B36[code_idx[code] + 1]

    (OUT / "legends.json").write_text(json.dumps(legends))

    doc = {
        "years": years,
        "meta": {"x0": classify.BBOX[0], "y1": classify.BBOX[3],
                 "tr": classify.TR * 2, "w": w, "h": h,
                 "crs": "EPSG:2283"},
        "rpc": [rpc_map.get(str(i), "") for i in range(n)],
        "hist": ["".join(hh) for hh in hist],
        "bbox": [None if bx1[i] < 0 else
                 [int(bx0[i]), int(by0[i]), int(bx1[i]), int(by1[i])]
                 for i in range(n)],
    }
    (OUT / "history.json").write_text(json.dumps(doc))

    classified = sum(1 for hh in doc["hist"] if hh != "0" * len(years))
    print(f"{n} parcels ({classified} with history), grid {w}x{h}")
    for f in ("parcel_ids.png", "history.json", "legends.json"):
        print(f"  {f}: {(OUT / f).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render each edition's parcel-voted classification as a GeoTIFF in one
standardized palette, for the /standardized/ viewer's tiles.

Every year is painted with the same canonical class set and colors, so the
timeline and compare slider show designation change rather than print
differences. Pre-1975 classes are placed under the nearest modern density
band, Public/Semi-Public/greenway share one green, and parcels the vote left
unassigned take the plurality raw class inside them (whole-parcel fill, as
on the printed posters). Street ROW and land outside the county are
transparent, so the basemap shows through.

  work/classify/{year}_parcel.tif + _raw.tif  ->  work/standardized/{year}-front.tif

The palette below is the shared standard (mirrored by _junk/postermap.py and
docs/standardized/config.js); keep the three copies identical.

Usage: standardize.py [years...]
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import classify  # noqa: E402  (BBOX)

OUT = ROOT / "work" / "standardized"
LEGENDS = json.loads((ROOT / "docs" / "data" / "legends.json").read_text())

# canonical class set: (code, label, hex) in display order
CANON = [
    ("res-low",        "Res Low  (0-10 u/ac)",          "f2e88c"),
    ("res-low-11-15",  "Res Low  (11-15 u/ac)",         "e6c944"),
    ("res-lowmed",     "Res Low-Medium  (16-36)",       "e89e54"),
    ("res-med",        "Res Medium  (37-72)",           "c97b4a"),
    ("res-highmed",    "Res High-Medium  (3.24 FAR)",   "8c4a2f"),
    ("res-high",       "Res High  (4.8 FAR)",           "521c1c"),
    ("svc-commercial", "Service Commercial",            "f28c9c"),
    ("com-general",    "General Commercial",            "d92b2b"),
    ("svc-industry",   "Industrial / Service Industry", "c9308f"),
    ("public",         "Public / Semi-Public",          "74c169"),
    ("gov-community",  "Government & Community",        "b5b294"),
    ("oah-low",        "Off-Apt-Hotel Low",             "a8d4ee"),
    ("oah-med",        "Off-Apt-Hotel Medium",          "4a9ede"),
    ("oah-high",       "Off-Apt-Hotel High",            "1f5fb0"),
    ("mu-med",         "Mixed-Use Medium",              "d9a8d9"),
    ("mu-highmed",     "Mixed-Use High-Medium",         "a55fc0"),
    ("mu-coord",       "Coordinated Mixed-Use",         "6a1f9e"),
]
# per-year legend code -> canonical slot, by density band rather than name
ALIAS = {
    "res-low-1-10": "res-low",
    "res-lowmed@60s": "res-low-11-15",   # 9-13 two-family
    "res-highmed@60s": "res-lowmed",     # 14-39 multi-family ~ 16-36 band
    "apt-office": "oah-med",
    "com-office": "oah-high",
    "com-neighborhood": "svc-commercial",
    "industrial": "svc-industry",
    "greenway": "public",
    "semi-public": "public",
}
IDX = {c[0]: i for i, c in enumerate(CANON)}


def canon_slot(code, year):
    if int(year) < 1975 and code in ("res-lowmed", "res-highmed"):
        code = ALIAS[code + "@60s"]
    return IDX[ALIAS.get(code, code)]


def filled_classes(year, county, pid):
    """Parcel-voted class raster with unassigned parcels filled by the
    plurality raw class inside them. Returns per-year legend indices."""
    voted = cv2.imread(str(ROOT / "work" / "classify" / f"{year}_parcel.tif"),
                       cv2.IMREAD_UNCHANGED)
    raw = cv2.imread(str(ROOT / "work" / "classify" / f"{year}_raw.tif"),
                     cv2.IMREAD_UNCHANGED)
    onp = county & (pid > 0)
    ids, pv, rv = pid[onp], voted[onp], raw[onp]
    n = int(pid.max()) + 1
    assigned = np.zeros(n, np.uint8)
    np.maximum.at(assigned, ids, pv)
    area = np.bincount(ids, minlength=n)
    gaps = np.nonzero((assigned == 0) & (area > 0))[0]
    compact = np.full(n, -1, np.int32)
    compact[gaps] = np.arange(len(gaps))
    k = int(raw.max()) + 1
    sel = (compact[ids] >= 0) & (rv > 0)
    counts = np.bincount(compact[ids[sel]].astype(np.int64) * k + rv[sel],
                         minlength=len(gaps) * k).reshape(len(gaps), k)
    best, votes = counts.argmax(1), counts.max(1)
    plurality = np.zeros(n, np.uint8)
    plurality[gaps[votes > 0]] = best[votes > 0].astype(np.uint8)
    out = pv.copy()
    byparcel = plurality[ids]
    z = (out == 0) & (byparcel > 0)
    out[z] = byparcel[z]
    full = voted.copy()
    full[onp] = out
    return full


def main():
    years = sys.argv[1:] or sorted(LEGENDS)
    OUT.mkdir(parents=True, exist_ok=True)
    county = cv2.imread(str(ROOT / "work" / "ref" / "county_mask.tif"),
                        cv2.IMREAD_UNCHANGED) > 0
    pid = cv2.imread(str(ROOT / "work" / "ref" / "parcel_ids.tif"),
                     cv2.IMREAD_UNCHANGED).astype(np.int64)
    bgra = np.zeros((256, 4), np.uint8)
    for s, (_, _, hx) in enumerate(CANON):
        bgra[s + 1] = (int(hx[4:6], 16), int(hx[2:4], 16), int(hx[0:2], 16), 255)

    for year in years:
        codes = [c["code"] for c in LEGENDS[year]]
        lut = np.zeros(256, np.uint8)
        for i, code in enumerate(codes):
            lut[i + 1] = canon_slot(code, year) + 1
        idx = lut[filled_classes(year, county, pid)]
        idx[~county] = 0
        img = bgra[idx]
        png = OUT / f"{year}-front.png"
        tif = OUT / f"{year}-front.tif"
        cv2.imwrite(str(png), img)
        b = classify.BBOX
        subprocess.run(
            ["gdal_translate", "-q", "-a_srs", "EPSG:2283", "-a_ullr",
             str(b[0]), str(b[3]), str(b[2]), str(b[1]),
             "-co", "COMPRESS=DEFLATE", str(png), str(tif)], check=True)
        png.unlink()
        print(f"{year}: {tif.name}  painted {(idx > 0).mean() * 100:.1f}% of grid",
              flush=True)


if __name__ == "__main__":
    main()

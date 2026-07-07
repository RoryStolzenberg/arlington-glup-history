#!/usr/bin/env python3
"""Test corr_match on the SIFT-resistant 1983 <-> 1987 pair."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from corr_match import corr_match

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "work" / "qa"

src = cv2.imread(str(ROOT / "work/rgb/1983-front.tif"), cv2.IMREAD_GRAYSCALE)
dst = cv2.imread(str(ROOT / "work/georef/1987-front.tif"),
                 cv2.IMREAD_GRAYSCALE)
print("src", src.shape, "dst", dst.shape, flush=True)

src_pts, dst_pts, resp = corr_match(src, dst)
if src_pts is None:
    print("FAILED")
    sys.exit(1)

H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 25.0)
proj = cv2.perspectiveTransform(src_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
rms = float(np.sqrt(np.mean(np.sum((proj - dst_pts) ** 2, axis=1))))
print(f"H rms={rms:.1f}px (full res), inliers={int(mask.sum())}/{len(src_pts)}")

# visual check: warp src to dst frame at 1/4 scale, blend
s = 0.25
dsmall = cv2.resize(dst, None, fx=s, fy=s)
Ssc = np.diag([s, s, 1.0])
Hs = Ssc @ H @ np.linalg.inv(Ssc)
wsrc = cv2.warpPerspective(cv2.resize(src, None, fx=s, fy=s), Hs,
                           (dsmall.shape[1], dsmall.shape[0]))
blend = (dsmall.astype(np.float32) * 0.5 + wsrc.astype(np.float32) * 0.5)
cv2.imwrite(str(OUT / "corr_1983_vs_1987.jpg"), blend.astype(np.uint8))
print("wrote", OUT / "corr_1983_vs_1987.jpg")

#!/usr/bin/env python3
"""Run corr_match 1983 vs 1987 without validator; render blend AND probe
positions to determine whether the transform or the gate is wrong."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from corr_match import corr_match
from georef import COUNTY_BBOX, geotransform_of

SCR = Path("/tmp/claude-1000/-home-rory-Documents-GitHub-sandbox-2026-arlington-glup/fa683da4-ba28-491b-88c5-d44c526ee72b/scratchpad")

src = cv2.imread(str(ROOT / "work/rgb/1983-front.tif"), cv2.IMREAD_GRAYSCALE)
dst_path = ROOT / "work/georef/1987-front.tif"
dst = cv2.imread(str(dst_path), cv2.IMREAD_GRAYSCALE)

src_pts, dst_pts, resp = corr_match(src, dst, validate=None)
print(f"accepted candidate resp={resp:.3f} n={len(src_pts)}")

gt = geotransform_of(dst_path)
A, inl = cv2.estimateAffinePartial2D(np.float32(dst_pts), np.float32(src_pts),
                                     ransacReprojThreshold=80.0)
print("similarity dst->src:\n", A)
print("similarity inliers:", int(inl.sum()), "/", len(dst_pts))

x0, y0, x1, y1 = COUNTY_BBOX
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
probes = [("center", cx, cy), ("S", cx, y0), ("N", cx, y1),
          ("W", x0, cy), ("E", x1, cy)]
pp = np.float32([[(gx - gt[0]) / gt[1], (gy - gt[3]) / gt[5]]
                 for _, gx, gy in probes])
back = cv2.transform(pp.reshape(-1, 1, 2), A).reshape(-1, 2)
print(f"src sheet is {src.shape[1]}x{src.shape[0]}")
for (label, _, _), (px, py), (dx, dy) in zip(probes, back, pp):
    print(f"  {label:6s} dstpx=({dx:7.0f},{dy:7.0f}) -> srcpx=({px:7.0f},{py:7.0f})")

# blend via homography for visual check
H, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 25.0)
s = 0.25
dsmall = cv2.resize(dst, None, fx=s, fy=s)
Ssc = np.diag([s, s, 1.0])
Hs = Ssc @ H @ np.linalg.inv(Ssc)
wsrc = cv2.warpPerspective(cv2.resize(src, None, fx=s, fy=s), Hs,
                           (dsmall.shape[1], dsmall.shape[0]))
blend = (dsmall.astype(np.float32) * 0.5 + wsrc.astype(np.float32) * 0.5)
bl = blend.astype(np.uint8)
# draw probes (dst px * s)
for (label, _, _), (dx, dy) in zip(probes, pp):
    cv2.circle(bl, (int(dx * s), int(dy * s)), 12, 255, 3)
cv2.imwrite(str(SCR / "gate_debug.jpg"), bl)
print("wrote gate_debug.jpg")

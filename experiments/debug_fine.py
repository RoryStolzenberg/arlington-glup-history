#!/usr/bin/env python3
"""Visualize refined coarse alignment + fine grid match vectors for 1983."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from corr_match import coarse_align, gradient, _thumb, _grid_pass, FINE_DIM

SCR = Path("/tmp/claude-1000/-home-rory-Documents-GitHub-sandbox-2026-arlington-glup/fa683da4-ba28-491b-88c5-d44c526ee72b/scratchpad")

src = cv2.imread(str(ROOT / "work/rgb/1983-front.tif"), cv2.IMREAD_GRAYSCALE)
dst = cv2.imread(str(ROOT / "work/georef/1987-front.tif"), cv2.IMREAD_GRAYSCALE)

M, resp = coarse_align(src, dst)
print(f"coarse resp={resp:.3f}")

dst_w, ds = _thumb(dst, FINE_DIM)
dst_g = gradient(dst_w)
dh, dw = dst_g.shape
S = np.diag([ds, ds, 1.0])
Mf = S @ M
src_warp = cv2.warpPerspective(src, Mf.astype(np.float64), (dw, dh))
src_g = gradient(src_warp)

# blend at 1/4 for viewing
s = 0.25
rs = cv2.resize(src_g, None, fx=s, fy=s); rd = cv2.resize(dst_g, None, fx=s, fy=s)
blend = np.zeros((rs.shape[0], rs.shape[1], 3), np.float32)
blend[:, :, 2] = rs * 255 * 2
blend[:, :, 1] = rd[:rs.shape[0], :rs.shape[1]] * 255 * 2
cv2.imwrite(str(SCR / "fine_coarsewarp.jpg"),
            np.clip(blend, 0, 255).astype(np.uint8))

a, b = _grid_pass(src_g, dst_g, 420, 0.22)
print(f"{len(a)} raw matches")
vec = np.clip(blend, 0, 255).astype(np.uint8).copy()
for (ax, ay), (bx, by) in zip(a, b):
    p1 = (int(ax * s), int(ay * s))
    p2 = (int(bx * s), int(by * s))
    cv2.arrowedLine(vec, p1, p2, (255, 255, 255), 2, tipLength=0.3)
d = b - a
print("displacement stats: median", np.median(d, axis=0),
      "mad", np.median(np.abs(d - np.median(d, axis=0)), axis=0))
cv2.imwrite(str(SCR / "fine_vectors.jpg"), vec)
print("wrote fine_coarsewarp.jpg / fine_vectors.jpg (red=1983, green=1987)")

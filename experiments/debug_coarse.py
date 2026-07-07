#!/usr/bin/env python3
"""Visualize coarse_align candidates for 1983 <-> 1987."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from corr_match import gradient, _thumb, _pad_to, COARSE_DIM

SCR = Path("/tmp/claude-1000/-home-rory-Documents-GitHub-sandbox-2026-arlington-glup/fa683da4-ba28-491b-88c5-d44c526ee72b/scratchpad")

src = cv2.imread(str(ROOT / "work/rgb/1983-front.tif"), cv2.IMREAD_GRAYSCALE)
dst = cv2.imread(str(ROOT / "work/georef/1987-front.tif"), cv2.IMREAD_GRAYSCALE)

dst_t, ds = _thumb(dst, COARSE_DIM)
dst_g = gradient(dst_t, 1.0)
size = int(COARSE_DIM * 1.5)
dst_p = _pad_to(dst_g, size)
win = cv2.createHanningWindow((size, size), cv2.CV_32F)

src_t, ss = _thumb(src, COARSE_DIM)
src_g = gradient(src_t, 1.0)

cands = []
for sc in np.geomspace(0.6, 1.7, 15):
    h, w = src_g.shape
    sw, sh = round(w * sc), round(h * sc)
    if max(sw, sh) > size:
        continue
    scaled = cv2.resize(src_g, (sw, sh), interpolation=cv2.INTER_AREA)
    for ang in np.arange(-180, 180, 3):
        M = cv2.getRotationMatrix2D((sw / 2, sh / 2), ang, 1.0)
        cos, sin = abs(M[0, 0]), abs(M[0, 1])
        nw, nh = int(sh * sin + sw * cos), int(sh * cos + sw * sin)
        if max(nw, nh) > size:
            continue
        M[0, 2] += nw / 2 - sw / 2
        M[1, 2] += nh / 2 - sh / 2
        rot = cv2.warpAffine(scaled, M, (nw, nh))
        (dx, dy), resp = cv2.phaseCorrelate(_pad_to(rot, size), dst_p, win)
        cands.append((resp, ang, sc, -dx, -dy, sw, sh, nw, nh))

cands.sort(reverse=True)
print("top 10: resp, ang, scale, dx, dy")
for c in cands[:10]:
    print(f"  {c[0]:.4f}  ang={c[1]:6.1f}  sc={c[2]:.3f}  d=({c[3]:7.1f},{c[4]:7.1f})")

# render blend of best 3
for rank, c in enumerate(cands[:3]):
    resp, ang, sc, dx, dy, sw, sh, nw, nh = c
    scaled = cv2.resize(src_g, (sw, sh), interpolation=cv2.INTER_AREA)
    M = cv2.getRotationMatrix2D((sw / 2, sh / 2), ang, 1.0)
    M[0, 2] += nw / 2 - sw / 2
    M[1, 2] += nh / 2 - sh / 2
    rot = cv2.warpAffine(scaled, M, (nw, nh))
    rot_p = np.zeros((size, size), np.float32)
    rot_p[:nh, :nw] = rot
    T = np.float32([[1, 0, dx], [0, 1, dy]])
    shifted = cv2.warpAffine(rot_p, T, (size, size))
    rgb = np.zeros((size, size, 3), np.float32)
    rgb[:, :, 2] = shifted * 255 * 3
    rgb[:, :, 1] = dst_p * 255 * 3
    cv2.imwrite(str(SCR / f"coarse_cand{rank}.jpg"),
                np.clip(rgb, 0, 255).astype(np.uint8))
print("wrote candidate blends (red=src, green=dst)")

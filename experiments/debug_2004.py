#!/usr/bin/env python3
"""Manually run the 2004<->2013 match+warp, KEEP intermediates, and dump:
- airport-window render of the warped 2004 (vs 2013's)
- the county-grid street masks the verifier compares
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import georef as G

SCR = Path("/tmp/claude-1000/-home-rory-Documents-GitHub-sandbox-2026-arlington-glup/fa683da4-ba28-491b-88c5-d44c526ee72b/scratchpad")
name, anchor = "2004-front", "2013-front"

src_img, s_scale = G.load_gray(G.RGB / f"{name}.tif")
full_shape = (round(src_img.shape[0] / s_scale),
              round(src_img.shape[1] / s_scale))
dst_img, d_scale = G.load_gray(G.GEOREF / f"{anchor}.tif")
mask = G.county_mask(G.GEOREF / f"{anchor}.tif",
                     (round(dst_img.shape[0] / d_scale),
                      round(dst_img.shape[1] / d_scale)))
mask = cv2.resize(mask, (dst_img.shape[1], dst_img.shape[0]),
                  interpolation=cv2.INTER_NEAREST)
dst_img = cv2.bitwise_and(dst_img, dst_img, mask=mask)
src_in, dst_in, rms = G.match_pair(src_img, dst_img)
print(f"inliers={len(src_in)} rms={rms:.2f}")
sp, dp = src_in / s_scale, dst_in / d_scale

gt = G.geotransform_of(G.GEOREF / f"{anchor}.tif")
idx = G.spread_pick(sp, dp, G.N_GCPS, full_shape)
print(f"gcps={len(idx)}")
gcps = []
for i in idx:
    sx, sy = sp[i]
    dx, dy = dp[i]
    gx, gy = G.px_to_geo(gt, dx, dy)
    gcps += ["-gcp", f"{sx:.2f}", f"{sy:.2f}", f"{gx:.3f}", f"{gy:.3f}"]

tmp_gcp = SCR / "dbg2004_gcp.tif"
tmp_warp = SCR / "dbg2004_warp.tif"
G.run(["gdal_translate", "-q", "-of", "GTiff", "-a_srs", "EPSG:2283",
       *gcps, G.RGB / f"{name}.tif", tmp_gcp], quiet=True)
G.run(["gdalwarp", "-q", "-tps", "-t_srs", "EPSG:2283", "-r", "bilinear",
       "-dstalpha", "-overwrite", tmp_gcp, tmp_warp], quiet=True)

# airport window render
G.run(["gdal_translate", "-q", "-of", "PNG", "-b", "1", "-b", "2", "-b", "3",
       "-projwin", "11888000", "7003000", "11905000", "6990000",
       "-outsize", "800", "0", tmp_warp, SCR / "dbg2004_dca.png"], quiet=True)

# verifier inputs
ref = G.county_grid_streets(G.GEOREF / f"{anchor}.tif", cache_key="dbg2013")
tst = G.county_grid_streets(tmp_warp)
cv2.imwrite(str(SCR / "dbg_streets_2013.png"), (ref * 255).astype(np.uint8))
cv2.imwrite(str(SCR / "dbg_streets_2004.png"), (tst * 255).astype(np.uint8))
win = cv2.createHanningWindow((ref.shape[1], ref.shape[0]), cv2.CV_32F)
(dx, dy), resp = cv2.phaseCorrelate(ref, tst, win)
print(f"verify offset=({dx*16:+.0f},{dy*16:+.0f})ft resp={resp:.3f}")

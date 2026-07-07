#!/usr/bin/env python3
"""Tune feature matching for the hard 2004 <-> modern style jump."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RGB = ROOT / "work" / "rgb"
GEOREF = ROOT / "work" / "georef"


def load_gray(path, max_dim):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)),
                         interpolation=cv2.INTER_AREA)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    return clahe.apply(img)


def root_sift(desc):
    desc = desc / (desc.sum(axis=1, keepdims=True) + 1e-7)
    return np.sqrt(desc)


def try_match(src_path, dst_path, nfeat, ratio, max_dim, use_root, thresh):
    src = load_gray(src_path, max_dim)
    dst = load_gray(dst_path, max_dim)
    sift = cv2.SIFT_create(nfeatures=nfeat)
    k1, d1 = sift.detectAndCompute(src, None)
    k2, d2 = sift.detectAndCompute(dst, None)
    if use_root:
        d1, d2 = root_sift(d1), root_sift(d2)
    flann = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    raw = flann.knnMatch(d1, d2, k=2)
    good = [m for m, n in raw if m.distance < ratio * n.distance]
    if len(good) < 8:
        return len(k1), len(k2), len(good), 0, -1
    src_pts = np.float32([k1[m.queryIdx].pt for m in good])
    dst_pts = np.float32([k2[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, thresh)
    if H is None:
        return len(k1), len(k2), len(good), 0, -1
    inl = mask.ravel().astype(bool)
    proj = cv2.perspectiveTransform(
        src_pts[inl].reshape(-1, 1, 2), H).reshape(-1, 2)
    rms = float(np.sqrt(np.mean(np.sum((proj - dst_pts[inl]) ** 2, axis=1))))
    return len(k1), len(k2), len(good), int(inl.sum()), rms


def main():
    src = RGB / "2004-front.tif"
    anchors = ["2013-front", "2016-front", "2018-front"]
    configs = [
        dict(nfeat=20000, ratio=0.75, max_dim=4000, use_root=False, thresh=8),   # baseline
        dict(nfeat=50000, ratio=0.75, max_dim=4000, use_root=False, thresh=8),
        dict(nfeat=50000, ratio=0.80, max_dim=4000, use_root=True, thresh=8),
        dict(nfeat=50000, ratio=0.80, max_dim=6000, use_root=True, thresh=10),
    ]
    print("anchor\tnfeat\tratio\tdim\troot\tf_src\tf_dst\tmatches\tinliers\trms")
    for anchor in anchors:
        dst = GEOREF / f"{anchor}.tif"
        for c in configs:
            f1, f2, m, inl, rms = try_match(src, dst, **c)
            print(f"{anchor}\t{c['nfeat']}\t{c['ratio']}\t{c['max_dim']}\t"
                  f"{c['use_root']}\t{f1}\t{f2}\t{m}\t{inl}\t{rms:.2f}",
                  flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Preprocessing variants to crack the 1983 <-> 1987 scan-to-scan match."""
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "work" / "rgb" / "1983-front.tif"
DSTS = [ROOT / "work" / "georef" / "1987-front.tif"]


def base_gray(path, max_dim):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)),
                         interpolation=cv2.INTER_AREA)
    return img


def prep_clahe(img):
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16)).apply(img)


def prep_blur(img):
    img = cv2.GaussianBlur(img, (0, 0), 2.0)
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16)).apply(img)


def prep_grad(img):
    img = cv2.GaussianBlur(img, (0, 0), 1.5)
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    mag = np.clip(mag / (np.percentile(mag, 99) + 1e-6) * 255, 0, 255)
    return mag.astype(np.uint8)


def prep_tophat(img):
    """Bright thin structures (street lines) via white top-hat."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    th = cv2.morphologyEx(img, cv2.MORPH_TOPHAT, k)
    th = cv2.GaussianBlur(th, (0, 0), 1.5)
    return cv2.normalize(th, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def root_sift(d):
    d = d / (d.sum(axis=1, keepdims=True) + 1e-7)
    return np.sqrt(d)


def try_match(src, dst, detector):
    if detector == "sift":
        det = cv2.SIFT_create(nfeatures=50000)
        norm = None
    else:
        det = cv2.ORB_create(nfeatures=50000)
        norm = cv2.NORM_HAMMING
    k1, d1 = det.detectAndCompute(src, None)
    k2, d2 = det.detectAndCompute(dst, None)
    if d1 is None or d2 is None or len(k1) < 100 or len(k2) < 100:
        return 0, 0, -1
    if detector == "sift":
        d1, d2 = root_sift(d1), root_sift(d2)
        matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5},
                                        {"checks": 64})
    else:
        matcher = cv2.BFMatcher(norm)
    raw = matcher.knnMatch(d1, d2, k=2)
    good = [m for m, n in raw if m.distance < 0.8 * n.distance]
    if len(good) < 8:
        return len(good), 0, -1
    sp = np.float32([k1[m.queryIdx].pt for m in good])
    dp = np.float32([k2[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(sp, dp, cv2.RANSAC, 8.0)
    if H is None or mask is None:
        return len(good), 0, -1
    inl = mask.ravel().astype(bool)
    proj = cv2.perspectiveTransform(sp[inl].reshape(-1, 1, 2), H)
    if proj is None:
        return len(good), int(inl.sum()), -1
    rms = float(np.sqrt(np.mean(
        np.sum((proj.reshape(-1, 2) - dp[inl]) ** 2, axis=1))))
    return len(good), int(inl.sum()), rms


PREPS = {"clahe": prep_clahe, "blur": prep_blur, "grad": prep_grad,
         "tophat": prep_tophat}

print("dst\tprep\tdim\tdet\tmatches\tinliers\trms")
for dst_path in DSTS:
    for dim in (2500, 4000):
        for pname, pfn in PREPS.items():
            for det in ("sift", "orb"):
                s = pfn(base_gray(SRC, dim))
                d = pfn(base_gray(dst_path, dim))
                m, inl, rms = try_match(s, d, det)
                print(f"{dst_path.stem}\t{pname}\t{dim}\t{det}\t{m}\t{inl}\t"
                      f"{rms:.2f}", flush=True)

#!/usr/bin/env python3
"""Auto-georeference GLUP editions that lack embedded georeferencing.

Method: SIFT feature matching against an "anchor" edition that is already
georeferenced (either a GeoPDF extract or a previously auto-georeferenced
edition — chained so each match pair is stylistically close in era).
RANSAC homography filters matches; surviving inliers become GCPs
(scan pixel -> anchor pixel -> anchor geo via its geotransform), then
gdalwarp -tps produces the georeferenced GeoTIFF.

Outputs:
  work/georef/{name}.tif   — georeferenced result (EPSG:2283, band 4 = alpha)
  work/qa/{name}.jpg       — 50/50 blend of warped result over its anchor
  work/qa/report.tsv       — inlier counts + RMS residuals per edition
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corr_match import corr_match, streets, tiger_coarse, fine_match

ROOT = Path(__file__).resolve().parent.parent
RGB = ROOT / "work" / "rgb"
GEOREF = ROOT / "work" / "georef"
QA = ROOT / "work" / "qa"

# edition -> candidate anchors, ordered so anchors exist before their
# dependents. Anchors are nearest-in-time editions with similar cartography;
# extra candidates cover weak pairs. Backs (corridor-inset sheets) are not
# georeferenceable and are excluded.
CHAIN = [
    ("2023-front", ["2024-front"]),
    ("2019-front", ["2018-front"]),
    ("2014-front", ["2016-front"]),
    ("2013-front", ["2014-front"]),
    ("2004-front", ["1996-front", "2013-front", "2014-front"]),
    ("1996-front", ["2004-front", "2013-front"]),
    ("1990-front", ["1996-front", "2004-front"]),
    ("1987-front", ["1990-front", "1996-front"]),
    ("1983-front", ["1987-front", "1990-front"]),
    ("1979-front", ["1983-front", "1987-front"]),
    ("1975-front", ["1979-front", "1983-front"]),
    ("1966-front", ["1975-front", "1979-front"]),
    ("1964-front", ["1966-front", "1975-front"]),
    ("1961-front", ["1964-front", "1966-front"]),
]

# Arlington's bbox in EPSG:2283 (ftUS), slightly padded. Used to mask anchors
# down to real map content so shared sheet furniture (title blocks, legends)
# can't dominate correlation matching.
COUNTY_BBOX = (11861230 - 2000, 6986963 - 2000, 11900486 + 2000, 7026535 + 2000)

MIN_GCP_COVERAGE_SIFT = 20 # distinct spread_pick cells required (of ~64)
MIN_GCP_COVERAGE_CORR = 10 # corr points are grid-spread by construction

VERIFY_TR = 16             # verification grid resolution, ft/px
VERIFY_MIN_RESP = 0.04     # min phase-corr response vs TIGER street reference
                           # (known-good editions measure 0.08-0.15; old
                           # scans have sparser road networks)
VERIFY_MAX_OFFSET_FT = 150 # max acceptable global offset vs anchor

MATCH_MAX_DIM = 4000       # downscale images to this for feature matching
MIN_INLIERS = 40
RATIO = 0.8                # Lowe ratio test (RootSIFT tolerates a looser ratio)
RANSAC_THRESH = 8.0        # px, at match scale
N_GCPS = 60                # well-distributed inliers promoted to GCPs
N_FEATURES = 50000         # SIFT keypoint budget; busy map sheets need lots
CORR_MIN_POINTS = 12       # correlation fallback: grid GCPs are sparse but strong


def run(cmd, quiet=False, **kw):
    if not quiet:
        print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def load_gray(path: Path):
    """Load image downscaled to MATCH_MAX_DIM, CLAHE-normalized.

    Returns (gray, scale) where full_res_px = matched_px / scale.
    """
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    h, w = img.shape
    scale = min(1.0, MATCH_MAX_DIM / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)),
                         interpolation=cv2.INTER_AREA)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    return clahe.apply(img), scale


def geotransform_of(path: Path):
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", str(path)], capture_output=True, text=True,
        check=True).stdout)
    return info["geoTransform"]


def px_to_geo(gt, x, y):
    gx = gt[0] + x * gt[1] + y * gt[2]
    gy = gt[3] + x * gt[4] + y * gt[5]
    return gx, gy


def county_mask(geo_path, shape):
    """uint8 mask of COUNTY_BBOX in a georeferenced raster's pixel frame."""
    gt = geotransform_of(geo_path)
    x0, y0, x1, y1 = COUNTY_BBOX
    # north-up rasters: invert the affine per-axis
    px0 = int((x0 - gt[0]) / gt[1])
    px1 = int((x1 - gt[0]) / gt[1])
    py0 = int((y1 - gt[3]) / gt[5])   # y1 (north) maps to smaller row
    py1 = int((y0 - gt[3]) / gt[5])
    mask = np.zeros(shape[:2], np.uint8)
    h, w = shape[:2]
    mask[max(0, py0):min(h, py1), max(0, px0):min(w, px1)] = 255
    return mask


def county_crop(anchor):
    """Anchor raster cropped to COUNTY_BBOX (cached); pure map content."""
    crop = GEOREF / f"_{anchor}_countycrop.tif"
    if not crop.exists():
        x0, y0, x1, y1 = COUNTY_BBOX
        run(["gdal_translate", "-q", "-projwin", x0, y1, x1, y0,
             GEOREF / f"{anchor}.tif", crop], quiet=True)
    return crop


def center_gate(src_pts, dst_pts, gt, full_shape, margin=0.25):
    """Sanity check: every county-bbox corner must land inside the source
    sheet (every GLUP sheet contains the whole county). Rejects
    self-consistent-but-wrong match consensuses (sheet furniture locks,
    mask-edge locks) that shift the result by a fraction of the county."""
    # Similarity fit (not homography): a flat scanned sheet is
    # rotation+scale+shift, and perspective terms fitted to clustered points
    # extrapolate wildly at the county extremes.
    A, _ = cv2.estimateAffinePartial2D(np.float32(dst_pts),
                                       np.float32(src_pts),
                                       ransacReprojThreshold=80.0)
    if A is None:
        return False
    x0, y0, x1, y1 = COUNTY_BBOX
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # The bbox EDGE MIDPOINTS approximate the diamond county's N/E/S/W
    # extremes — always drawn on the sheet (bbox corners are not: they cover
    # empty neighbor-jurisdiction triangles and rotate off-sheet legitimately)
    probes = [(cx, cy), (cx, y0), (cx, y1), (x0, cy), (x1, cy)]
    # geo -> anchor px (invert north-up affine) -> src px (dst->src affine)
    probes_px = np.float32([
        [(gx - gt[0]) / gt[1], (gy - gt[3]) / gt[5]] for gx, gy in probes])
    back = cv2.transform(probes_px.reshape(-1, 1, 2), A)
    if back is None:
        return False
    h, w = full_shape
    for px, py in back.reshape(-1, 2):
        if not (-margin * w <= px <= (1 + margin) * w and
                -margin * h <= py <= (1 + margin) * h):
            print(f"  center gate: county probe -> ({px:.0f},{py:.0f}) "
                  f"outside sheet {w}x{h}", flush=True)
            return False
    return True


def spread_pick(pts_src, pts_dst, n, img_shape):
    """Pick up to n point pairs spread across a grid so GCPs cover the sheet."""
    h, w = img_shape
    cells = int(np.ceil(np.sqrt(n)))
    picked = []
    used = set()
    for i, (s, d) in enumerate(zip(pts_src, pts_dst)):
        cx, cy = int(s[0] / w * cells), int(s[1] / h * cells)
        if (cx, cy) in used:
            continue
        used.add((cx, cy))
        picked.append(i)
        if len(picked) >= n:
            break
    return picked


def root_sift(desc):
    """L1-normalize + sqrt (RootSIFT) — markedly better across map styles."""
    desc = desc / (desc.sum(axis=1, keepdims=True) + 1e-7)
    return np.sqrt(desc)


def match_pair(src_img, dst_img):
    sift = cv2.SIFT_create(nfeatures=N_FEATURES)
    k1, d1 = sift.detectAndCompute(src_img, None)
    k2, d2 = sift.detectAndCompute(dst_img, None)
    d1, d2 = root_sift(d1), root_sift(d2)
    print(f"  features: src={len(k1)} dst={len(k2)}", flush=True)
    flann = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    raw = flann.knnMatch(d1, d2, k=2)
    good = [m for m, n in raw if m.distance < RATIO * n.distance]
    print(f"  ratio-test matches: {len(good)}", flush=True)
    if len(good) < MIN_INLIERS:
        return None, None, None
    src_pts = np.float32([k1[m.queryIdx].pt for m in good])
    dst_pts = np.float32([k2[m.trainIdx].pt for m in good])
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, RANSAC_THRESH)
    if H is None or mask is None:
        return None, None, None
    inl = mask.ravel().astype(bool)
    src_in, dst_in = src_pts[inl], dst_pts[inl]
    # residuals under H (perspectiveTransform yields None for a degenerate H)
    proj = cv2.perspectiveTransform(src_in.reshape(-1, 1, 2), H)
    if proj is None:
        return None, None, None
    proj = proj.reshape(-1, 2)
    rms = float(np.sqrt(np.mean(np.sum((proj - dst_in) ** 2, axis=1))))
    print(f"  RANSAC inliers: {inl.sum()}  rms={rms:.2f}px", flush=True)
    return src_in, dst_in, rms


def county_grid_streets(tif_path):
    """Street mask of a raster warped onto the common county-bbox grid."""
    x0, y0, x1, y1 = COUNTY_BBOX
    grid = GEOREF / "_grid_tmp.tif"
    grid.unlink(missing_ok=True)
    run(["gdalwarp", "-q", "-te", x0, y0, x1, y1,
         "-tr", VERIFY_TR, VERIFY_TR, "-r", "bilinear",
         tif_path, grid], quiet=True)
    img = cv2.imread(str(grid), cv2.IMREAD_GRAYSCALE)
    return streets(img)


_REF_STREETS = None


def ref_streets():
    """Blurred rasterization of TIGER street centerlines on the county grid
    — an absolute, furniture-free, style-free georeferencing reference.
    Build with scripts/make_ref.sh (gdal_rasterize of TIGER 51013 roads)."""
    global _REF_STREETS
    if _REF_STREETS is None:
        img = cv2.imread(str(ROOT / "work" / "ref" / "ref_streets.tif"),
                         cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError("work/ref/ref_streets.tif missing — "
                               "see scripts/make_ref.sh")
        soft = cv2.GaussianBlur(img.astype(np.float32) / 255, (0, 0), 3.0)
        _REF_STREETS = soft / (soft.max() + 1e-6)
    return _REF_STREETS


def verify_warp(tmp_warp, label):
    """Measure the warped result's offset against the TIGER street-network
    reference on the county grid. This is the authoritative acceptance test.
    (Anchor-raster references failed: north-up sheets tuck notes/legend text
    inside the county bbox and furniture dominated the correlation.)"""
    ref = ref_streets()
    tst = county_grid_streets(tmp_warp)
    win = cv2.createHanningWindow((ref.shape[1], ref.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(ref, tst, win)
    dx_ft, dy_ft = dx * VERIFY_TR, dy * VERIFY_TR
    ok = resp >= VERIFY_MIN_RESP and abs(dx_ft) <= VERIFY_MAX_OFFSET_FT \
        and abs(dy_ft) <= VERIFY_MAX_OFFSET_FT
    print(f"  verify[{label}] vs TIGER: offset=({dx_ft:+.0f},{dy_ft:+.0f})ft "
          f"resp={resp:.3f} -> {'OK' if ok else 'REJECT'}", flush=True)
    return ok


def tiger_anchor():
    """(image, path) for matching directly against the TIGER street raster —
    a synthetic 'anchor' with only street signal, so furniture cannot lock,
    and no chained error. Blurred so NCC behaves like chamfer matching."""
    path = ROOT / "work" / "ref" / "ref_streets.tif"
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    soft = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 2.0)
    soft = np.clip(soft / (soft.max() + 1e-6) * 255, 0, 255).astype(np.uint8)
    return soft, path


def warp_and_verify(name, anchor, src_pts, dst_pts, rms, method,
                    full_shape, report):
    """GCPs -> TPS warp -> extent check -> correlation check vs anchor.
    Returns True and installs the output only if every check passes."""
    print(f"  warping via {anchor} ({method}, {len(src_pts)} points)",
          flush=True)
    if anchor == "tiger":
        gt = geotransform_of(ROOT / "work" / "ref" / "ref_streets.tif")
    else:
        gt = geotransform_of(GEOREF / f"{anchor}.tif")
    idx = spread_pick(src_pts, dst_pts, N_GCPS, full_shape)
    # Coverage gate: matches clustered in one small sheet region are the
    # signature of a false lock (inset map, legend block), and TPS on a
    # tight cluster extrapolates garbage across the rest of the sheet.
    min_cov = MIN_GCP_COVERAGE_SIFT if method == "sift" else MIN_GCP_COVERAGE_CORR
    if len(idx) < min_cov:
        print(f"  REJECT coverage: matches span only {len(idx)} grid cells "
              f"(need {min_cov})", flush=True)
        return False
    gcps = []
    for i in idx:
        sx, sy = src_pts[i]                   # full-res source pixel
        dx, dy = dst_pts[i]                   # full-res anchor pixel
        gx, gy = px_to_geo(gt, dx, dy)
        gcps += ["-gcp", f"{sx:.2f}", f"{sy:.2f}", f"{gx:.3f}", f"{gy:.3f}"]

    tmp_gcp = GEOREF / f"{name}_gcp.tif"
    tmp_warp = GEOREF / f"{name}_warp.tif"
    run(["gdal_translate", "-q", "-of", "GTiff", "-a_srs", "EPSG:2283",
         *gcps, RGB / f"{name}.tif", tmp_gcp], quiet=True)
    run(["gdalwarp", "-q", "-tps", "-t_srs", "EPSG:2283", "-r", "bilinear",
         "-dstalpha", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
         "-co", "BIGTIFF=IF_SAFER", tmp_gcp, tmp_warp], quiet=True)
    tmp_gcp.unlink()

    # extent invariant: every GLUP sheet contains the whole county
    info = json.loads(subprocess.run(
        ["gdalinfo", "-json", str(tmp_warp)], capture_output=True, text=True,
        check=True).stdout)
    cc = info["cornerCoordinates"]
    (ulx, uly), (lrx, lry) = cc["upperLeft"], cc["lowerRight"]
    x0, y0, x1, y1 = COUNTY_BBOX
    tol = 3000  # ft
    if not (ulx - tol <= x0 and lrx + tol >= x1 and
            lry - tol <= y0 and uly + tol >= y1):
        print(f"  REJECT extent: raster ({ulx:.0f},{lry:.0f})-"
              f"({lrx:.0f},{uly:.0f}) does not contain county", flush=True)
        tmp_warp.unlink()
        return False

    if not verify_warp(tmp_warp, anchor):
        tmp_warp.unlink()
        return False

    tmp_warp.rename(GEOREF / f"{name}.tif")
    report.append((name, f"{anchor}({method})", len(src_pts), rms))
    make_qa(name, anchor if anchor != "tiger" else "2024-front")
    return True


def georef_one(name, anchors, report):
    out = GEOREF / f"{name}.tif"
    if out.exists():
        print(f"SKIP {name} (exists)", flush=True)
        return True
    src_img, s_scale = load_gray(RGB / f"{name}.tif")
    full_shape = (round(src_img.shape[0] / s_scale),
                  round(src_img.shape[1] / s_scale))
    live = [c for c in anchors if (GEOREF / f"{c}.tif").exists()]
    for c in set(anchors) - set(live):
        print(f"  anchor {c} missing, skipping candidate", flush=True)

    # Pass 1: SIFT candidates (best-first), each verified after warping.
    # The anchor is masked to the county bbox: editions share sheet layouts
    # (title/legend/inset positions), and furniture-to-furniture matches can
    # form a self-consistent — but geographically wrong — consensus.
    sift_cands = []
    for cand in live:
        print(f"=== {name} vs anchor {cand} [sift]", flush=True)
        dst_img, d_scale = load_gray(GEOREF / f"{cand}.tif")
        mask = county_mask(GEOREF / f"{cand}.tif",
                           (round(dst_img.shape[0] / d_scale),
                            round(dst_img.shape[1] / d_scale)))
        mask = cv2.resize(mask, (dst_img.shape[1], dst_img.shape[0]),
                          interpolation=cv2.INTER_NEAREST)
        dst_img = cv2.bitwise_and(dst_img, dst_img, mask=mask)
        src_in, dst_in, rms = match_pair(src_img, dst_img)
        n = 0 if src_in is None else len(src_in)
        if n < MIN_INLIERS:
            continue
        sp, dp = src_in / s_scale, dst_in / d_scale
        if not center_gate(sp, dp, geotransform_of(GEOREF / f"{cand}.tif"),
                           full_shape):
            print("  rejected by center gate", flush=True)
            continue
        sift_cands.append((n, cand, sp, dp, rms))
    for n, cand, sp, dp, rms in sorted(sift_cands, reverse=True,
                                       key=lambda c: c[0]):
        if warp_and_verify(name, cand, sp, dp, rms, "sift",
                           full_shape, report):
            return True

    # Pass 2: match directly against the TIGER street raster. Style-free
    # and furniture-free — nothing on it but real streets, and its
    # geotransform is ground truth (no chained error). Coarse candidates
    # come from street-grid orientation + sheet-width template matching.
    src_full = cv2.imread(str(RGB / f"{name}.tif"), cv2.IMREAD_GRAYSCALE)
    tiger_img, tiger_path = tiger_anchor()
    tiger_gt = geotransform_of(tiger_path)
    print(f"=== {name} vs TIGER street raster [tiger]", flush=True)
    tiger_soft = tiger_img.astype(np.float32) / 255.0
    for M, score in tiger_coarse(src_full, tiger_soft)[:6]:
        src_pts, dst_pts = fine_match(src_full, tiger_img, M)
        if src_pts is None or len(src_pts) < CORR_MIN_POINTS:
            continue
        if not center_gate(src_pts, dst_pts, tiger_gt, full_shape):
            continue
        if warp_and_verify(name, "tiger", src_pts, dst_pts, -1, "tiger",
                           full_shape, report):
            return True

    # Pass 3: correlation vs chained anchors, for editions whose road
    # network has drifted too far from present-day TIGER.
    for cand in live:
        print(f"=== {name} vs anchor {cand} [corr]", flush=True)
        cand_tif = GEOREF / f"{cand}.tif"
        dst_full = cv2.imread(str(cand_tif), cv2.IMREAD_GRAYSCALE)
        gate = lambda sp, dp: center_gate(
            sp, dp, geotransform_of(cand_tif), full_shape)
        src_pts, dst_pts, resp = corr_match(
            src_full, dst_full, validate=gate, min_points=CORR_MIN_POINTS)
        if src_pts is None or len(src_pts) < CORR_MIN_POINTS:
            continue
        if warp_and_verify(name, cand, src_pts, dst_pts, -1, "corr",
                           full_shape, report):
            return True

    print(f"  FAILED: no candidate survived verification", flush=True)
    report.append((name, "|".join(anchors), 0, -1))
    return False


def make_qa(name, anchor):
    """Blend warped result over its anchor at matched extents for eyeballing."""
    QA.mkdir(exist_ok=True)
    small = {}
    for label, path in (("src", GEOREF / f"{name}.tif"),
                        ("dst", GEOREF / f"{anchor}.tif")):
        info = json.loads(subprocess.run(
            ["gdalinfo", "-json", str(path)], capture_output=True, text=True,
            check=True).stdout)
        small[label + "_cc"] = info["cornerCoordinates"]
        png = QA / f"_{label}.png"
        run(["gdal_translate", "-q", "-of", "PNG", "-outsize", "1600", "0",
             path, png], quiet=True)
        small[label] = png

    # warp src png onto dst extent via geo coords
    s_cc, d_cc = small["src_cc"], small["dst_cc"]
    src = cv2.imread(str(small["src"]), cv2.IMREAD_UNCHANGED)
    dst = cv2.imread(str(small["dst"]), cv2.IMREAD_UNCHANGED)
    dh, dw = dst.shape[:2]

    def geo_to_dstpx(gx, gy):
        x = (gx - d_cc["upperLeft"][0]) / (d_cc["lowerRight"][0] - d_cc["upperLeft"][0]) * dw
        y = (gy - d_cc["upperLeft"][1]) / (d_cc["lowerRight"][1] - d_cc["upperLeft"][1]) * dh
        return x, y

    sh, sw = src.shape[:2]
    corners_geo = [s_cc["upperLeft"], [s_cc["lowerRight"][0], s_cc["upperLeft"][1]],
                   s_cc["lowerRight"], [s_cc["upperLeft"][0], s_cc["lowerRight"][1]]]
    dst_pts = np.float32([geo_to_dstpx(*c) for c in corners_geo])
    src_pts = np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]])
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(src, M, (dw, dh))

    if warped.shape[2] == 4:
        alpha = (warped[:, :, 3:4].astype(np.float32)) / 255 * 0.5
        base = dst[:, :, :3].astype(np.float32)
        blend = base * (1 - alpha) + warped[:, :, :3].astype(np.float32) * alpha
    else:
        blend = dst[:, :, :3] * 0.5 + warped[:, :, :3] * 0.5
    cv2.imwrite(str(QA / f"{name}_vs_{anchor}.jpg"), blend.astype(np.uint8),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    small["src"].unlink()
    small["dst"].unlink()


def main():
    QA.mkdir(parents=True, exist_ok=True)
    # anchor grid caches may refer to re-derived rasters — always rebuild
    for stale in GEOREF.glob("_grid_*.tif"):
        stale.unlink()
    only = sys.argv[1:]
    report = []
    for name, anchors in CHAIN:
        if only and name not in only:
            continue
        try:
            georef_one(name, anchors, report)
        except Exception as e:
            print(f"!! {name}: {e}", file=sys.stderr)
            report.append((name, "|".join(anchors), -1, -1))
    with open(QA / "report.tsv", "a") as f:
        for r in report:
            f.write("\t".join(str(x) for x in r) + "\n")
    print("\nname\tanchor\tinliers\trms_px")
    for r in report:
        print("\t".join(str(x) for x in r))


if __name__ == "__main__":
    main()

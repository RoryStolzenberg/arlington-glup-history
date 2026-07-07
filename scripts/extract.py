#!/usr/bin/env python3
"""Extract working rasters from GLUP source files.

Outputs:
  work/rgb/{year}-{side}.tif     — plain high-res RGB render of every edition
  work/georef/{year}-{side}.tif  — GeoTIFF (EPSG:2283) for editions whose PDF
                                   carries embedded georeferencing (GeoPDF)

GeoPDFs are rendered through GDAL so the embedded geotransform scales with
render DPI. Non-georeferenced PDFs are rendered with pdftoppm (page 1 = the
map side). JPGs are converted to TIFF as-is.
"""
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
RGB = ROOT / "work" / "rgb"
GEOREF = ROOT / "work" / "georef"
DPI = 300


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def is_geopdf(path: Path) -> bool:
    out = subprocess.run(
        ["gdalinfo", str(path)], capture_output=True, text=True
    ).stdout
    if "SUBDATASET_1_NAME" in out:
        out = subprocess.run(
            ["gdalinfo", f"PDF:1:{path}"], capture_output=True, text=True
        ).stdout
    return "NEATLINE" in out and ("Origin = " in out or "GeoTransform" in out)


def n_pages(path: Path) -> int:
    out = subprocess.run(
        ["gdalinfo", str(path)], capture_output=True, text=True
    ).stdout
    n = out.count("_NAME=PDF:")
    return max(n, 1)


def extract_geopdf(src: Path, name: str):
    """Render GeoPDF -> georeferenced GeoTIFF + plain RGB copy."""
    geo_out = GEOREF / f"{name}.tif"
    rgb_out = RGB / f"{name}.tif"
    if geo_out.exists() and rgb_out.exists():
        print(f"SKIP {name} (exists)")
        return
    dataset = f"PDF:1:{src}" if n_pages(src) > 1 else str(src)
    run([
        "gdal_translate", "-q", "--config", "GDAL_PDF_DPI", str(DPI),
        "-of", "GTiff", "-b", "1", "-b", "2", "-b", "3",
        "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-co", "BIGTIFF=IF_SAFER",
        dataset, geo_out,
    ])
    # plain copy for feature matching (same pixels, no CRS needed)
    if not rgb_out.exists():
        rgb_out.symlink_to(Path("..") / "georef" / f"{name}.tif")


def extract_plain_pdf(src: Path, name: str):
    rgb_out = RGB / f"{name}.tif"
    if rgb_out.exists():
        print(f"SKIP {name} (exists)")
        return
    tmp = RGB / f"{name}_pp"
    run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(DPI), "-tiff",
         "-tiffcompression", "deflate", str(src), str(tmp)])
    produced = sorted(RGB.glob(f"{name}_pp*.tif"))
    if not produced:
        raise RuntimeError(f"pdftoppm produced nothing for {src}")
    produced[0].rename(rgb_out)


def extract_jpg(src: Path, name: str):
    rgb_out = RGB / f"{name}.tif"
    if rgb_out.exists():
        print(f"SKIP {name} (exists)")
        return
    run(["gdal_translate", "-q", "-of", "GTiff",
         "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", str(src), rgb_out])


def main():
    RGB.mkdir(parents=True, exist_ok=True)
    GEOREF.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]  # optional: names like "2024-front"

    with open(SOURCES / "manifest.tsv") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    for row in rows:
        year, side = row["year"], row["side"]
        name = f"{year}-{side}"
        if only and name not in only:
            continue
        ext = row["url"].rsplit(".", 1)[-1].lower()
        src = SOURCES / f"{name}.{ext}"
        if not src.exists():
            print(f"MISSING {src}", file=sys.stderr)
            continue
        if ext == "jpg":
            extract_jpg(src, name)
        elif is_geopdf(src):
            print(f"{name}: GeoPDF")
            extract_geopdf(src, name)
        else:
            print(f"{name}: plain PDF")
            extract_plain_pdf(src, name)


if __name__ == "__main__":
    main()

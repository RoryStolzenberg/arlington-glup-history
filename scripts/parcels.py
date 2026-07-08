#!/usr/bin/env python3
"""Download Arlington REA property (parcel) polygons and rasterize them onto
the classification grid.

Outputs:
  work/ref/parcels.gpkg        — polygons, EPSG:2283, keyed by RPCMSTR
  work/ref/parcel_ids.tif      — uint32 raster of parcel index (1-based;
                                 0 = no parcel / ROW) on the CLASSIFY grid
  work/ref/parcel_index.json   — index -> RPCMSTR
"""
import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "work" / "ref"
SVC = ("https://arlgis.arlingtonva.us/arcgis/rest/services/Open_Data/"
       "od_REA_Property_Polygons/FeatureServer/0/query")
# classification grid: county bbox at 8 ft/px (finer than the 16 ft verify
# grid so parcel supermajorities have enough pixels on small lots)
BBOX = (11859230, 6984963, 11902486, 7028535)
TR = 8


def fetch_page(offset):
    q = (f"?where=1%3D1&outFields=RPCMSTR&outSR=4326&f=geojson"
         f"&resultOffset={offset}&resultRecordCount=2000")
    req = urllib.request.Request(SVC + q, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    REF.mkdir(parents=True, exist_ok=True)
    raw = REF / "parcels_4326.geojson"
    if not raw.exists():
        feats = []
        offset = 0
        while True:
            page = fetch_page(offset)
            got = page.get("features", [])
            feats.extend(got)
            print(f"  {len(feats)} features", flush=True)
            if len(got) < 2000:
                break
            offset += 2000
        raw.write_text(json.dumps(
            {"type": "FeatureCollection", "features": feats}))
    gpkg = REF / "parcels.gpkg"
    if not gpkg.exists():
        subprocess.run(["ogr2ogr", "-f", "GPKG", "-t_srs", "EPSG:2283",
                        str(gpkg), str(raw), "-nln", "parcels"], check=True)

    # sequential index (fid) -> RPCMSTR mapping, burn fid into raster
    out = subprocess.run(
        ["ogrinfo", "-al", "-geom=NO", str(gpkg), "parcels"],
        capture_output=True, text=True, check=True).stdout
    idx = {}
    fid = None
    for line in out.splitlines():
        if line.startswith("OBJECTID") or not line.strip():
            continue
        if line.startswith("  RPCMSTR"):
            idx[fid] = line.split("=", 1)[1].strip()
        elif line.startswith("OGRFeature"):
            fid = int(line.rsplit(":", 1)[1])
    (REF / "parcel_index.json").write_text(json.dumps(idx))
    print(f"{len(idx)} parcels indexed")

    tif = REF / "parcel_ids.tif"
    if not tif.exists():
        subprocess.run(
            ["gdal_rasterize", "-q", "-a", "fid_burn",
             "-te", *[str(v) for v in BBOX], "-tr", str(TR), str(TR),
             "-ot", "UInt32", "-co", "COMPRESS=DEFLATE",
             "-sql", "SELECT fid AS fid_burn, geom FROM parcels",
             "-dialect", "sqlite",
             str(gpkg), str(tif)], check=True)
    print("rasterized:", tif)


if __name__ == "__main__":
    main()

#!/bin/bash
# Build work/ref/ref_streets.tif — TIGER street centerlines rasterized onto
# the verification grid (county bbox, EPSG:2283, 16 ft/px). This is the
# absolute georeferencing reference every edition is verified against.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p work/ref
cd work/ref

if [ ! -f tl_2023_51013_roads.shp ]; then
  curl -s -O https://www2.census.gov/geo/tiger/TIGER2023/ROADS/tl_2023_51013_roads.zip
  unzip -o -q tl_2023_51013_roads.zip
fi
ogr2ogr -overwrite -t_srs EPSG:2283 roads2283.shp tl_2023_51013_roads.shp
gdal_rasterize -q -burn 255 -te 11859230 6984963 11902486 7028535 \
  -tr 16 16 -ot Byte roads2283.shp ref_streets.tif
echo "wrote work/ref/ref_streets.tif"

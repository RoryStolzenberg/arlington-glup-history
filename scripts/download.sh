#!/bin/bash
# Download all GLUP map editions listed in sources/manifest.tsv.
# arlingtonva.us sits behind Akamai and 403s non-browser requests,
# so send full browser-like headers. Skips files already present.
set -u
cd "$(dirname "$0")/../sources"

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REF="https://www.arlingtonva.us/Government/Projects/Plans-Studies/General-Land-Use-Plan/Maps"

tail -n +2 manifest.tsv | while IFS=$'\t' read -r year side url; do
  ext="${url##*.}"
  out="${year}-${side}.${ext}"
  if [ -s "$out" ]; then
    echo "SKIP $out"
    continue
  fi
  curl -sL -o "$out" \
    -H "User-Agent: $UA" \
    -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" \
    -H "Accept-Language: en-US,en;q=0.5" \
    -H "Referer: $REF" \
    -H "Sec-Fetch-Dest: document" -H "Sec-Fetch-Mode: navigate" -H "Sec-Fetch-Site: same-origin" \
    --compressed "$url"
  size=$(stat -c%s "$out" 2>/dev/null || echo 0)
  if [ "$size" -lt 10000 ]; then
    echo "FAIL $out ($size bytes)"
    rm -f "$out"
  else
    echo "OK   $out ($size bytes)"
  fi
  sleep 2
done

#!/bin/sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
out=${1:?usage: pack.sh out-dir catalog.json}
mkdir -p "$out/app/contract"
cp "$here/function_app.py" "$here/host.json" "$here/requirements.txt" "$out/app/"
cp -R "$here/pulse_software" "$root/products/computers/api/pulse_computers" "$root/core/pulse_core" "$out/app/"
cp "$root/core/contract/"*.json "$out/app/contract/"
cp "${2:?catalog.json required}" "$out/app/catalog.json"
find "$out/app" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f "$out/function.zip"
(cd "$out/app" && zip -qr ../function.zip .)

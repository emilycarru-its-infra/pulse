#!/bin/sh
# Assemble the Functions package: function_app.py and its settings, the pulse_computers and
# pulse_core packages and the event contract, in one folder and a zip of it. A deploying
# pipeline adds the site's catalog.json (and a CA bundle file, if it uses one) to the folder
# or passes them here, then deploys the zip with a remote build, which installs requirements.txt.
#
#   ./pack.sh <out-dir> [catalog.json ca.pem ...]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
out=${1:?usage: pack.sh <out-dir> [extra files...]}
shift
rm -rf "$out/app" "$out/function.zip"
mkdir -p "$out/app/contract"
cp "$here/function_app.py" "$here/host.json" "$here/requirements.txt" "$out/app/"
cp -R "$here/pulse_computers" "$root/core/pulse_core" "$out/app/"
cp "$root/core/contract/"*.json "$out/app/contract/"
for f in "$@"; do cp "$f" "$out/app/"; done
find "$out/app" -name __pycache__ -type d -prune -exec rm -rf {} +
(cd "$out/app" && zip -qr ../function.zip .)
echo "$out/function.zip"

#!/bin/sh
# Assemble the Functions package: function_app.py and its settings and the pulse_servers
# package, in one folder and a zip of it. A deploying pipeline passes the site's catalog.json,
# then deploys the zip with a remote build, which installs requirements.txt.
#
#   ./pack.sh <out-dir> [catalog.json ...]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:?usage: pack.sh <out-dir> [extra files...]}
shift
rm -rf "$out/app" "$out/function.zip"
mkdir -p "$out/app"
cp "$here/function_app.py" "$here/host.json" "$here/requirements.txt" "$out/app/"
cp -R "$here/pulse_servers" "$out/app/"
for f in "$@"; do cp "$f" "$out/app/"; done
find "$out/app" -name __pycache__ -type d -prune -exec rm -rf {} +
(cd "$out/app" && zip -qr ../function.zip .)
echo "$out/function.zip"

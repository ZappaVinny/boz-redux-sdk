#!/usr/bin/env bash
# Packages an SDK release: the source with the gamedef submodule, the prebuilt editor
# (build/suite, from tools/build_suite.py) and the navmesh helpers for Linux and Windows
# (tools/navmesh/build/boz-navmesh and boz-navmesh.exe). Build those first.
# Usage: tools/package_release.sh VERSION   -> build/release/BOZ-Redux-SDK-VERSION.zip
set -euo pipefail
version="${1:?usage: package_release.sh VERSION}"
here="$(cd "$(dirname "$0")/.." && pwd)"
name="BOZ-Redux-SDK-$version"
out="$here/build/release"
stage="$out/$name"
for needed in tools/navmesh/build/boz-navmesh tools/navmesh/build/boz-navmesh.exe \
              build/suite/scripts/startup/bl_app_templates_user/boz_suite/startup.blend; do
  [ -f "$here/$needed" ] || { echo "missing $needed: build it first" >&2; exit 1; }
done
rm -rf "$stage" "$out/$name.zip"
mkdir -p "$stage"
git -C "$here" archive HEAD | tar -x -C "$stage"
git -C "$here/gamedef" archive HEAD | tar -x -C "$stage/gamedef"
mkdir -p "$stage/tools/navmesh/build"
cp "$here/tools/navmesh/build/boz-navmesh" "$here/tools/navmesh/build/boz-navmesh.exe" \
   "$stage/tools/navmesh/build/"
mkdir -p "$stage/build"
cp -a "$here/build/suite" "$stage/build/suite"
python3 -c 'import shutil, sys; shutil.make_archive(sys.argv[1], "zip", sys.argv[2], sys.argv[3])' \
  "$out/$name" "$out" "$name"
echo "$out/$name.zip"

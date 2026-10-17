#!/usr/bin/env bash
# Fetch the MEP acceptance fixture. Deliberately NOT committed: 47 MB, and it
# is a public model, so provenance belongs in FIXTURES.md and the bytes belong
# in a download.
#
# The source is the ARCHIVED repo. Both the order and the live
# openBIMstandards/DataSetSchependomlaan repo point at paths that 404 — the
# live repo is now a README forwarding to a location that no longer exists.
set -euo pipefail
cd "$(dirname "$0")"

BASE="https://raw.githubusercontent.com/openBIMstandards/Archive-DataSetSchependomlaan/master"
curl -fL -o schependomlaan_design.ifc "$BASE/Design%20model%20IFC/IFC%20Schependomlaan.ifc"

echo "downloaded: $(du -h schependomlaan_design.ifc | cut -f1)"
echo "expected: IFC2X3, 73 MEP elements, 2954 structural, 6 storeys"
echo "see FIXTURES.md for why the companion utilities model is NOT used"

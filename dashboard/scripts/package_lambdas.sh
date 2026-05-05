#!/usr/bin/env bash
# Package the ingest Lambda + GeoLite2 layer into .zip files for Terraform.
#
# Output:
#   infrastructure/terraform/modules/ingest/build/ingest.zip
#   infrastructure/terraform/modules/ingest/build/geolite2-layer.zip   (if .mmdb files exist)
#
# Usage:
#   cd dashboard
#   ./scripts/package_lambdas.sh
#
# Requirements:
#   - Any Python with pip (cross-target wheels via --platform / --python-version)
#   - PYTHON_BIN env var defaults to `python3.13` if available, otherwise tries
#     `python3` then `python` then a local .venv. Override explicitly to use
#     a specific interpreter:  PYTHON_BIN=.venv/Scripts/python.exe ./scripts/package_lambdas.sh
#
# Cross-target wheel download: pip is invoked with
#   --platform manylinux2014_x86_64 --implementation cp --python-version 3.13
#   --only-binary=:all:
# so the resulting wheels match the Lambda runtime exactly regardless of which
# Python runs this script. python3.13 is NOT required locally to build the zip.

set -euo pipefail

DASHBOARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${DASHBOARD_DIR}/infrastructure/terraform/modules/ingest/build"
INGEST_STAGE="${BUILD_DIR}/ingest-stage"
LAYER_STAGE="${BUILD_DIR}/geolite2-stage"

# Pick a working Python interpreter
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :  # honour the override
elif command -v python3.13 > /dev/null 2>&1; then
  PYTHON_BIN="python3.13"
elif [[ -x "${DASHBOARD_DIR}/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="${DASHBOARD_DIR}/.venv/Scripts/python.exe"
elif [[ -x "${DASHBOARD_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${DASHBOARD_DIR}/.venv/bin/python"
elif command -v python3 > /dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python > /dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: no Python interpreter found." >&2
  exit 1
fi

echo "Using PYTHON_BIN=${PYTHON_BIN}"
"${PYTHON_BIN}" --version

mkdir -p "${BUILD_DIR}"
rm -rf "${INGEST_STAGE}" "${LAYER_STAGE}"
mkdir -p "${INGEST_STAGE}/functions" "${LAYER_STAGE}/geolite2"

###############################################################################
# Ingest Lambda package
###############################################################################

# Vendor first-party code preserving the package layout
touch "${INGEST_STAGE}/functions/__init__.py"
cp -r "${DASHBOARD_DIR}/functions/ingest" "${INGEST_STAGE}/functions/"
cp -r "${DASHBOARD_DIR}/functions/shared" "${INGEST_STAGE}/functions/"

# Vendor third-party deps targeting the Lambda runtime (cp313, manylinux2014_x86_64)
"${PYTHON_BIN}" -m pip install \
  --quiet \
  --target "${INGEST_STAGE}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  pydantic boto3 geoip2

# Strip caches and tests to reduce size
find "${INGEST_STAGE}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "${INGEST_STAGE}" -type d -name "tests" -prune -exec rm -rf {} + 2>/dev/null || true
find "${INGEST_STAGE}" -type f -name "*.pyc" -delete 2>/dev/null || true

# Use Python's zipfile to produce the archive (portable across Windows / Linux)
"${PYTHON_BIN}" - <<PY
import os, zipfile
stage = r"${INGEST_STAGE}"
out = r"${BUILD_DIR}/ingest.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for root, _, files in os.walk(stage):
        for fn in files:
            abs_path = os.path.join(root, fn)
            rel = os.path.relpath(abs_path, stage).replace(os.sep, "/")
            zf.write(abs_path, rel)
print(f"Built: {out} ({os.path.getsize(out)} bytes)")
PY

###############################################################################
# GeoLite2 layer package (optional — skipped if .mmdb files absent)
###############################################################################

GEOIP_DIR="${DASHBOARD_DIR}/functions/layers/geolite2"
if [[ -f "${GEOIP_DIR}/GeoLite2-Country.mmdb" && -f "${GEOIP_DIR}/GeoLite2-ASN.mmdb" ]]; then
  cp "${GEOIP_DIR}/GeoLite2-Country.mmdb" "${LAYER_STAGE}/geolite2/"
  cp "${GEOIP_DIR}/GeoLite2-ASN.mmdb"     "${LAYER_STAGE}/geolite2/"
  "${PYTHON_BIN}" - <<PY
import os, zipfile
stage = r"${LAYER_STAGE}"
out = r"${BUILD_DIR}/geolite2-layer.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for root, _, files in os.walk(stage):
        for fn in files:
            abs_path = os.path.join(root, fn)
            rel = os.path.relpath(abs_path, stage).replace(os.sep, "/")
            zf.write(abs_path, rel)
print(f"Built: {out} ({os.path.getsize(out)} bytes)")
PY
else
  echo "Skipping GeoLite2 layer: .mmdb files not present."
  echo "  Run MAXMIND_LICENSE_KEY=xxx ${GEOIP_DIR}/download_geolite2.sh first."
fi

# Clean staging dirs (keep the .zip outputs)
rm -rf "${INGEST_STAGE}" "${LAYER_STAGE}"

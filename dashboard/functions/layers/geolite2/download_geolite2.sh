#!/usr/bin/env bash
# Download MaxMind GeoLite2 Country + ASN databases for bundling into the
# ingest Lambda's layer.
#
# License (CC BY-SA 4.0) requires attribution; the dashboard footer credits
# MaxMind. Redistribution permitted; we deliberately do NOT commit the .mmdb
# files to git so each deploy fetches a current copy.
#
# Requires:
#   MAXMIND_LICENSE_KEY  — issued from https://www.maxmind.com/en/accounts/<id>/license-key
#                          (free GeoLite2 account; renew annually)
#
# Usage:
#   MAXMIND_LICENSE_KEY=xxxx ./download_geolite2.sh
#
# Phase 9 will replace this manual fetch with a scheduled Lambda that
# refreshes the layer weekly and republishes a new layer version.

set -euo pipefail

DEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${MAXMIND_LICENSE_KEY:-}" ]]; then
  echo "MAXMIND_LICENSE_KEY env var is required" >&2
  echo "Get one at https://www.maxmind.com/en/accounts/<your-id>/license-key" >&2
  exit 1
fi

download_db() {
  local edition="$1"   # GeoLite2-Country | GeoLite2-ASN
  local outfile="$2"   # GeoLite2-Country.mmdb | GeoLite2-ASN.mmdb

  local url="https://download.maxmind.com/app/geoip_download?edition_id=${edition}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz"
  local tmp_tgz tmp_dir
  tmp_tgz="$(mktemp --suffix=.tar.gz)"
  tmp_dir="$(mktemp -d)"

  echo "Downloading ${edition}..."
  curl -sSL -o "${tmp_tgz}" "${url}"

  tar -xzf "${tmp_tgz}" -C "${tmp_dir}"
  local found
  found="$(find "${tmp_dir}" -name "${edition}.mmdb" | head -1)"

  if [[ -z "${found}" ]]; then
    echo "ERROR: did not find ${edition}.mmdb in download" >&2
    exit 2
  fi

  cp "${found}" "${DEST_DIR}/${outfile}"
  rm -rf "${tmp_tgz}" "${tmp_dir}"
  echo "  -> ${DEST_DIR}/${outfile}"
}

download_db "GeoLite2-Country" "GeoLite2-Country.mmdb"
download_db "GeoLite2-ASN" "GeoLite2-ASN.mmdb"

echo "GeoLite2 databases downloaded successfully."
echo "Layer build will pick them up from: ${DEST_DIR}"

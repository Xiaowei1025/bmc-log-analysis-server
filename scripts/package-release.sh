#!/usr/bin/env bash
set -euo pipefail

# Creates a source-only release. Production data, uploads and secrets stay on the server.
project_root="$(cd "$(dirname "$0")/.." && pwd)"
version_file="$project_root/VERSION"
release_version="${1:-$(tr -d '[:space:]' < "$version_file")}"
if [[ -z "$release_version" ]]; then
  echo "Release version is empty. Set VERSION or pass a version argument." >&2
  exit 1
fi
output_dir="$project_root/releases"
archive="$output_dir/bmc-hub-${release_version}.tar.gz"

mkdir -p "$output_dir"
tar -C "$project_root" \
  --exclude='.venv*' --exclude='.env' --exclude='data/*' --exclude='uploads/*' --exclude='examples/*' \
  --exclude='releases' --exclude='__pycache__' --exclude='*.pyc' \
  -czf "$archive" .
printf 'Created %s\n' "$archive"

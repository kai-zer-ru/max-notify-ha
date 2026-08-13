#!/usr/bin/env bash
# Run official hassfest against a clean tree (no local .venv*).
# Needed under nektos/act: nested docker remounts the host workspace, which
# often contains Home Assistant installs inside .venv* and produces thousands
# of false MANIFEST errors for core integrations.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STAGE="${GITHUB_WORKSPACE:-$ROOT}/.artifacts/hassfest-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"

if ! command -v rsync >/dev/null 2>&1; then
	echo "run-hassfest: rsync is required" >&2
	exit 1
fi

rsync -a \
	--exclude='.git/' \
	--exclude='.venv/' \
	--exclude='.venv-*/' \
	--exclude='.idea/' \
	--exclude='.artifacts/' \
	--exclude='.pytest_cache/' \
	--exclude='__pycache__/' \
	--exclude='*.pyc' \
	--exclude='*.pyo' \
	./ "$STAGE"/

docker run --rm -v "$STAGE:/github/workspace" ghcr.io/home-assistant/hassfest

#!/usr/bin/env bash
# Prints release git tag (vX.Y.Z) for CHANGELOG extraction.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${ROOT}/custom_components/max_notify/manifest.json"

semver_tag_re='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'

ref="${1:-${GITHUB_REF_NAME:-}}"

if [[ "$ref" =~ $semver_tag_re ]]; then
	printf '%s\n' "$ref"
	exit 0
fi

exact="$(git -C "$ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)"
if [[ "$exact" =~ $semver_tag_re ]]; then
	printf '%s\n' "$exact"
	exit 0
fi

latest="$(git -C "$ROOT" describe --tags --abbrev=0 2>/dev/null || true)"
if [[ "$latest" =~ $semver_tag_re ]]; then
	printf '%s\n' "$latest"
	exit 0
fi

if [[ -f "$MANIFEST" ]]; then
	ver="$(python3 -c "import json; print(json.load(open('${MANIFEST}'))['version'])")"
	if [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
		printf 'v%s\n' "$ver"
		exit 0
	fi
fi

echo "resolve-release-tag: could not determine release tag (ref=${ref:-<empty>})" >&2
exit 1

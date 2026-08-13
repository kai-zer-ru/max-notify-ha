#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MANIFEST="custom_components/max_notify/manifest.json"

[[ -f "$MANIFEST" ]] || {
	echo "tag_release: missing ${MANIFEST}" >&2
	exit 1
}

ver="$(python3 -c "import json; print(json.load(open('${MANIFEST}'))['version'])")"
tag="v${ver}"

if ! [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
	echo "tag_release: invalid semver in manifest: ${ver}" >&2
	exit 1
fi

git rev-parse HEAD >/dev/null 2>&1 || {
	echo "tag_release: not a git repository" >&2
	exit 1
}

if [[ -n "$(git status --porcelain)" ]]; then
	echo "tag_release: working tree is not clean; commit or stash changes first" >&2
	exit 1
fi

if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
	echo "tag_release: tag ${tag} already exists" >&2
	exit 1
fi

echo "tag_release: checking CHANGELOG section for ${tag}..."
bash scripts/extract-release-notes.sh --stdout "${tag}" >/dev/null

echo "tag_release: git tag -a ${tag} -m \"${tag}\""
git tag -a "${tag}" -m "${tag}"

echo "tag_release: git push origin ${tag}"
git push origin "${tag}"

echo "tag_release: done — ${tag} (GitHub Actions создаст Release из CHANGELOG.md)"

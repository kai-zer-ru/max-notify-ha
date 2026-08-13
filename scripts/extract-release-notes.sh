#!/usr/bin/env bash
# Extract CHANGELOG.md section for a release tag.
# MaxNotify format: "# [vX.Y.Z] — YYYY-MM-DD" (H1), next release starts at next "# [".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHANGELOG="${ROOT}/CHANGELOG.md"
OUT="${ROOT}/.release-notes.md"

usage() {
	echo "Usage: scripts/extract-release-notes.sh [--stdout] [v1.0.0]" >&2
	echo "  Extract CHANGELOG section for a release tag." >&2
	exit 1
}

stdout=false
tag=""

while [[ $# -gt 0 ]]; do
	case "$1" in
	--stdout)
		stdout=true
		shift
		;;
	-h | --help) usage ;;
	*)
		tag="$1"
		shift
		;;
	esac
done

if [[ -z "$tag" ]]; then
	tag="${GITHUB_REF_NAME:-}"
fi

semver_tag_re='^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'
if [[ -z "$tag" ]] || [[ ! "$tag" =~ $semver_tag_re ]]; then
	tag="$(bash "${ROOT}/scripts/resolve-release-tag.sh" "${tag:-}")"
fi
[[ -n "$tag" ]] || {
	echo "extract-release-notes: no version tag" >&2
	exit 1
}

[[ -f "$CHANGELOG" ]] || {
	echo "extract-release-notes: missing CHANGELOG.md" >&2
	exit 1
}

extract_section() {
	local heading="$1"
	awk -v h="$heading" '
		BEGIN { found = 0 }
		$0 ~ "^# \\[" h "\\]" { found = 1; print; next }
		found && /^# \[/ { exit }
		found && /^\[[^]]+\]:[[:space:]]/ { next }
		found { print }
	' "$CHANGELOG"
}

ver="${tag#v}"
body=""
for candidate in "v${ver}" "${ver}"; do
	body="$(extract_section "$candidate")"
	if [[ -n "${body//[[:space:]]/}" ]]; then
		break
	fi
done

if [[ -z "${body//[[:space:]]/}" ]]; then
	echo "extract-release-notes: no section for ${tag} in CHANGELOG.md (expected # [${ver}] or # [v${ver}])" >&2
	exit 1
fi

# Trim trailing horizontal rules / blank lines often used as section separators.
body="$(printf '%s\n' "$body" | awk '
	{ lines[NR] = $0 }
	END {
		end = NR
		while (end > 0 && (lines[end] ~ /^[[:space:]]*$/ || lines[end] ~ /^---+[[:space:]]*$/)) end--
		for (i = 1; i <= end; i++) print lines[i]
	}
')"

if $stdout; then
	printf '%s\n' "$body"
else
	printf '%s\n' "$body" >"$OUT"
	echo "extract-release-notes: wrote ${OUT}"
fi

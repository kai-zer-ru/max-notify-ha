#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MANIFEST="custom_components/max_notify/manifest.json"

usage() {
	echo "Usage: make version vX.Y.Z" >&2
	echo "       scripts/set_version.sh vX.Y.Z" >&2
	exit 1
}

[[ $# -eq 1 ]] || usage

raw="$1"
ver="${raw#v}"

if ! [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
	echo "set_version: invalid semver: $raw (expected v1.2.3 or 1.2.3)" >&2
	exit 1
fi

[[ -f "$MANIFEST" ]] || {
	echo "set_version: missing ${MANIFEST}" >&2
	exit 1
}

python3 - "$ver" "$MANIFEST" <<'PY'
import json
import sys
from pathlib import Path

ver = sys.argv[1]
path = Path(sys.argv[2])
data = json.loads(path.read_text(encoding="utf-8"))
data["version"] = ver
# hassfest: domain, name, then alphabetical
ordered = {}
for key in ("domain", "name"):
    if key in data:
        ordered[key] = data[key]
for key in sorted(k for k in data if k not in ("domain", "name")):
    ordered[key] = data[key]
path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "set_version: ${ver}"
echo "  ${MANIFEST}"
echo "Не забудьте добавить секцию # [v${ver}] в CHANGELOG.md перед тегом."

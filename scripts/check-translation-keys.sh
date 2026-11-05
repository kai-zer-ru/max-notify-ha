#!/usr/bin/env bash
# Сверка наборов ключей: strings.json, translations/en.json, translations/ru.json.
# Как в AGENTS.md: jq -S '[paths(scalars)]'.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/custom_components/max_notify"

if ! command -v jq >/dev/null 2>&1; then
	echo "check-translation-keys: jq is required" >&2
	exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

keys() {
	jq -S '[paths(scalars)]' "$1"
}

keys "$DIR/strings.json" >"$tmp/strings"
keys "$DIR/translations/en.json" >"$tmp/en"
keys "$DIR/translations/ru.json" >"$tmp/ru"

fail=0
for other in en ru; do
	if ! diff -u "$tmp/strings" "$tmp/$other"; then
		echo "check-translation-keys: strings.json vs translations/${other}.json — наборы ключей различаются" >&2
		fail=1
	fi
done
if [[ "$fail" -ne 0 ]]; then
	exit 1
fi
echo "OK: ключи strings.json, en.json и ru.json совпадают."

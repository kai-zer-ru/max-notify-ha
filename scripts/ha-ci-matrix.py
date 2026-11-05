#!/usr/bin/env python3
"""Матрица pytest для CI: HA от MINIMUM_HA_VERSION до текущего стабильного на PyPI.

На каждый месяц Core — последний патч (2026.4.4, не все 2026.4.0…4.4).
Точная минимальная версия из hacs.json / const.py всегда в матрице.
Бета/rc не входят. Python берётся из requires_python пакета на PyPI.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPI_URL = "https://pypi.org/pypi/homeassistant/json"
STABLE = re.compile(r"^(\d{4})\.(\d+)\.(\d+)$")


def _parse(ver: str) -> tuple[int, int, int]:
    match = STABLE.fullmatch(ver)
    if not match:
        raise ValueError(ver)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _minimum() -> str:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    from_hacs = str(hacs["homeassistant"])
    const = (ROOT / "custom_components/max_notify/const.py").read_text(
        encoding="utf-8"
    )
    found = re.search(r'MINIMUM_HA_VERSION = "([^"]+)"', const)
    if not found:
        raise SystemExit("ha-ci-matrix: нет MINIMUM_HA_VERSION в const.py")
    from_const = found.group(1)
    if from_hacs != from_const:
        raise SystemExit(
            f"ha-ci-matrix: hacs.json ({from_hacs}) != const.py ({from_const})"
        )
    return from_hacs


def _python_for_requires(requires: str | None) -> str:
    """Минимальный CPython, который setup-python может поставить под requires_python."""
    if not requires:
        return "3.13"
    match = re.search(r">=\s*3\.(\d+)(?:\.(\d+))?", requires)
    if not match:
        return "3.13"
    minor = int(match.group(1))
    patch = int(match.group(2) or 0)
    if minor >= 14:
        return f"3.{minor}.{patch}" if patch else f"3.{minor}"
    return f"3.{minor}"


def _requires_python(files: list[dict]) -> str | None:
    for item in files:
        req = item.get("requires_python")
        if req:
            return str(req)
    return None


def build() -> list[dict[str, str]]:
    minimum = _minimum()
    min_key = _parse(minimum)
    with urllib.request.urlopen(PYPI_URL, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    releases: dict[str, list] = payload.get("releases") or {}

    by_month: dict[tuple[int, int], list[str]] = defaultdict(list)
    requires: dict[str, str | None] = {}
    for ver, files in releases.items():
        if not STABLE.fullmatch(ver):
            continue
        if _parse(ver) < min_key:
            continue
        if not files:
            continue
        by_month[_parse(ver)[:2]].append(ver)
        requires[ver] = _requires_python(files)

    if not by_month:
        raise SystemExit(
            f"ha-ci-matrix: на PyPI нет стабильных homeassistant >= {minimum}"
        )

    chosen: list[str] = []
    seen: set[str] = set()

    def add(ver: str) -> None:
        if ver not in seen:
            seen.add(ver)
            chosen.append(ver)

    add(minimum)
    for month in sorted(by_month):
        latest = max(by_month[month], key=_parse)
        add(latest)

    return [
        {
            "ha": ver,
            "python": _python_for_requires(requires.get(ver)),
        }
        for ver in chosen
    ]


def main() -> None:
    matrix = build()
    json.dump(matrix, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

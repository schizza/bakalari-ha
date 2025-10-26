#!/usr/bin/env python3

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "ha": [
        (ROOT / "Makefile", r"HA_VERSION\s*:=\s*([0-9][^\s#]+)"),
        (ROOT / "hacs.json", r"\"homeassistant\": \"([0-9][^\s#]+)\""),
        (
            ROOT / ".github/workflows/ci.yml",
            r"pip install homeassistant==([0-9][^\s#]+)",
        ),
    ],
    "bakalari": [
        (ROOT / "Makefile", r"BAKALARI_VERSION\s*:=\s*([0-9][^\s#]+)"),
        (ROOT / ".github/workflows/ci.yml", r"async-bakalari-api==([0-9][^\s#]+)"),
        (
            ROOT / "custom_components/bakalari/manifest.json",
            r'"async-bakalari-api==([0-9][^"]+)"',
        ),
        (ROOT / "README.md", r"async-bakalari-api==([0-9][^\s#]+)\`"),
    ],
    "library": [
        (ROOT / "custom_components/bakalari/manifest.json", r"\"version\":\s*\"([0-9][^\s#]+)\""),
        (ROOT / "pyproject.toml", r"version = \"([0-9][^\s#]+)\""),
    ],
}


def extract_versions(group: str) -> tuple[str, dict[Path, str], list[str]]:
    """Vrátí (expected, per_file, errors)."""
    versions: dict[Path, str] = {}
    errors: list[str] = []

    for path, pattern in FILES[group]:
        if not path.exists():
            # Nepovinné soubory přeskoč, jen informuj
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(pattern, text, flags=re.MULTILINE)
        if not m:
            errors.append(f"[{group}] Nenalezen vzor v: {path} (pattern: {pattern})")
        else:
            versions[path] = m.group(1)

    if not versions:
        errors.append(f"[{group}] Nenašel jsem verzi v žádném souboru.")
        expected = ""
    else:
        expected = next(iter(versions.values()))

    return expected, versions, errors


def main() -> int:
    overall_errors: list[str] = []

    for group in FILES:
        expected, versions, errors = extract_versions(group)
        overall_errors.extend(errors)
        for path, ver in versions.items():
            if ver != expected:
                overall_errors.append(
                    f"[{group}] Nesoulad: {path} má '{ver}', očekáváno '{expected}'"
                )

    if overall_errors:
        print("❌ Nesoulad verzí nalezen:\n")
        for e in overall_errors:
            print(" -", e)
        print("\nTip: změň verzi pomocí bump-my-version (make bump-… NEW=…).")
        return 1

    print("✅ Verze jsou konzistentní napříč soubory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

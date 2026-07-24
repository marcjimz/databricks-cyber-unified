#!/usr/bin/env python3
"""CI guard: validate the app-owned migration files.

Rules:
  * every file in app/migrations/versions/ matches ``NNNN__description.sql``;
  * version numbers are unique and strictly ascending with no gaps;
  * each file is non-empty.

Exits non-zero (failing the PR) on any violation. No DB connection needed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VERSIONS = Path("app/migrations/versions")
NAME_RE = re.compile(r"^(\d{4})__.+\.sql$")


def main() -> int:
    if not VERSIONS.is_dir():
        print(f"error: {VERSIONS} not found")
        return 1

    files = sorted(p for p in VERSIONS.iterdir() if p.suffix == ".sql")
    if not files:
        print(f"error: no migration files in {VERSIONS}")
        return 1

    versions: list[int] = []
    ok = True
    for p in files:
        m = NAME_RE.match(p.name)
        if not m:
            print(f"error: {p.name} does not match NNNN__description.sql")
            ok = False
            continue
        if not p.read_text().strip():
            print(f"error: {p.name} is empty")
            ok = False
        versions.append(int(m.group(1)))

    if len(set(versions)) != len(versions):
        print(f"error: duplicate version numbers: {versions}")
        ok = False

    expected = list(range(1, len(versions) + 1))
    if sorted(versions) != expected:
        print(f"error: versions must be contiguous 0001..N; got {sorted(versions)}")
        ok = False

    if ok:
        print(f"OK: {len(files)} migration file(s) valid ({', '.join(p.name for p in files)})")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

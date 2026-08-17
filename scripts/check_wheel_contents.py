#!/usr/bin/env python3
"""Assert that a built wheel contains only files tracked by git.

The marketplace tree is pulled into the wheel with hatchling's ``force-include``,
which reads the *working tree*, not the git index. Anything sitting untracked in
``plugins/`` -- a draft skill, a scratch file, a local experiment -- is therefore
silently published to anyone who installs the package. That has already happened
once during development.

Run this after building, before publishing.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

# Wheel paths under this prefix map back to repo paths, per the force-include
# mapping in pyproject.toml.
PREFIX = "pegasus_ai_knowledge/marketplace/"


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <wheel>", file=sys.stderr)
        return 2

    wheel = Path(argv[1])
    tracked = tracked_files()

    untracked: list[str] = []
    checked = 0
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if not name.startswith(PREFIX) or name.endswith("/"):
                continue
            checked += 1
            if name[len(PREFIX) :] not in tracked:
                untracked.append(name)

    if untracked:
        print(
            f"{wheel.name} contains {len(untracked)} file(s) not tracked by git:",
            file=sys.stderr,
        )
        for name in sorted(untracked):
            print(f"  {name}", file=sys.stderr)
        print(
            "\nRemove them from the working tree (or commit them) and rebuild.",
            file=sys.stderr,
        )
        return 1

    print(f"{wheel.name}: {checked} marketplace file(s), all tracked by git")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

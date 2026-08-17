"""Locate the packaged Pegasus AI marketplace tree.

This package ships the same marketplace directory that lives at the root of
pegasus-isi/claude-plugin-marketplace, so a host that cannot clone the repo at
runtime -- a container image, an Open OnDemand app, an HPC login node with no
egress -- can still get the skills, agents and reference material from a plain
``pip install``.

There is exactly one authored copy of that content, in this repo. Consumers
locate it through this module rather than vendoring it again.

Typical use::

    import pegasus_ai_knowledge as k

    k.plugin_dir()            # .../marketplace/plugins/pegasus-ai
    k.write_seed("/var/lib/pegasus-ai/seed")

and then point Claude Code at it::

    CLAUDE_CODE_PLUGIN_SEED_DIR=/var/lib/pegasus-ai/seed
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "marketplace_dir",
    "manifest_path",
    "marketplace_name",
    "plugin_dir",
    "list_plugins",
    "write_seed",
    "__version__",
]

__version__ = "0.0.0"

_HERE = Path(__file__).resolve().parent

DEFAULT_PLUGIN = "pegasus-ai"


def marketplace_dir() -> Path:
    """Return the packaged directory containing ``.claude-plugin/marketplace.json``.

    This is what Claude Code calls a marketplace of ``source: "directory"``. It is
    inside site-packages and must be treated as read-only.
    """
    return _HERE / "marketplace"


def manifest_path() -> Path:
    """Return the path to the packaged marketplace manifest."""
    return marketplace_dir() / ".claude-plugin" / "marketplace.json"


def _manifest() -> dict:
    with open(manifest_path()) as fh:
        return json.load(fh)


def marketplace_name() -> str:
    """Return the marketplace's declared name.

    Read from the manifest rather than hardcoded: Claude Code enforces that the
    key a marketplace is registered under matches this value, so registering it
    as anything else fails with a confusing "plugin not found in marketplace"
    error rather than a name mismatch.
    """
    return _manifest()["name"]


def list_plugins() -> list[str]:
    """Return the names of plugins declared in the manifest.

    Includes plugins sourced from elsewhere (e.g. GitHub), which are declared here
    but not shipped in this package and are therefore unavailable offline.
    """
    return [p["name"] for p in _manifest().get("plugins", [])]


def plugin_dir(name: str = DEFAULT_PLUGIN) -> Path:
    """Return the packaged directory for one plugin.

    Raises ``FileNotFoundError`` if the plugin is declared but not shipped in this
    package, which is the case for any plugin the manifest sources from GitHub.
    """
    path = marketplace_dir() / "plugins" / name
    if not path.is_dir():
        raise FileNotFoundError(
            f"plugin {name!r} is not shipped in this package "
            f"(declared plugins: {', '.join(list_plugins())})"
        )
    return path


def write_seed(dest: str | os.PathLike[str], *, copy: bool = False) -> Path:
    """Materialize a Claude Code plugin seed directory at ``dest``.

    Writes the layout Claude Code syncs at startup::

        <dest>/known_marketplaces.json
        <dest>/marketplaces/<name>   -> the packaged marketplace

    Point ``CLAUDE_CODE_PLUGIN_SEED_DIR`` at the returned path. Seeded
    marketplaces are read-only to the user and are skipped during refresh, so no
    network access is needed at any point.

    ``known_marketplaces.json`` is generated rather than shipped because
    ``installLocation`` must be an absolute path, which is only known once the
    package is installed. ``installLocation`` and ``lastUpdated`` are both
    mandatory: an entry carrying only ``source`` fails schema validation and is
    skipped with a warning that is invisible at normal verbosity.

    By default ``marketplaces/<name>`` is a symlink to the packaged tree, so
    there is still only one copy on disk. Pass ``copy=True`` where symlinks are
    unavailable or where the consumer must survive the package being upgraded
    underneath it.
    """
    dest_path = Path(dest).resolve()
    name = marketplace_name()
    source = marketplace_dir()

    markets = dest_path / "marketplaces"
    markets.mkdir(parents=True, exist_ok=True)

    target = markets / name
    if target.is_symlink() or target.exists():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    if copy:
        shutil.copytree(source, target)
    else:
        try:
            target.symlink_to(source, target_is_directory=True)
        except OSError:
            shutil.copytree(source, target)

    entry = {
        name: {
            "source": {"source": "directory", "path": str(source)},
            "installLocation": str(target),
            "lastUpdated": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }
    }
    with open(dest_path / "known_marketplaces.json", "w") as fh:
        json.dump(entry, fh, indent=2)
        fh.write("\n")

    return dest_path

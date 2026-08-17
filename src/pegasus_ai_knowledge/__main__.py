"""Command line entry point, for launcher scripts that are not Python.

A container entrypoint or an Open OnDemand ``before.sh`` needs the packaged paths
as shell variables, so expose them without making the launcher write inline
Python::

    export CLAUDE_CODE_PLUGIN_SEED_DIR="$(pegasus-ai-knowledge seed "$STATE/seed")"
    export KNOWLEDGE_ROOT="$(pegasus-ai-knowledge path)"
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, list_plugins, marketplace_dir, plugin_dir, write_seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pegasus-ai-knowledge",
        description="Locate the packaged Pegasus AI marketplace tree.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser(
        "seed",
        help="write a Claude Code plugin seed directory and print its path",
    )
    p_seed.add_argument("dest", help="directory to create the seed in")
    p_seed.add_argument(
        "--copy",
        action="store_true",
        help="copy the tree instead of symlinking it (for hosts without symlinks)",
    )

    p_path = sub.add_parser("path", help="print the path to a packaged plugin")
    p_path.add_argument("plugin", nargs="?", default="pegasus-ai")

    sub.add_parser("marketplace", help="print the path to the packaged marketplace")
    sub.add_parser("plugins", help="list plugins declared in the manifest")

    args = parser.parse_args(argv)

    if args.command == "seed":
        print(write_seed(args.dest, copy=args.copy))
    elif args.command == "path":
        try:
            print(plugin_dir(args.plugin))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    elif args.command == "marketplace":
        print(marketplace_dir())
    elif args.command == "plugins":
        for name in list_plugins():
            print(name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

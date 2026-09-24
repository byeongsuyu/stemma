"""Run repository tasks without installation; installed packages need no path shim.

This development-only adapter locates sibling sources. Reusable packages never
import it, and neither wheel contains it or any personal data.
"""

import argparse
import runpy
import sys
from pathlib import Path

# The tool reads --root and --no-sync before its subcommand. A task below supplies that
# subcommand itself, so these have to be moved in front of it; left where they were typed
# they land after it, which is why `dev.py workspace --root somewhere` used to exit 2
# instead of starting. True means the option takes a separate value.
GLOBAL = {"--root": True, "--no-sync": False}
SUBCOMMAND = {"blog-admin": "blog-admin", "blog": "preview", "editor": "editor", "workspace": "editor"}


def split_global(arguments):
    """Separate the tool's own options from the ones its subcommand takes."""
    options, rest, expecting = [], [], False
    for item in arguments:
        if expecting:
            options.append(item)
            expecting = False
        elif item.split("=", 1)[0] in GLOBAL:
            options.append(item)
            expecting = GLOBAL[item.split("=", 1)[0]] and "=" not in item
        else:
            rest.append(item)
    return options, rest


def invocation(task, forwarded, root):
    """The module to run, and the argv to run it with."""
    if task == "test":
        return "unittest", ["discover", "-s", str(Path(root) / "tests"), *forwarded]
    if task == "example":
        return "graph_only", list(forwarded)
    options, rest = split_global(forwarded)
    named = SUBCOMMAND.get(task)
    return "stemma_studio.cli", [*options, *([named] if named else []), *rest]


def main():
    # Plain `python3` may be an older system interpreter; fail before any 3.12-only code imports.
    # Keep this file parseable by old interpreters so the message is what they print.
    if sys.version_info < (3, 12):
        sys.exit(f"Python 3.12+ is required (found {sys.version.split()[0]}). Run: python3.12 -B scripts/dev.py ...")
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run local Studio development tasks.")
    parser.add_argument("task", choices=("test", "example", "studio", "editor", "blog", "blog-admin", "workspace"))
    args, forwarded = parser.parse_known_args()
    sys.path[:0] = [str(root / "packages" / "stemma_graph" / "src"), str(root / "src")]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "packages" / "stemma_graph" / "examples"))
    module, arguments = invocation(args.task, forwarded, root)
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")


if __name__ == "__main__":
    main()

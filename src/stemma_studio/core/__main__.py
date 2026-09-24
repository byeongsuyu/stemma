"""Thin command-line adapter over Studio use cases.

Parsing and printing belong here; graph algorithms and persistence rules do not.
The publish command updates local metadata only and never uploads content."""

import argparse
import json
import sys
from pathlib import Path

from .application import Studio as Store
from .domain import ModelError, genealogy, set_representatives

COMMANDS = (
    "validate",
    "migrate",
    "sync-archive",
    "create",
    "graph",
    "confirm",
    "archive",
    "restore",
    "revise",
    "represent",
    "publish",
    "unpublish",
    "export-public",
)


def build_parser():
    """Build the shared parser and return it together with its subcommand action.

    ``stemma_studio.cli`` registers the editor and blog commands on the same
    subparsers, so every command accepts the same --root and --no-sync options.
    """
    parser = argparse.ArgumentParser(prog="stemma", description="Stemma: manage writing and its genealogy locally.")
    parser.add_argument("--no-sync", action="store_true", help="Use the cached archive without checking Git.")
    # Installed code has no implicit relationship to the user's data directory.
    parser.add_argument(
        "--root", default=str(Path.cwd()), help="Studio data root; defaults to the current working directory."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Check stored metadata and content hashes.")
    sub.add_parser("migrate", help="Upgrade the data root to the current schema version.")
    sync = sub.add_parser("sync-archive", help="Import committed writing from a Git archive.")
    sync.add_argument("--archive", help="Local Git archive path; remembered after the first successful sync.")
    sync.add_argument("--dry-run", action="store_true")
    create = sub.add_parser("create", help="Create a draft document from a file.")
    create.add_argument("document")
    create.add_argument("file")
    create.add_argument("--title", required=True)
    create.add_argument("--question", action="append", required=True)
    create.add_argument("--parent", action="append", default=[])
    create.add_argument("--note", required=True)
    graph = sub.add_parser("graph", help="Print the genealogy for one question.")
    graph.add_argument("question")
    confirmation = sub.add_parser("confirm", help="Confirm a draft as a finished document.")
    confirmation.add_argument("document")
    confirmation.add_argument(
        "--archive-parent",
        action="append",
        default=[],
        help="Retire this parent document from future use as the succession is confirmed.",
    )
    for name in ("archive", "restore"):
        command = sub.add_parser(name, help="Archive or restore a document.")
        command.add_argument("document")
    revision = sub.add_parser("revise", help="Store a new revision of a confirmed document.")
    revision.add_argument("document")
    revision.add_argument("file", help="New body file; the stored snapshot is never edited in place.")
    revision.add_argument("--note", required=True)
    revision.add_argument(
        "--archive-parent",
        action="append",
        default=[],
        help="Retire the succession parent as the new revision of a confirmed document is stored.",
    )
    rep = sub.add_parser("represent", help="Set the representative documents for a question.")
    rep.add_argument("question")
    rep.add_argument("documents", nargs="*")
    publish = sub.add_parser("publish", help="Select a reviewed bilingual pair for publication.")
    publish.add_argument("document")
    publish.add_argument(
        "--pair", required=True, help="Reviewed bilingual pair ID; revision-only publishing is disabled."
    )
    unpublish = sub.add_parser("unpublish", help="Clear the selected publication pair.")
    unpublish.add_argument("document")
    export = sub.add_parser("export-public", help="Print the prospective public payload without saving.")
    export.add_argument("--planned-at", help="Explicit UTC publication time for a prospective nonempty export.")
    return parser, sub


def dispatch(args, parser):
    """Load verified state, run one use case, and print JSON."""
    store = Store(args.root)
    try:
        # Loading checks content hashes before any command reads or modifies metadata.
        if args.command == "sync-archive":
            state, report = store.sync_archive(args.archive, args.dry_run)
            print(json.dumps({**report, "added_count": len(report["added"])}, ensure_ascii=False, indent=2))
            if report["status"] == "blocked":
                parser.exit(1)
            return
        state = store.load(auto_sync=not args.no_sync and args.command not in ("migrate", "export-public"))
        if store.last_sync_report and store.last_sync_report["status"] != "up_to_date":
            report = store.last_sync_report
            brief = {k: v for k, v in report.items() if k not in ("added", "moved")}
            brief["added_count"] = len(report.get("added", []))
            print(json.dumps({"archive_sync": brief}, ensure_ascii=False), file=sys.stderr)
        if args.command == "validate":
            result = {
                "valid": True,
                "documents": len(state["documents"]),
                "edges": len(state["edges"]),
                "archived": sum(d["archived"] for d in state["documents"].values()),
            }
        elif args.command == "migrate":
            store.save(state)
            result = {"schema_version": state["schema_version"]}
        elif args.command == "create":
            store.create_draft(
                state,
                args.document,
                args.title,
                args.question,
                Path(args.file).read_text(encoding="utf-8"),
                [{"parent": p, "questions": args.question} for p in args.parent],
                args.note,
            )
            result = {"draft": args.document}
        elif args.command == "graph":
            result = genealogy(state, args.question)
        elif args.command == "confirm":
            store.confirm(state, args.document, args.archive_parent)
            result = {"confirmed": args.document, "archived_parents": args.archive_parent}
        elif args.command in ("archive", "restore"):
            store.set_archived(state, args.document, args.command == "archive")
            result = {"document": args.document, "archived": args.command == "archive"}
        elif args.command == "revise":
            result_state = store.add_revision(
                state,
                args.document,
                Path(args.file).read_text(encoding="utf-8"),
                args.note,
                archive_parents=args.archive_parent,
            )
            result = {
                "document": args.document,
                "revision": result_state["documents"][args.document]["current_revision"],
            }
        elif args.command == "represent":
            store.save(set_representatives(state, args.question, args.documents))
            result = {"representatives": args.documents}
        elif args.command in ("publish", "unpublish"):
            store.select_publication(state, args.document, args.pair if args.command == "publish" else None)
            result = {
                "document": args.document,
                "selected_pair": args.pair if args.command == "publish" else None,
                "deployed": False,
            }
        else:
            result = store.export_public(state, args.planned_at)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ModelError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(1, "error: " + str(error) + "\n")


def main():
    parser, _ = build_parser()
    dispatch(parser.parse_args(), parser)


if __name__ == "__main__":
    main()

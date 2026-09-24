"""The single `stemma` entry point.

Core model commands come from :mod:`stemma_studio.core.__main__`; this module
adds the commands that start a local server or prepare a new data root, so that
one installed command covers the whole tool.
"""

import json
import sys
from pathlib import Path

from .core.__main__ import COMMANDS, build_parser, dispatch


def add_commands(sub):
    """Register the app-level commands on the shared subparser action."""
    sub.add_parser("init", help="Create an empty Studio data root in --root.")
    editor = sub.add_parser("editor", help="Serve the writing desk and publication screens.")
    editor.add_argument("--port", type=int, default=8787)
    admin = sub.add_parser("blog-admin", help="Serve the blog publication and release manager alone.")
    admin.add_argument("--port", type=int, default=8768)
    admin.add_argument("--read-only", action="store_true")
    admin.add_argument("--demo", action="store_true", help="Disposable synthetic corpus; needs a source checkout.")
    preview = sub.add_parser("preview", help="Serve a synthetic sample of the blog, or a folder you exported.")
    preview.add_argument("--port", type=int, default=8766)
    preview.add_argument("--base", help="Serve under this path. Read from the export when --folder is given.")
    preview.add_argument("--folder", help="A folder this tool published; it is checked against its receipt and served.")


def serve(server, message):
    print(message, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def run_init(root, parser):
    from .core.application import Studio
    from .core.domain import empty_state

    target = Path(root)
    if (target / "data" / "studio.json").exists():
        parser.exit(1, f"error: {target} already holds a Studio data root\n")
    Studio(target).save(empty_state())
    print(json.dumps({"root": str(target.resolve()), "created": "data/studio.json"}, indent=2))
    print(
        f"\nNext: stemma --root {root} editor\n      stemma --root {root} sync-archive --archive /path/to/your/archive",
        file=sys.stderr,
    )


def run_blog_admin(args, parser):
    import tempfile

    from .blog.admin_server import Server
    from .core.repository import FileRepository

    temporary, root = None, args.root
    if args.demo:
        try:
            # Demo data is deliberately sourced from the synthetic test factory,
            # which only exists in a source checkout, not in an installed wheel.
            from tests.blog_fixtures import make_fixture
        except ImportError:
            parser.exit(1, "error: --demo needs a source checkout of the repository\n")
        temporary = tempfile.TemporaryDirectory(prefix="stemma-demo-")
        root = str(Path(temporary.name) / "studio")
        Path(root).mkdir()
        make_fixture(root, unrelated=0)
        repository = FileRepository(root)
        state = repository.load()
        for index, doc in enumerate(state["documents"].values(), 1):
            doc["title"] = "가상 글 " + str(index)
        repository.save(state)
    server = Server(root, args.port, args.read_only, args.demo)
    server.admin.state()
    try:
        serve(
            server,
            "Blog manager: http://127.0.0.1:{}/ ({})".format(
                server.server_port, "temporary fixture" if args.demo else "local author workspace"
            ),
        )
    finally:
        if temporary:
            temporary.cleanup()


def read_export(folder, parser):
    """Read a folder this tool published, checking it against its own receipt.

    A published site uses absolute paths, so opening its index.html as a file gives a
    page with no stylesheet and no way to tell a good export from a broken one. Serving
    it answers that by eye; the receipt answers it exactly, because it names every file
    the release froze along with the bytes it froze. Both are worth having.
    """
    import hashlib
    import re

    from .blog.local_folder import MANIFEST, read_manifest
    from .core.containment import contained

    target = Path(folder).expanduser()
    if not target.is_dir():
        parser.exit(1, f"error: {target} is not a folder\n")
    target = target.resolve()
    record = read_manifest(target)
    if record is None:
        parser.exit(1, f"error: {target} has no {MANIFEST}; this tool did not publish it\n")
    files, missing, differing = {}, [], []
    for name, digest in record["files"].items():
        path = contained(target, name)
        if path is None or not path.is_file():
            missing.append(name)
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            files[name] = data
        else:
            differing.append(name)
    # Every page links the stylesheet by its full published path, so the page itself says
    # which base it was built for; nothing outside the folder has to be consulted.
    found = re.search(rb'href="([^"]*)site\.css"', files.get("index.html", b""))
    return target, record, files, missing, differing, (found.group(1).decode() if found else "/")


def run_preview(args, parser):
    from http.server import ThreadingHTTPServer

    from .blog.preview import fixture_public, handler, static_files

    if args.folder:
        target, record, files, missing, differing, base = read_export(args.folder, parser)
        base = args.base or base
        total = len(record["files"])
        print(f"{target}\n  release {record['release']} · {total} files")
        for label, names in (("missing", missing), ("different from the release", differing)):
            if names:
                print(f"  {len(names)} {label}: " + ", ".join(sorted(names)[:5]))
        print(
            "  every file matches the release"
            if not missing and not differing
            else "  this folder does not match its receipt"
        )
        # A folder worth inspecting is often one that came out wrong, so serve it even
        # when the page the handler falls back to is one of the files that went missing.
        files.setdefault("404.html", b"<!doctype html><title>404</title><p>Not in this export.")
    else:
        base = args.base or "/blog/"
        files = static_files(fixture_public(), base=base, preview=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(files, base, args.port))
    serve(server, f"Local preview: http://127.0.0.1:{args.port}{base}")


def main():
    parser, sub = build_parser()
    add_commands(sub)
    args = parser.parse_args()
    if args.command in COMMANDS:
        return dispatch(args, parser)
    if args.command == "init":
        return run_init(args.root, parser)
    if args.command == "editor":
        from .editor.workspace_server import Server

        server = Server(args.root, args.port)
        server.editor.state()
        return serve(server, f"Stemma: http://127.0.0.1:{server.server_port}/ · /publish/")
    if args.command == "blog-admin":
        return run_blog_admin(args, parser)
    return run_preview(args, parser)


if __name__ == "__main__":
    main()

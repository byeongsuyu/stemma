"""Loopback author UI, protected writes and isolated in-memory preview URLs."""

import argparse
import json
import mimetypes
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from stemma_studio.core.domain import ModelError
from stemma_studio.locale import Message, carried, interface_language, localise, page, save_language

from .admin import Admin, Conflict
from .render import CSP

STATIC = Path(__file__).parent / "admin_frontend"


class Server(ThreadingHTTPServer):
    def __init__(self, root, port=8768, read_only=False, demo=False):
        self.admin = Admin(root, read_only)
        self.token = secrets.token_urlsafe(32)
        self.request_lock = threading.RLock()
        self.demo = demo
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, *args):
        pass

    def language(self):
        # The author's choice for this data root, else what the browser asks for.
        return interface_language(self.server.admin.root, self.headers.get("Accept-Language"))

    def send(self, status, value, kind="application/json; charset=utf-8", preview=False):
        if isinstance(value, (dict, list)):
            value = localise(value, self.language())
        data = json.dumps(value, ensure_ascii=False).encode("utf-8") if isinstance(value, (dict, list)) else value
        self.send_response(status)
        for key, val in [
            ("Content-Type", kind),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            (
                "Content-Security-Policy",
                (
                    CSP
                    if preview
                    else "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'"
                )
                +
                # Only the local manager may frame its own reader preview; nothing frames the manager.
                ("; frame-ancestors 'self'" if preview else "; frame-ancestors 'none'"),
            ),
        ]:
            self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def dispatch(self, write=False):
        try:
            host = self.headers.get("Host")
            allowed = {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}
            if host not in allowed:
                return self.send(403, {"error": Message("error.local_only")})
            route = urlsplit(self.path)
            path = unquote(route.path)
            query = {k: v[0] for k, v in parse_qs(route.query).items()}
            admin = self.server.admin
            # Requests are serialized, so this is the language of the one being answered.
            admin.language = self.language()
            if write:
                if (
                    self.headers.get("Origin") not in (None, "http://" + host)
                    or self.headers.get("X-Blog-Token") != self.server.token
                ):
                    return self.send(403, {"error": Message("error.reload_cross_site")})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.send(415, {"error": Message("error.json")})
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4_000_000:
                    return self.send(413, {"error": Message("error.too_large", size=4)})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError(Message("error.bad_request"))
                if path == "/api/interface-language":
                    # A preference of the desk rather than the author's data, so read-only allows it.
                    return self.send(200, {"language": save_language(admin.root, body.get("language"))})
                if path == "/api/render-preview":
                    from .author_preview import preview

                    return self.send(
                        200,
                        {
                            "html": preview(
                                body.get("title", ""),
                                body.get("body", ""),
                                body.get("language", "ko"),
                                body.get("summary", ""),
                                interface=admin.language,
                            )
                        },
                    )
                if path not in [
                    "/api/" + p
                    for p in (
                        "draft",
                        "preview",
                        "select",
                        "unselect",
                        "series-save",
                        "series-order",
                        "revert",
                        "release-configure",
                        "release-freeze-home",
                        "release-build",
                        "release-deploy",
                        "release-check",
                        "release-interrupt",
                        "site-settings",
                        "import-scan",
                        "import-apply",
                    )
                ]:
                    return self.send(404, {"error": Message("error.no_route")})
                return self.send(200, admin.action(path[5:], body))
            if path.startswith("/render-assets/"):
                from .author_preview import ASSETS, FRONTEND

                name = path[len("/render-assets/") :]
                if name in ASSETS:
                    return self.send(
                        200, (FRONTEND / name).read_bytes(), "text/css" if name.endswith(".css") else "font/woff2"
                    )
            if path in ("/fonts/MaruBuri-Regular.woff2", "/fonts/MaruBuri-Bold.woff2", "/fonts/OFL.txt"):
                return self.send(
                    200,
                    (STATIC.parent / "frontend" / path[1:]).read_bytes(),
                    "font/woff2" if path.endswith(".woff2") else "text/plain; charset=utf-8",
                )
            if path in ("/", "/admin.js", "/admin.css", "/buffer.js", "/flow.js", "/i18n.js"):
                name = "index.html" if path == "/" else path[1:]
                return self.send(
                    200,
                    page(STATIC / name, admin.language) if name.endswith(".html") else (STATIC / name).read_bytes(),
                    {"html": "text/html", "css": "text/css", "js": "text/javascript"}[name.split(".")[-1]]
                    + "; charset=utf-8",
                )
            if path == "/api/session":
                return self.send(
                    200,
                    {
                        "token": self.server.token,
                        "read_only": admin.read_only,
                        "demo": self.server.demo,
                        "editor_url": "/" if getattr(self.server, "unified", False) else None,
                        # Browser-side recovery is namespaced by this, the way the editor's is:
                        # two data roots served from one local origin must not read each
                        # other's drafts when their imported document IDs happen to agree.
                        "workspace": str(admin.root),
                    },
                )
            if path == "/api/site-settings":
                return self.send(200, admin.site_settings())
            if path == "/api/releases":
                return self.send(200, admin.release_status(query.get("rollback")))
            if path == "/api/catalog":
                return self.send(200, admin.catalog(query.get("q", ""), query.get("status", "all")))
            if path == "/api/document":
                return self.send(200, admin.detail(query["id"], query.get("revision")))
            if path.startswith("/preview/"):
                parts = path.split("/", 3)
                review = admin.previews.get(parts[2]) if len(parts) == 4 else None
                if review:
                    key = parts[3] + ("index.html" if parts[3].endswith("/") or not parts[3] else "")
                    files = review["files"]
                    found = key in files
                    return self.send(
                        200 if found else 404,
                        files[key] if found else files["404.html"],
                        (mimetypes.guess_type(key)[0] if found else "text/html") or "application/octet-stream",
                        True,
                    )
                return self.send(404, b"Preview expired. Return to the local manager.", "text/plain")
            if path.startswith("/release/"):
                # A frozen release, read here before it reaches a reader or a merge.
                parts = path.split("/", 3)
                releases = admin.state()["blog"]["releases"] if len(parts) == 4 else {}
                if parts[2] in releases:
                    files = admin.release_preview(parts[2])["files"]
                    key = parts[3] + ("index.html" if parts[3].endswith("/") or not parts[3] else "")
                    found = key in files
                    return self.send(
                        200 if found else 404,
                        files[key] if found else files["404.html"],
                        (mimetypes.guess_type(key)[0] if found else "text/html") or "application/octet-stream",
                        True,
                    )
                return self.send(404, b"No such release. Return to the local manager.", "text/plain")
            self.send(404, {"error": Message("error.no_route")})
        except Conflict as error:
            self.send(409, {"error": carried(error)})
        except (ValueError, ModelError, KeyError, TypeError, StopIteration) as error:
            self.send(400, {"error": carried(error) or Message("error.check_input")})
        except RuntimeError as error:
            self.send(400, {"error": carried(error)})
        except OSError:
            self.send(500, {"error": Message("error.io_admin")})

    def do_GET(self):
        with self.server.request_lock:
            self.dispatch()

    def do_POST(self):
        with self.server.request_lock:
            self.dispatch(True)

    do_HEAD = do_GET


def main():
    parser = argparse.ArgumentParser(description="Local blog author and release manager")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", help="Explicit Studio root; no automatic archive sync")
    group.add_argument("--demo", action="store_true", help="Disposable synthetic corpus")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    temporary = None
    if args.demo:
        # Demo data is deliberately sourced from the existing synthetic test factory.
        from tests.blog_fixtures import make_fixture

        from stemma_studio.core.repository import FileRepository

        temporary = tempfile.TemporaryDirectory(prefix="stemma-demo-")
        args.root = str(Path(temporary.name) / "studio")
        Path(args.root).mkdir()
        make_fixture(args.root, unrelated=0)
        repo = FileRepository(args.root)
        state = repo.load()
        for index, doc in enumerate(state["documents"].values(), 1):
            doc["title"] = "가상 글 " + str(index)
        repo.save(state)
    server = Server(args.root, args.port, args.read_only, args.demo)
    server.admin.state()
    print(
        "Blog manager: http://127.0.0.1:{}/ ({})".format(
            server.server_port, "temporary fixture" if args.demo else "local author workspace"
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()

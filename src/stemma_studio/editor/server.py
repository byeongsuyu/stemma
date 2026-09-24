"""Serve an allowlisted local UI and JSON API without exposing repository files."""

import argparse
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from stemma_studio.core.domain import ModelError
from stemma_studio.locale import Message, carried, interface_language, localise, page, save_language, translate

from .service import Conflict, Editor

STATIC = Path(__file__).parent / "frontend"


class Server(ThreadingHTTPServer):
    def __init__(self, root, port=8787):
        self.request_lock = threading.RLock()
        self.editor = Editor(root)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    # Idle browser preconnections must not monopolize the listener.
    timeout = 10

    def log_message(self, *_):
        """Do not log private queries or manuscript contents."""

    def language(self):
        # The author's choice for this data root, else what the browser asks for.
        return interface_language(self.server.editor.root, self.headers.get("Accept-Language"))

    def send(self, status, data, content_type="application/json; charset=utf-8"):
        if isinstance(data, (dict, list)):
            data = localise(data, self.language())
        raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(raw)

    def dispatch(self, write=False):
        try:
            port = self.server.server_port
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                return self.send(403, {"error": Message("error.local_only")})
            if write:
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + h for h in allowed}:
                    return self.send(403, {"error": Message("error.cross_site")})
                if self.headers.get("X-Editor-Token") != self.server.token:
                    return self.send(403, {"error": Message("error.reload")})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.send(415, {"error": Message("error.json")})
                size = int(self.headers.get("Content-Length", "0"))
                # Base64 costs a third on top of the bytes, so attachments get their
                # own ceiling rather than forcing every picture to be tiny.
                limit = 12_000_000 if urlsplit(self.path).path == "/api/assets" else 4_000_000
                if not 0 < size <= limit:
                    return self.send(413, {"error": Message("error.too_large", size=limit // 1_000_000)})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError(Message("error.bad_request"))
            route = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(route.query).items()}
            editor = self.server.editor
            # Requests are serialized, so this is the language of the one being answered.
            editor.language = self.language()
            if not write:
                if route.path.startswith("/render-assets/"):
                    from stemma_studio.blog.author_preview import ASSETS, FRONTEND

                    name = route.path[len("/render-assets/") :]
                    if name in ASSETS:
                        kind = "text/css; charset=utf-8" if name.endswith(".css") else "font/woff2"
                        return self.send(200, (FRONTEND / name).read_bytes(), kind)
                if route.path.startswith("/attachments/"):
                    from stemma_studio.core.uploads import EXTENSIONS

                    # A stored file is named by its own hash, so this is the whole check.
                    found = re.fullmatch(r"[0-9a-f]{64}(\.[a-z]+)", route.path[len("/attachments/") :])
                    if not found or found.group(1) not in EXTENSIONS:
                        return self.send(404, {"error": Message("error.no_attachment")})
                    name = found.group(0)
                    try:
                        content = editor.studio.repository.read_bytes("data/assets/" + name)
                    except (FileNotFoundError, KeyError):
                        return self.send(404, {"error": Message("error.no_attachment")})
                    return self.send(200, content, EXTENSIONS[found.group(1)])
                if route.path == "/api/markdown-example":
                    from stemma_studio.blog.author_preview import EXAMPLES, preview

                    example = EXAMPLES[editor.language]
                    title = translate(editor.language, "editor.markdown_example")
                    html = preview(title, example, editor.language, interface=editor.language)
                    return self.send(200, {"source": example, "html": html})
                if route.path in (
                    "/",
                    "/app.js",
                    "/style.css",
                    "/work-buffer.js",
                    "/feedback.js",
                    "/i18n.js",
                    "/genealogy",
                    "/genealogy.js",
                    "/genealogy.css",
                    "/genealogy-layout.js",
                ):
                    name = {"/": "index.html", "/genealogy": "genealogy.html"}.get(route.path, route.path[1:])
                    kind = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.split(".")[-1]]
                    content = (
                        page(STATIC / name, editor.language) if name.endswith(".html") else (STATIC / name).read_bytes()
                    )
                    return self.send(200, content, kind + "; charset=utf-8")
                if route.path == "/api/session":
                    return self.send(
                        200,
                        {
                            "token": self.server.token,
                            "publication_url": "/publish/" if getattr(self.server, "unified", False) else None,
                            "workspace": str(editor.root),
                            "questions": editor.state()["questions"],
                        },
                    )
                if route.path == "/api/documents":
                    offset = max(0, int(query.get("offset", "0")))
                    return self.send(200, editor.catalog(query.get("q", ""), query.get("archived") == "true", offset))
                if route.path == "/api/genealogy":
                    ids = list(filter(None, query.get("ids", "").split(",")))
                    return self.send(200, editor.components(ids, query.get("proposed") == "true"))
                if route.path == "/api/document":
                    return self.send(200, editor.detail(query["id"], query.get("revision")))
                if route.path == "/api/works":
                    return self.send(200, editor.works())
                if route.path == "/api/work":
                    return self.send(200, editor.work(query["id"]))
            else:
                if route.path == "/api/render-preview":
                    from stemma_studio.blog.author_preview import preview

                    # Attachments are read from the saved work, never from the request,
                    # so a preview can only ever show what this draft actually holds. A
                    # manuscript is set in the language it is written in.
                    return self.send(
                        200,
                        {
                            "html": preview(
                                body.get("title", ""),
                                body.get("body", ""),
                                editor.manuscript_language(body.get("id")),
                                assets=editor.previewable(body.get("id")),
                                interface=editor.language,
                            )
                        },
                    )
                if route.path == "/api/interface-language":
                    return self.send(200, {"language": save_language(editor.root, body.get("language"))})
                if route.path == "/api/works":
                    return self.send(200, editor.new(body.get("document_id")))
                if route.path == "/api/work":
                    return self.send(200, editor.update(body["id"], body))
                if route.path == "/api/assets":
                    return self.send(200, editor.attach(body["id"], body.get("files")))
                if route.path == "/api/work/delete":
                    return self.send(200, editor.delete_work(body["id"], body["version"]))
                if route.path == "/api/commit":
                    if type(body.get("confirm")) is not bool:
                        raise ValueError(Message("error.confirm_flag"))
                    return self.send(200, editor.commit(body["id"], body["version"], body["confirm"]))
                if route.path == "/api/restore":
                    return self.send(200, editor.restore(body["id"]))
            self.send(404, {"error": Message("error.no_route")})
        except Conflict as error:
            self.send(409, {"error": carried(error)})
        except (ModelError, ValueError, KeyError, TypeError, StopIteration) as error:
            self.send(400, {"error": carried(error) or Message("error.not_found")})
        except OSError:
            self.send(500, {"error": Message("error.io_editor")})

    def do_GET(self):
        with self.server.request_lock:
            self.dispatch()

    def do_POST(self):
        with self.server.request_lock:
            self.dispatch(write=True)


def main():
    parser = argparse.ArgumentParser(description="Local Stemma editor")
    parser.add_argument("--root", default=".")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = Server(args.root, args.port)
    server.editor.state()
    print(f"Stemma: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

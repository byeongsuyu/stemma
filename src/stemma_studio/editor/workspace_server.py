"""One loopback listener and write lock for editing and publication workflows."""

import argparse
from urllib.parse import urlsplit

from stemma_studio.blog.admin import Admin
from stemma_studio.blog.admin_server import Handler as PublicationHandler
from stemma_studio.locale import Message

from .server import Handler as EditorHandler
from .server import Server as EditorServer


class Handler(EditorHandler):
    def send(self, status, data, content_type="application/json; charset=utf-8", preview=False):
        return PublicationHandler.send(self, status, data, content_type, preview)

    def dispatch(self, write=False):
        path = urlsplit(self.path).path
        original = self.path
        if path == "/publish":
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                return self.send(403, {"error": Message("error.local_only")})
            self.send_response(302)
            self.send_header("Location", "/publish/")
            self.end_headers()
            return
        # A reader preview links its assets absolutely, so the paths it was rendered for
        # belong to the publication side wherever the manager itself happens to be mounted.
        if path.startswith(("/publish/", "/preview/", "/release/", "/fonts/")):
            if path.startswith("/publish/"):
                self.path = self.path[len("/publish") :]
            try:
                return PublicationHandler.dispatch(self, write)
            finally:
                self.path = original
        return EditorHandler.dispatch(self, write)


class Server(EditorServer):
    def __init__(self, root, port=8787):
        super().__init__(root, port)
        self.admin = Admin(root)
        self.demo = False
        self.unified = True
        self.RequestHandlerClass = Handler


def main():
    parser = argparse.ArgumentParser(description="Stemma: editor and publication workspace")
    parser.add_argument("--root", default=".")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = Server(args.root, args.port)
    server.editor.state()
    print(f"Stemma: http://127.0.0.1:{server.server_port}/ · /publish/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

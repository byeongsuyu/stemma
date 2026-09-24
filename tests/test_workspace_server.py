"""Shared listener must preserve both API security and memory-only preview behavior."""

import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

import stemma_studio
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import empty_state
from stemma_studio.editor.workspace_server import Server

FRONTEND = Path(stemma_studio.__file__).resolve().parent / "editor" / "frontend"


def module_graph(*entries):
    """Every module the pages pull in, following imports the way a browser would."""
    seen, pending = set(), list(entries)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        source = (FRONTEND / name).read_text(encoding="utf-8")
        pending += [m + ".js" for m in re.findall(r"""from\s+['"]\./([\w-]+)\.js['"]""", source)]
    return sorted(seen)


class WorkspaceServerTests(unittest.TestCase):
    def test_both_workflows_and_preview_share_one_protected_listener(self):
        with tempfile.TemporaryDirectory() as root:
            Studio(root).repository.save(empty_state())
            server = Server(root, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                for path in (
                    "/",
                    "/publish/",
                    *("/" + name for name in module_graph("app.js", "genealogy.js")),
                    "/publish/admin.js",
                    "/publish/flow.js",
                    "/publish/i18n.js",
                    "/api/session",
                    "/publish/api/session",
                    "/render-assets/site.css",
                    "/render-assets/theme.css",
                    "/api/markdown-example",
                ):
                    client.request("GET", path)
                    response = client.getresponse()
                    body = response.read()
                    self.assertEqual(response.status, 200, path)
                    if path == "/api/markdown-example":
                        self.assertIn(b"[^1]", body)
                # A module the page imports but the server does not serve breaks the whole
                # desk, and only the browser would have noticed. The list is derived from
                # the imports so adding one cannot quietly go unserved.
                self.assertIn("feedback.js", module_graph("app.js", "genealogy.js"))
                # A release preview links its assets from the server root, so the shared
                # listener has to hand those paths to the publication side. An unknown
                # release answering in its own words is what proves the route arrived.
                client.request("GET", "/release/none/")
                answer = client.getresponse()
                body = answer.read()
                self.assertEqual(answer.status, 404)
                self.assertIn(b"No such release", body)
                before = Path(root, "data/studio.json").read_bytes()
                payload = json.dumps(
                    {
                        "title": "Draft",
                        "body": "passage $A$; question: **high**.",
                        "language": "en",
                        "summary": "*Italic* [private](file:///private)",
                    }
                )
                for headers, status in [
                    ({"Content-Type": "application/json"}, 403),
                    (
                        {
                            "Content-Type": "application/json",
                            "X-Blog-Token": server.token,
                            "Origin": "https://evil.example",
                        },
                        403,
                    ),
                    ({"Content-Type": "application/json", "X-Blog-Token": server.token}, 200),
                ]:
                    client.request("POST", "/publish/api/render-preview", payload, headers)
                    response = client.getresponse()
                    data = response.read()
                    self.assertEqual(response.status, status)
                    if status == 200:
                        html = json.loads(data)["html"]
                        self.assertIn('lang="en"', html)
                        self.assertIn("<em>Italic</em>", html)
                        self.assertIn("question: <strong>high</strong>", html)
                        self.assertIn("passage <span", html)
                        self.assertNotIn("file:", html)
                client.request("GET", "/publish/data/studio.json")
                response = client.getresponse()
                response.read()
                self.assertEqual(response.status, 404)
                self.assertEqual(before, Path(root, "data/studio.json").read_bytes())
                client.close()
            finally:
                server.shutdown()
                server.server_close()

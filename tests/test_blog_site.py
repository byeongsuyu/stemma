"""Static rendering and HTTP boundaries run only on synthetic public inputs."""

import copy
import http.client
import threading
import unittest
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from stemma_studio.blog.input import LinkRewriter
from stemma_studio.blog.markdown import external_url, markdown
from stemma_studio.blog.preview import fixture_public, handler, static_files
from stemma_studio.blog.render import render_site
from stemma_studio.blog.site_settings import DEFAULT_LICENSE, LICENSES
from stemma_studio.blog.site_settings import DEFAULTS as SITE_DEFAULTS
from stemma_studio.blog.vendor.mistune import create_markdown


class Links(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.urls = []
        self.tags = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.urls.extend(v for k, v in attrs if k in ("href", "src") and not v.startswith("#"))


class BlogSiteTests(unittest.TestCase):
    def setUp(self):
        self.public = fixture_public()

    def test_all_local_urls_exist_at_base_and_bilingual_routes(self):
        files = static_files(self.public, base="/nested/blog/")
        for name, content in files.items():
            if not name.endswith(".html"):
                continue
            page = content.decode("utf-8", errors="ignore")
            if name.startswith(("ko/", "en/")):
                self.assertIn('<html lang="' + name[:2] + '">', page)
            for url in Links(page).urls:
                self.assertTrue(url.startswith("/nested/blog/"), (name, url))
                target = url[len("/nested/blog/") :]
                self.assertIn(target + ("index.html" if target.endswith("/") else ""), files, (name, url))
        self.assertIn("en/posts/post-d/genealogy/index.html", files)

    def test_home_brand_and_intro_are_not_repeated_in_body(self):
        page = render_site(self.public)["ko/index.html"].decode()
        body = page.split("<main", 1)[1].split("</main>", 1)[0]
        self.assertNotIn("글과 생각", body)
        self.assertNotIn("읽고, 생각하고, 다시 쓰는 기록.", body)
        self.assertIn("전체 글", body)

    def parts(self, page):
        return (
            page.split('<header class="site-header">')[1].split("</header>")[0],
            page.split('<footer class="site-footer">')[1].split("</footer>")[0],
        )

    def test_brand_tagline_and_copyright_placement(self):
        """Identity comes from the author's settings; the tagline belongs in the header only."""
        site = {
            "ko": {"name": "나의 기록", "author": "홍길동", "byline": "홍길동", "intro": "읽고 다시 묻는 기록"},
            "en": {
                "name": "My Record",
                "author": "Gildong Hong",
                "byline": "by Gildong Hong",
                "intro": "Reading and asking again.",
            },
        }
        for lang in ("ko", "en"):
            header, footer = self.parts(render_site(self.public, site=site)[lang + "/index.html"].decode())
            self.assertIn(site[lang]["name"], header)
            self.assertIn(site[lang]["byline"], header)
            self.assertIn(site[lang]["intro"], header)
            self.assertNotIn(site[lang]["intro"], footer)
            self.assertIn("© " + site[lang]["author"] + ". " + LICENSES[DEFAULT_LICENSE][lang] + ".", footer)

    def test_unconfigured_site_renders_placeholders_and_no_author_identity(self):
        """An unconfigured install must never publish somebody else's name."""
        for lang in ("ko", "en"):
            page = render_site(self.public)[lang + "/index.html"].decode()
            header, footer = self.parts(page)
            self.assertIn(SITE_DEFAULTS[lang]["name"], header)
            self.assertIn("© " + SITE_DEFAULTS[lang]["author"] + ". " + LICENSES[DEFAULT_LICENSE][lang] + ".", footer)

    def test_footer_shows_the_authors_chosen_licence_with_a_link(self):
        """The footer states the writing's terms, which the author chooses."""
        from stemma_studio.blog.site_settings import normalise

        site = normalise({"en": {"author": "Ada"}, "license": {"id": "cc-by-4.0"}})
        footer = self.parts(render_site(self.public, site=site)["en/index.html"].decode())[1]
        self.assertIn("© Ada.", footer)
        self.assertIn("CC BY 4.0", footer)
        self.assertIn('href="https://creativecommons.org/licenses/by/4.0/"', footer)
        self.assertIn('rel="license noopener noreferrer"', footer)

    def test_unconfigured_footer_reserves_all_rights_without_a_link(self):
        footer = self.parts(render_site(self.public)["en/index.html"].decode())[1]
        self.assertIn("All rights reserved.", footer)
        self.assertNotIn("<a ", footer)

    def test_custom_licence_wording_is_escaped(self):
        from stemma_studio.blog.site_settings import normalise

        site = normalise(
            {
                "license": {
                    "id": "custom",
                    "ko": "<b>조건</b>",
                    "en": "<b>Terms</b>",
                    "url": "https://example.com/?a=1&b=2",
                }
            }
        )
        footer = self.parts(render_site(self.public, site=site)["en/index.html"].decode())[1]
        self.assertNotIn("<b>", footer)
        self.assertIn("&lt;b&gt;Terms", footer)
        self.assertIn("a=1&amp;b=2", footer)

    def test_site_identity_is_escaped(self):
        site = {
            "ko": {"name": "<script>x</script>", "author": "a&b", "byline": "b", "intro": "i"},
            "en": {"name": "<script>x</script>", "author": "a&b", "byline": "b", "intro": "i"},
        }
        page = render_site(self.public, site=site)["ko/index.html"].decode()
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("a&amp;b", page)

    def test_graph_list_groups_depth_before_dates_including_unknown_parent(self):
        from stemma_studio.blog.render import render_graph

        graph = {
            "nodes": [
                {"id": "root", "kind": "private", "month": None},
                {"id": "middle", "kind": "private", "month": "2025-01"},
                {"id": "current", "kind": "public"},
            ],
            "edges": [
                {"parent": "root", "child": "middle", "questions": [], "change_note": {}},
                {"parent": "middle", "child": "current", "questions": [], "change_note": {}},
            ],
        }
        docs = {
            "current": {
                "slug": "current",
                "date": {"value": "2020-01-01"},
                "translations": {"en": {"title": "Current title"}},
            }
        }
        page = render_graph(graph, docs, "current", "en", "/blog/")
        listing = page.split("<details>")[1]
        self.assertLess(listing.index("Level 1"), listing.index("Date unknown"))
        self.assertLess(listing.index("Date unknown"), listing.index("Level 2"))
        self.assertLess(listing.index("2025-01"), listing.index("Level 3"))
        self.assertLess(listing.index("Level 3"), listing.index("Current title"))

    def test_empty_and_series_rules(self):
        empty = {"schema_version": 3, "documents": [], "genealogies": [], "series": []}
        page = render_site(empty)["ko/index.html"].decode("utf-8", errors="ignore")
        self.assertIn("아직 공개된 글이 없습니다", page)
        self.assertNotIn('class="series-list"', page)
        for i in range(3):
            s = copy.deepcopy(self.public["series"][0])
            s["slug"] = "extra-" + str(i)
            self.public["series"].append(s)
        files = render_site(self.public)
        page = files["ko/index.html"].decode("utf-8", errors="ignore")
        self.assertIn("모든 시리즈", page)
        self.assertEqual(page.count("posts</small>"), 0)
        self.assertNotIn("/series/extra-2/", page)
        self.assertIn("/series/extra-2/", files["ko/series/index.html"].decode("utf-8", errors="ignore"))
        first = files["ko/series/first/index.html"].decode("utf-8", errors="ignore")
        self.assertLess(first.index("/posts/post-c/"), first.index("/posts/post-a/"))

    def test_chronology_is_publication_order_and_series_independent(self):
        for doc in self.public["documents"]:
            if doc["slug"] == "post-d":
                doc["first_published_at"] = "2026-02-03T09:00:00Z"
            if doc["slug"] == "post-s":
                doc["first_published_at"] = "2026-02-02T09:00:00Z"
        files = render_site(self.public)
        page = files["ko/posts/post-d/index.html"].decode("utf-8", errors="ignore").split('class="chronology"')[1]
        self.assertIn("이전 공개 글", page)
        self.assertIn("/ko/posts/post-s/", page)
        self.assertNotIn("/posts/post-c/", page)
        self.public["series"].reverse()
        self.assertEqual(
            page,
            render_site(self.public)["ko/posts/post-d/index.html"]
            .decode("utf-8", errors="ignore")
            .split('class="chronology"')[1],
        )

    def test_graph_branch_merge_placeholder_and_language(self):
        files = render_site(self.public)
        page = files["en/posts/post-c/genealogy/index.html"].decode("utf-8", errors="ignore")
        self.assertEqual(page.count('class="edge"'), 5)
        self.assertIn("Unpublished", page)
        self.assertIn("2022-08", page)
        self.assertIn("Date unknown", page)
        self.assertIn("Current post", page)
        self.assertIn("/en/posts/post-a/", page)
        self.assertNotIn("미공개", page)
        isolated = files["ko/posts/post-s/genealogy/index.html"].decode("utf-8", errors="ignore")
        self.assertIn("독립된 계보", isolated)
        self.assertEqual(isolated.count('class="node current"'), 1)
        self.assertIn("현재 글", isolated)
        self.assertIn("<svg", isolated)
        self.assertNotIn('<path class="edge"', isolated)

    def test_safe_markdown_does_not_emit_private_destinations_or_html(self):
        payload = """[text](javascript:alert%281%29 "PRIVATE-TITLE")
[file](file:///PRIVATE-PATH)
[hidden](../../PRIVATE-ID.md "PRIVATE-META")
![image](https://example.org/pixel.png)
<script src="PRIVATE-SCRIPT">alert(1)</script>
<iframe src="PRIVATE-FRAME"></iframe>
[reference][secret]

[secret]: /PRIVATE-REF "PRIVATE-REF-TITLE"

**bold** and `code`
"""
        result = markdown(payload, external_url)
        parsed = Links(result)
        self.assertNotIn("img", parsed.tags)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("iframe", parsed.tags)
        self.assertNotIn("PRIVATE-", result)
        self.assertNotIn("javascript:", result)
        self.assertIn("<strong>bold</strong>", result)
        self.assertIn("https://example.org/pixel.png", result)

    def test_url_policy(self):
        for url in [
            "javascript:alert(1)",
            "file:///tmp/a",
            "data:text/html,x",
            "//evil.test",
            "https://x.test/%0afoo",
            "https://a@b.test",
            "https://x.test\\a",
        ]:
            self.assertIsNone(external_url(url), url)
        self.assertEqual(external_url("https://example.org/a"), "https://example.org/a")

    def test_public_links_rewritten_per_language_and_unknown_links_disabled(self):
        body = '[public](post:post-a) [private](post:secret "SECRET-TITLE") [old](/blog/ko/posts/post-c/)'
        for value in self.public["documents"][0]["translations"].values():
            value["body"] = body
        files = render_site(self.public, base="/blog/")
        page = files["en/posts/post-d/index.html"].decode("utf-8", errors="ignore")
        self.assertIn('href="/blog/en/posts/post-a/"', page)
        self.assertIn('href="/blog/en/posts/post-c/"', page)
        self.assertNotIn("post:secret", page)
        self.assertNotIn("SECRET-TITLE", page)

    def test_local_adapter_resolves_reference_links_without_retaining_aliases(self):
        parser = create_markdown(renderer=LinkRewriter({"studio:PRIVATE-ID": "post:post-a"}))
        result = parser(
            '[open][ref]\n\n[closed](data/revisions/PRIVATE-OTHER/r1.md "PRIVATE-TITLE")\n\n[ref]: studio:PRIVATE-ID "PRIVATE-REF-TITLE"\n'
        )
        self.assertIn("post:post-a", result)
        self.assertNotIn("PRIVATE-", result)

    def test_asset_allowlist_and_no_unselected_copy(self):
        path = "assets/" + "a" * 32 + ".png"
        doc = self.public["documents"][0]
        doc["assets"] = [{"id": "a" * 32, "url": path, "media_type": "image/png"}]
        for val in doc["translations"].values():
            val["body"] = "![allowed](" + path + ") ![private](../secret.png)"
        with self.assertRaises(ValueError):
            render_site(self.public)
        files = render_site(self.public, {path: b"fixture"}, base="/blog/")
        self.assertEqual(files[path], b"fixture")
        self.assertIn('src="/blog/' + path + '"', files["ko/posts/post-d/index.html"].decode("utf-8", errors="ignore"))
        self.assertNotIn("secret.png", b"".join(files.values()).decode("utf-8", errors="ignore"))
        with self.assertRaises(ValueError):
            render_site(self.public, {path: b"x", "secret.txt": b"private"})

    def test_missing_language_bad_routes_and_graph_cycle_rejected(self):
        with self.assertRaises(ValueError):
            render_site(self.public, base="/../")
        broken = copy.deepcopy(self.public)
        broken["documents"][0]["translations"].pop("en")
        with self.assertRaises(ValueError):
            render_site(broken)
        broken = copy.deepcopy(self.public)
        broken["documents"][0]["slug"] = "../data"
        with self.assertRaises(ValueError):
            render_site(broken)
        broken = copy.deepcopy(self.public)
        edge = broken["genealogies"][0]["edges"][0]
        edge["child"] = edge["parent"]
        with self.assertRaises(ValueError):
            render_site(broken)

    def test_studio_adapter_to_static_output_is_read_only_and_leak_free(self):
        import tempfile

        from blog_fixtures import RELEASE_TIME, make_fixture
        from stemma_studio.blog.input import prepare_input
        from stemma_studio.core.application import Studio
        from test_publication_v3 import phase_three

        with tempfile.TemporaryDirectory() as folder:
            fixture = make_fixture(folder)
            state = phase_three(fixture)
            app = Studio(folder)
            app.save(state)
            before = {str(p): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}
            bundle = prepare_input(app, state, RELEASE_TIME)
            output = static_files(bundle["public"], bundle["assets"])
            serialized = b"".join(output.values()).decode("utf-8", errors="ignore")
            for sentinel in fixture["sentinels"]:
                self.assertNotIn(sentinel, serialized)
            self.assertEqual(before, {str(p): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()})

    def test_http_allowlist_host_and_direct_routes(self):
        files = static_files(self.public)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(files, "/blog/", 0))
        port = server.server_address[1]
        server.RequestHandlerClass = handler(files, "/blog/", port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, status in [
                ("/blog/en/posts/post-c/genealogy/", 200),
                ("/blog/missing/", 404),
                ("/blog/../data/studio.json", 404),
                ("/blog/%2e%2e/data/studio.json", 404),
                ("/data/studio.json", 404),
            ]:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", path)
                res = conn.getresponse()
                self.assertEqual(res.status, status)
                self.assertIn("frame-ancestors 'none'", res.getheader("Content-Security-Policy"))
                res.read()
                conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("GET", "/blog/", headers={"Host": "evil.test"})
            res = conn.getresponse()
            self.assertEqual(res.status, 403)
            res.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

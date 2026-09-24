"""Exercise the manual editor only against temporary synthetic manuscripts."""

import copy
import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_test_support import reviewed_pair
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import ModelError, empty_state, genealogy, set_representatives
from stemma_studio.editor.server import Server
from stemma_studio.editor.service import Conflict, Editor, fingerprint


class EditorTests(unittest.TestCase):
    def test_render_preview_is_read_only_and_uses_safe_blog_typography(self):
        server = Server(self.root, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        self.addCleanup(client.close)
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        payload = json.dumps(
            {
                "title": "<script>title</script>",
                "body": "| X | Y |\n| --- | --- |\n| $x^2$ | 2 |\n\n<script>bad()</script>\n\n![private](https://example.com/tracker.png)",
            }
        )
        client.request("POST", "/api/render-preview", payload, {"Content-Type": "application/json"})
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        client.request(
            "POST", "/api/render-preview", payload, {"Content-Type": "application/json", "X-Editor-Token": server.token}
        )
        response = client.getresponse()
        result = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertIn("<math ", result["html"])
        self.assertIn("<table>", result["html"])
        self.assertNotIn("<script>", result["html"])
        self.assertNotIn("<img", result["html"])
        self.assertNotIn("https://example.com", result["html"])
        for path in ("/api/markdown-example", "/render-assets/site.css", "/render-assets/fonts/MaruBuri-Regular.woff2"):
            client.request("GET", path)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
        client.request("GET", "/render-assets/../../data/studio.json")
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 404)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root)
        state = empty_state()
        state["questions"] = {q: {"text": q, "public": False, "representatives": []} for q in ("q", "other")}
        for docid, title, text in [
            ("a", "기록을 다시 읽기", "기록은 생각을 이어 쓰는 재료입니다."),
            ("b", "짧은 글", "기록을 나중에 다시 읽고 발효시킵니다."),
        ]:
            state = self.studio.create_draft(state, docid, title, ["q", "other"], text, [], "initial")
            state = self.studio.confirm(state, docid)
        self.editor = Editor(self.root)

    def test_catalog_uses_creation_instant_not_last_edit(self):
        state = self.editor.state()
        state["documents"]["a"]["created_at"] = "2026-09-19T10:30:00+09:00"
        state["documents"]["b"]["created_at"] = "2026-09-19T02:00:00Z"
        state["documents"]["a"]["edited_at"] = "2026-09-20T20:00:00Z"
        self.studio.save(state)
        self.assertEqual([d["id"] for d in self.editor.catalog()["documents"]], ["b", "a"])
        row = self.editor.catalog()["documents"][1]
        # The date a document carries is when it was written, never when the desk last
        # touched it; the instant is sorted on, but the day is what a reader is shown.
        self.assertEqual(row["date"], "2026-09-19")
        self.assertEqual(row["date_kind"], "created")

    def test_every_surface_dates_a_document_the_same_way(self):
        """The shelf, the source reader and the genealogy all answer from one policy.

        They used to disagree: the reader read `edited_at`, so a document written once
        and edited later showed two different dates, and an imported one that had never
        been edited here showed none at all while the other surfaces showed its date.
        """
        state = self.editor.state()
        state["documents"]["a"]["created_at"] = "2026-09-19T10:30:00+09:00"
        state["documents"]["a"]["edited_at"] = "2026-09-20T20:00:00Z"
        self.studio.save(state)
        shelf = next(d for d in self.editor.catalog()["documents"] if d["id"] == "a")
        detail = self.editor.detail("a")
        nodes = [n for c in self.editor.components(["a"])["components"] for n in c["nodes"]]
        node = next(n for n in nodes if n["id"] == "a")
        self.assertEqual({shelf["date"], detail["date"], node["date"]}, {"2026-09-19"})
        self.assertEqual({shelf["date_kind"], detail["date_kind"], node["date_kind"]}, {"created"})

    def test_an_imported_source_date_wins_over_the_local_save(self):
        state = self.editor.state()
        state["documents"]["a"]["source"] = {"origin": "folder", "date": "2011-09-27", "assets": []}
        state["documents"]["a"]["created_at"] = "2026-09-19T10:30:00+09:00"
        self.studio.save(state)
        detail = self.editor.detail("a")
        self.assertEqual((detail["date"], detail["date_kind"]), ("2011-09-27", "source"))

    def source(self, docid, scopes=("q",), archive=False, role="parent"):
        d = self.editor.detail(docid)
        return {
            "id": docid,
            "revision": d["revision"],
            "sha256": d["sha256"],
            "title": d["title"],
            "role": role,
            "questions": list(scopes),
            "new_questions": [],
            "note": "함께 읽고 이어 쓴다",
            "archive": archive,
        }

    def draft(self, selections=None):
        work = self.editor.new()
        return self.editor.update(
            work["id"], dict(work, title="이어 쓴 글", body="새로운 생각", selections=selections or [])
        )

    def commit(self, work, confirm=False):
        return self.editor.commit(work["id"], work["version"], confirm)

    def test_delete_workspace_preserves_saved_revision_and_rejects_stale_version(self):
        work = self.commit(self.draft())
        other = self.draft()
        before = self.studio.metadata.read_bytes()
        files = {str(p): p.read_bytes() for p in self.root.glob("data/revisions/*/*.md")}
        with self.assertRaises(Conflict):
            self.editor.delete_work(work["id"], work["version"] - 1)
        self.assertTrue(self.editor.work_path(work["id"]).exists())
        self.editor.delete_work(work["id"], work["version"])
        self.assertFalse(self.editor.work_path(work["id"]).exists())
        self.assertEqual(self.editor.work(other["id"]), other)
        self.assertEqual(self.studio.metadata.read_bytes(), before)
        self.assertEqual(files, {str(p): p.read_bytes() for p in self.root.glob("data/revisions/*/*.md")})
        with self.assertRaises(ValueError):
            self.editor.delete_work("../studio", 1)

    def test_autosave_survives_restart_without_revisions_or_studio_changes(self):
        before = self.studio.metadata.read_bytes()
        work = self.draft([self.source("a")])
        loaded = Editor(self.root).work(work["id"])
        self.assertEqual(loaded, work)
        self.assertEqual(before, self.studio.metadata.read_bytes())
        self.assertEqual(len(list(self.root.glob("data/revisions/*/*.md"))), 2)

    def test_merge_scopes_reference_and_archive_preserve_parents(self):
        before = self.editor.detail("a")["body"]
        work = self.draft([self.source("a", ("q",), True), self.source("b", ("other",))])
        saved = self.commit(work)
        self.assertEqual(self.editor.state()["edges"], [])
        confirmed = self.commit(saved, True)
        state = self.editor.state()
        child = confirmed["document_id"]
        self.assertEqual(genealogy(state, "q")["terminals"], ["b", child])
        self.assertEqual(genealogy(state, "other")["terminals"], ["a", child])
        self.assertTrue(state["documents"]["a"]["archived"])
        self.assertEqual(self.editor.detail("a")["body"], before)
        self.assertFalse(state["documents"][child]["publication"]["selected_pair"])
        self.assertFalse(any(q["representatives"] for q in state["questions"].values()))

    def test_expression_revision_keeps_published_revision_and_confirmed_edges(self):
        work = self.commit(self.draft([self.source("a")]), True)
        docid = work["document_id"]
        state = self.editor.state()
        state = reviewed_pair(self.studio, state, docid, "r1")
        state = set_representatives(state, "q", [docid])
        self.studio.save(state)
        # External metadata change correctly invalidates an already opened buffer.
        with self.assertRaises(Conflict):
            self.commit(work)
        fresh = self.editor.new()
        # A new file-backed edit session based on the current document.
        fresh.update(
            document_id=docid,
            base=fingerprint(state["documents"][docid]),
            document_state="confirmed",
            title=state["documents"][docid]["title"],
        )
        self.editor.write_work(fresh)
        fresh = self.editor.update(fresh["id"], dict(fresh, body="표현을 다듬은 새 본문"))
        edges = copy.deepcopy(state["edges"])
        saved = self.commit(fresh)
        state = self.editor.state()
        self.assertEqual(saved["saved_revision"], "r2")
        self.assertEqual(state["edges"], edges)
        self.assertEqual(state["documents"][docid]["publication"]["selected_pair"], "pair-r1")
        self.assertEqual(state["questions"]["q"]["representatives"], [docid])
        self.assertEqual(self.studio.read_pair(state, docid, "pair-r1")["ko"]["body"], "새로운 생각")

    def test_parent_revision_is_pinned_despite_later_parent_edit(self):
        work = self.draft([self.source("a")])
        self.studio.add_revision(self.editor.state(), "a", "later parent text", "polish")
        self.commit(work, True)
        self.assertEqual(self.editor.state()["edges"][0]["parent_revision"], "r1")

    def test_reference_and_missing_question_do_not_create_succession(self):
        work = self.draft([self.source("a", role="reference")])
        self.commit(work, True)
        self.assertEqual(self.editor.state()["edges"], [])
        work = self.draft([self.source("b", ())])
        before = self.studio.metadata.read_bytes()
        with self.assertRaises(ModelError):
            self.commit(work, True)
        self.assertEqual(self.studio.metadata.read_bytes(), before)
        self.assertFalse((self.root / "data/revisions" / ("studio-" + work["id"][5:])).exists())

    def test_new_question_and_duplicate_scope_are_combined(self):
        item = self.source("a")
        item["new_questions"] = ["어떻게 다시 읽을까?", "어떻게 다시 읽을까?"]
        self.commit(self.draft([item]), True)
        state = self.editor.state()
        edge = state["edges"][0]
        self.assertEqual(len(edge["questions"]), 2)
        self.assertEqual(len(state["questions"]), 3)
        self.assertFalse(state["questions"][edge["questions"][1]]["public"])

    def test_stale_autosave_and_external_document_changes_are_rejected(self):
        work = self.draft()
        self.editor.update(work["id"], dict(work, body="newer"))
        with self.assertRaises(Conflict):
            self.editor.update(work["id"], dict(work, body="older"))
        work = self.editor.new("a")
        self.studio.add_revision(self.editor.state(), "a", "external revision", "external")
        with self.assertRaises(Conflict):
            self.commit(work)

    def test_archived_parent_blocks_commit_until_explicit_restore(self):
        work = self.draft([self.source("a")])
        self.studio.set_archived(self.editor.state(), "a")
        with self.assertRaises(ModelError):
            self.commit(work, True)
        self.editor.restore("a")
        self.commit(work, True)

    def test_partial_word_search_title_priority_and_archived_filter(self):
        result = self.editor.catalog("기록")
        self.assertEqual(result["documents"][0]["id"], "a")
        self.assertEqual(self.editor.catalog("발효")["documents"][0]["id"], "b")
        self.assertEqual(self.editor.catalog("없는단어")["total"], 0)
        self.studio.set_archived(self.editor.state(), "a")
        self.assertEqual(self.editor.catalog("기록")["total"], 1)
        self.assertEqual(self.editor.catalog("", True)["documents"][0]["id"], "a")

    def test_duplicate_parents_and_self_cycle_have_no_partial_writes(self):
        item = self.source("a")
        work = self.editor.new()
        with self.assertRaises(ValueError):
            self.editor.update(work["id"], dict(work, selections=[item, item]))
        work = self.commit(self.draft())
        item = self.source(work["document_id"])
        work = self.editor.update(work["id"], dict(work, selections=[item]))
        before = self.studio.metadata.read_bytes()
        with self.assertRaises(ModelError):
            self.commit(work, True)
        self.assertEqual(self.studio.metadata.read_bytes(), before)

    def test_commit_recovery_after_work_file_failure_does_not_duplicate_revision(self):
        work = self.draft([self.source("a")])
        with patch.object(self.editor, "write_work", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.commit(work, True)
        saved = self.commit(work, True)
        self.assertEqual(saved["document_state"], "confirmed")
        self.assertEqual(len(self.editor.state()["documents"][saved["document_id"]]["revisions"]), 1)
        self.assertEqual(len(self.editor.state()["edges"]), 1)

    def test_imported_document_cannot_be_edited_in_place(self):
        state = self.editor.state()
        state["documents"]["a"]["kind"] = "imported"
        self.studio.save(state)
        with self.assertRaises(ValueError):
            self.editor.new("a")
        self.commit(self.draft([self.source("a")]), True)
        self.assertEqual(self.editor.state()["documents"]["a"]["current_revision"], "r1")

    def test_http_rejects_external_writes_and_does_not_serve_private_paths(self):
        server = Server(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = http.client.HTTPConnection("127.0.0.1", server.server_port)
        self.addCleanup(client.close)
        client.request("GET", "/api/session")
        response = client.getresponse()
        session = json.loads(response.read())
        self.assertEqual(response.status, 200)
        client.request("POST", "/api/works", "{}", {"Content-Type": "application/json"})
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        client.request(
            "POST",
            "/api/works",
            "{}",
            {"Content-Type": "application/json", "X-Editor-Token": session["token"], "Origin": "https://example.org"},
        )
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        client.request("GET", "/data/studio.json")
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 404)
        client.request("GET", "/api/session", headers={"Host": "attacker.example"})
        response = client.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        client.request(
            "POST", "/api/works", "{}", {"Content-Type": "application/json", "X-Editor-Token": session["token"]}
        )
        response = client.getresponse()
        data = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertTrue(data["id"].startswith("work-"))
        self.assertEqual(len(self.editor.works()), 1)

    def test_reopening_external_revision_starts_fresh_without_losing_old_work(self):
        work = self.editor.new("a")
        work = self.editor.update(work["id"], dict(work, body="uncommitted text"))
        self.studio.add_revision(self.editor.state(), "a", "externally edited", "external")
        fresh = self.editor.new("a")
        self.assertNotEqual(fresh["id"], work["id"])
        self.assertEqual(fresh["body"], "externally edited")
        self.assertEqual(self.editor.work(work["id"])["body"], "uncommitted text")

    def test_branch_then_merge_keeps_historical_edges(self):
        first = self.commit(self.draft([self.source("a")]), True)
        second = self.commit(self.draft([self.source("a")]), True)
        before = copy.deepcopy(self.editor.state()["edges"])
        final = self.commit(self.draft([self.source(first["document_id"]), self.source(second["document_id"])]), True)
        state = self.editor.state()
        self.assertEqual(state["edges"][:2], before)
        self.assertEqual(genealogy(state, "q")["terminals"], ["b", final["document_id"]])

    def test_wrong_parent_question_and_hash_cannot_modify_studio(self):
        item = self.source("a", ("missing",))
        work = self.draft([item])
        before = self.studio.metadata.read_bytes()
        with self.assertRaises(ModelError):
            self.commit(work, True)
        self.assertEqual(before, self.studio.metadata.read_bytes())
        item["sha256"] = "0" * 64
        with self.assertRaises(Conflict):
            self.editor.update(work["id"], dict(work, selections=[item]))

    def test_idle_browser_connection_does_not_block_another_browser(self):
        server = Server(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        idle = socket.create_connection(("127.0.0.1", server.server_port))
        self.addCleanup(idle.close)
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        self.addCleanup(client.close)
        client.request("GET", "/")
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b"Stemma", response.read())
        client.request("GET", "/api/documents")
        response = client.getresponse()
        self.assertEqual(json.loads(response.read())["total"], 2)

    def test_component_returns_unselected_coparent_archived_nodes_and_exact_edges(self):
        work = self.commit(self.draft([self.source("a", archive=True), self.source("b", ("other",))]), True)
        before = self.studio.metadata.read_bytes()
        result = self.editor.components(["b", work["document_id"]])
        self.assertEqual(len(result["components"]), 1)
        component = result["components"][0]
        self.assertEqual({n["id"] for n in component["nodes"]}, {"a", "b", work["document_id"]})
        a = next(n for n in component["nodes"] if n["id"] == "a")
        self.assertTrue(a["archived"])
        self.assertFalse(a["selected"])
        self.assertIsNone(a["date"])
        self.assertEqual(len(component["edges"]), 2)
        self.assertEqual({e["parent_revision"] for e in component["edges"]}, {"r1"})
        self.assertEqual(self.studio.metadata.read_bytes(), before)

    def test_component_isolated_selection_and_proposal_opt_in(self):
        state = self.editor.state()
        state = self.studio.create_draft(
            state, "c", "proposed child", ["q"], "draft text", [{"parent": "a", "questions": ["q"]}], "proposed"
        )
        self.assertEqual(len(self.editor.components(["a", "b", "c"])["components"]), 3)
        groups = self.editor.components(["a", "b", "c"], True)["components"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["edges"][0]["state"], "proposed")
        self.assertEqual(self.editor.components([])["components"], [])
        with self.assertRaises(ModelError):
            self.editor.components(["unknown"])

    def test_initial_save_date_does_not_move_with_expression_revision(self):
        work = self.commit(self.draft())
        docid = work["document_id"]
        created = self.editor.components([docid])["components"][0]["nodes"][0]["date"]
        self.assertIsNotNone(created)
        work = self.editor.update(work["id"], dict(work, body="polished"))
        self.commit(work)
        node = self.editor.components([docid])["components"][0]["nodes"][0]
        self.assertEqual(node["date"], created)
        self.assertEqual(node["revision_count"], 2)

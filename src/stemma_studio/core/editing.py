"""Prepare editor changes as values before any snapshot or metadata is written."""

import copy

from ..locale import Message
from . import domain


def prepare(state, docid, title, revision, parents=None, questions=None, confirm=False, archive_parents=()):
    """Replace only a draft's proposals; confirmed history is never rewritten.

    Parent entries carry exact revisions selected by the author. Question records
    may be added, while existing identities and public settings remain unchanged.
    """
    result = copy.deepcopy(state)
    for qid, text in (questions or {}).items():
        domain._require(bool(text.strip()), Message("error.editing.question_blank"))
        if qid in result["questions"]:
            domain._require(result["questions"][qid]["text"] == text, Message("error.editing.question_overwrite"))
        else:
            result["questions"][qid] = {"text": text, "public": False, "representatives": []}
    if docid not in result["documents"]:
        result = domain.create_draft(result, docid, title, [], revision, [])
    else:
        doc = result["documents"][docid]
        domain._require(doc["kind"] == "original", Message("error.editing.original_only"))
        domain._require(not doc["archived"], Message("error.editing.restore_first"))
        if revision is not None:
            result = domain.add_revision(result, docid, revision)
        result["documents"][docid]["title"] = title
    doc = result["documents"][docid]
    if parents is not None:
        domain._require(doc["state"] == "draft", Message("error.editing.confirmed_succession"))
        result["edges"] = [e for e in result["edges"] if e["child"] != docid]
        for parent in parents:
            pid, rid = parent["parent"], parent["revision"]
            domain._require(pid in result["documents"], Message("error.editing.missing_source"))
            source = result["documents"][pid]
            domain._require(not source["archived"], Message("error.editing.restore_parent"))
            domain._require(source["state"] == "confirmed", Message("error.editing.parent_unconfirmed"))
            domain._require(rid in [r["id"] for r in source["revisions"]], Message("error.editing.missing_revision"))
            scopes = parent["questions"]
            domain._require(bool(scopes), Message("error.editing.no_question"))
            domain._require(bool(parent["change_note"].strip()), Message("error.editing.no_note"))
            for endpoint in (source, doc):
                endpoint["questions"] = list(dict.fromkeys(endpoint["questions"] + scopes))
            result["edges"].append(
                {
                    "id": "edge-" + domain.digest(pid + "|" + docid)[:16],
                    "parent": pid,
                    "parent_revision": rid,
                    "child": docid,
                    "child_revision": doc["current_revision"],
                    "questions": list(scopes),
                    "change_note": parent["change_note"],
                    "state": "proposed",
                    "public": False,
                }
            )
    domain.validate(result)
    if confirm:
        result = domain.confirm(result, docid, archive_parents)
    else:
        domain._require(not archive_parents, Message("error.editing.archive_at_confirm"))
    return result

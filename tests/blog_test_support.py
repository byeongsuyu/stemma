"""Explicit bilingual approval helpers for synthetic regression fixtures."""

import copy

from stemma_studio.core.blog import fingerprint, pair_input


def reviewed_pair(app, state, docid, revision, prefix=""):
    """Prepare both languages explicitly instead of using revision-only publishing."""
    app.save(state)
    for lang in ("ko", "en"):
        vid = prefix + lang + "-" + revision
        state = app.save_variant(
            state,
            docid,
            vid,
            revision,
            lang,
            lang + " fixture title",
            body=None if lang == "ko" else "English fixture " + revision,
        )
        state = app.review_variant(state, docid, vid, fingerprint(state["documents"][docid]["language_variants"][vid]))
    pid = prefix + "pair-" + revision
    payload = {
        "base_revision": revision,
        "variants": {lang: prefix + lang + "-" + revision for lang in ("ko", "en")},
        "attachments": [],
    }
    state = app.approve_pair(
        state, docid, pid, revision, payload["variants"], fingerprint(pair_input(state["documents"][docid], payload))
    )
    return app.select_publication(state, docid, pid)


def legacy_v3(state):
    """Build authentic old-schema input for migration tests only."""
    result = copy.deepcopy(state)
    result["schema_version"] = 3
    del result["blog"]
    for doc in result["documents"].values():
        publication = doc["publication"]
        doc["publication"] = publication["legacy_v3"] or {"published": False, "revision": None}
        for key in ("language_variants", "variant_reviews", "publication_pairs"):
            del doc[key]
    return result

# Design

The rules the model enforces, and why they are what they are. This is the
condensed version of a longer internal design note; it covers the decisions a
reader of the code needs, not the full history of how they were reached.

## The problem

Most writing tools treat a post as a standalone artifact. If you write by
returning to things you wrote years ago — rereading, disagreeing with yourself,
starting again from a better question — that model loses the only part that
mattered: the relationship between the old piece and the new one.

Stemma makes that relationship data.

## Documents, revisions, questions

A **document** is a unit of thought with a stable ID. A **revision** is one
particular body text of that document. Revisions are immutable snapshots;
editing writes a new file and never overwrites an old one. Autosaves are
working state, not revisions, and never become nodes in the graph.

A **question** is the scope of a succession — “Is market reward a measure of
ability?”, not a broad tag like “economics”. A question's wording and its ID
are separate: rephrasing the same question keeps the ID, while changing what is
being asked is a new question. Stemma never infers this and never moves
existing lineage on its own.

A document may take part in several questions. Titles and question IDs are
separate data, so renaming a document never changes its lineage. Imported
material keeps its original title; where there is none, the generated display
label is marked as generated.

## Succession

`A → B [Q]` is the author's declaration that, on question Q, B reviewed A and
carried it forward, and that future exploration should start from B. It does
**not** mean agreement or logical implication — a piece that contradicts or
retracts an earlier position still succeeds it.

An edge records the parent document and revision, the child document and
revision, one or more questions, and a free-text note about what changed. There
is no required taxonomy of change types, because extension, correction,
reversal and synthesis overlap in practice.

Rules the model enforces:

- The whole lineage is a directed acyclic graph. Multiple parents and multiple
  children are allowed; cycles are refused even across combined questions. To
  return to an earlier position, write a new document.
- One edge per parent/child pair, whatever the questions or revisions. Several
  questions go in that edge's `questions` list, so adding finer questions never
  multiplies the connections between documents.
- No self-edges.
- Publication dates and word similarity never establish a succession by
  themselves. A parent can be recognised long after the fact, so date order is
  not a substitute for validating the graph.

Citing, quoting or consulting something while writing is not succession. The
model distinguishes “I referred to this” from “I now start again from here”.

## Roots, terminals and representatives

Per question, the graph is computed from confirmed documents and confirmed
edges only; drafts are excluded. A **root** has no incoming edges, a
**terminal** no outgoing ones, and an isolated document is both. A root is the
start of the recorded lineage, not a claim about the first thought.

There can be several terminals, and a document that is superseded on one
question may still be terminal on another. Roots and terminals are computed,
never stored.

A **representative** is the author's designated current position on a question.
There may be none, one, or several. Being terminal does not make a document
representative, and representation is independent of publication — a private
document can represent a question. When a representative gains a successor, it
is flagged for review rather than silently replaced.

## Retirement

`archived` is an explicit declaration that a document will not be used as
material for new thinking. It is not a judgement that the text is wrong,
withdrawn or fully superseded in content. It defaults to false, is never
inferred from succession, and applies to the whole document rather than per
question.

Retiring a document preserves everything: the source, every revision, existing
edges and question participation. It does not move representatives or
unpublish anything, and the public output never exposes it.

To use a retired document as a new succession parent — or to confirm a pending
succession that has one as a parent — restore it first. Storing a new revision
does not restore it.

Retired documents are excluded from the publication list and from search, and
publishing one anew is refused: its argument was carried forward, so publish
the successor instead. One already live can still be taken down.

## Editing versus writing a new document

Typo fixes, Markdown repairs and tightening prose are new revisions of the same
document. Existing edges keep pointing at the revisions they were made against.

Editing several fragments into one independent piece that you will write from
next is a **new document with several parents**. Adding a new claim is not
required for succession; a collection that merely displays old material is not
succession. Changes of position, argument or answer are recorded as new
documents, and nothing is classified automatically by how much text changed.

Imported archive documents are never revised in place. A cleaned-up version
becomes a new Stemma document, so the original and its provenance survive.

## Bilingual publication

Korean and English are two expressions of one document. A translation never
adds a node or an edge, and is never inserted as the next revision. Stemma
stores immutable language variants that reference a base revision, each with
its own title, summary, hash and review state.

One of the two is the language the document is written in, and that variant's
body *is* the base revision; the other is a translation with a body of its own.
Which is which is recorded in the variant, not assumed: an author may write in
either language, and says which in the blog settings. A document keeps the side
it was first given — by a stored variant, or failing that by a translation draft
already begun — so changing the setting never turns round a post in progress. A
data root that has never published and never said is asked rather than guessed
at, because the answer is written into immutable records.

Genealogy wording — a question, a change note — has a language of its own too,
and it need not be the post's: an English post can carry a question first asked
in Korean. Its label keeps the wording as written under that language, and a
translation under the other; since the label is shared by every post that shows
it, a save that would file the original under the wrong language is refused.

Publishing requires a reviewed Korean **and** English title and body for the
same base revision. Reading the preview and confirming *is* the review: the
variants, their review records and the pair are recorded together at that
moment, and previewing alone records nothing. A preview is the review of the
input that produced it, so if the input changes the preview is void and must be
made again.

The pair is fixed and updated as a unit. While one side is being revised, the
existing published pair stays live. Changing the base revision does not
re-attach translations automatically. This policy lives in Stemma; the
`stemma_graph` core knows nothing about languages or publication.

## Preservation

The source archive is read-only: Stemma reads committed Git objects and records
provenance and integrity by ID, commit, blob and SHA-256. Uncommitted material
is not imported. Titles and filenames are not identifiers, so moving a file
with the same ID and content only updates the recorded path. See
[importing.md](importing.md).

New material arrives with no questions, no succession, no representation and
unpublished. `confirmed` on an imported document means it is usable material,
not an endorsement. Instructions found inside archived text are data, not
directions to the tool.

Saving writes content copies first and metadata last, so a failed retry reuses
the same copies rather than overwriting different content. This is built for a
single local author: there is no multi-file transaction, no concurrent writing
and no general rollback.

## Module boundaries

| Area | Responsibility and dependencies |
|---|---|
| `stemma_graph` | Immutable lineage values, validation and queries. Standard library only. |
| `stemma_studio.core` | Writing, revisions, representation, storage, archive sync and publication policy. Depends on `stemma_graph`. |
| `stemma_studio.blog` | Reader's site rendering, preview, publication admin, deployment. Depends on the core. |
| `stemma_studio.editor` | Local writing desk; mounts the blog's publication screens. May depend on both. |

Graph changes return new immutable instances. `stemma_graph` carries no
filesystem, publication or UI knowledge, and no `sys.path` manipulation;
`stemma_studio.core` is where storage and publication policy live. Interface code
stays out of the graph package. The installation path and the data root are
independent, and no personal data is in either wheel.
`tests/test_package_layout.py` enforces the direction.

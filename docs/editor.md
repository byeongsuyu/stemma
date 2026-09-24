# The editor

The writing desk at <http://127.0.0.1:8787>. Three panes: find material, read
what you picked, write. The interface speaks Korean or English; the switch is in
the top bar, and the choice is remembered for the data root.

```sh
stemma editor                 # or: stemma --root /path editor
```

## The flow

1. **Find.** Search titles and bodies. Every whitespace-separated term must
   appear; title matches come first, and Korean partial words match. With no
   query, material is ordered by original or first-saved time, compared in UTC.
   Reworking a document's wording does not move it up the list.
2. **Read.** Click a title for the full source with its provenance, revisions
   and immediate parents and successors. Tick several items to keep them; the
   middle pane becomes tabs you can move through with arrow keys or Home/End.
   Changing the search keeps your selection, which stays pinned below the
   finder. Each pane scrolls on its own.
3. **Write.** Title and body, in Markdown. Importing a source's text is an
   explicit action and is recorded as a reference — selecting and copying is
   never succession by itself.
4. **Autosave.** Pausing stores working state. You can continue from the
   manuscript tabs or after a refresh. Closing a tab deletes only that
   autosaved working file; stored revisions and lineage remain. **Store
   revision** is what creates a new immutable body — autosave never creates a
   revision or a lineage edge.
5. **Review succession.** For each source, choose *referred to* or *carried
   forward*. Per parent, pick existing questions or write new ones, one per
   line, and describe what changed. Retiring a parent is off by default and
   applies across all questions.
6. **Confirm.** The final body and relationships are validated and confirmed.
   This does not publish anything. An already-confirmed document is only
   reworded by storing a new revision; a change of position or a merge becomes
   a new document.
7. **Translate and publish** hands the same document and revision to the
   publication screen. See [publishing.md](publishing.md).

Imported archive material has no edit button. Open a Stemma document in the
source pane and choose to rework it, which opens that document's working file.
If it changed elsewhere in the meantime, the older working file is preserved
and a new one is opened against the current document. Retired documents are
read in a separate view, or explicitly restored.

On narrow screens the three panes become tabs; on a desktop the source pane
folds away. HTML inside sources is shown as text, and external images and links
are never fetched automatically.

## Pictures and files

**Add pictures or files** in the writing tools attaches one or many files at once. Each
is stored under its own content hash in `data/assets/`, and a Markdown link is
written at the cursor. The name in the link carries a short piece of that hash —
`images/고양이-3f9a21b0.png` — which is what lets two pictures with the same
file name live in one post without any renaming, and makes the same picture
attached twice resolve to a single stored file.

PNG, JPEG, GIF, WebP, PDF and plain text are accepted: what the published site
can carry. Pictures go in `images/` and are written into the body as images;
anything else goes in `files/` and is written as a link.
The first bytes of the file have to match the name it carries, so a renamed file
is refused here rather than becoming a broken image on a reader's page. The
limit is 8MB a picture. Large batches are sent in groups: an upload request may
carry 12MB of encoded bytes, and every other editor request 4MB, so the encoded
size of a batch is what the grouping keeps under the cap, not the file size.

The bytes are stored first and the record of them is sent with the next
autosave, so the link in the manuscript and the record of what it points at are
saved together and cannot disagree. Nothing the browser sends back about an
attachment is trusted: every part of the record is rebuilt from the stored
picture's own hash and compared before it is kept.

Attachments accumulate. Deleting a link from the body does not delete the
picture, and a published page carries only the files its text actually refers
to — one attached and never linked is stored, but never published and never
named in the public payload.

**Preview text shows the pictures.** They are served from the data root for the
duration of the preview, and only this draft's own attachments are reachable:
the preview is told what to resolve from the saved work, never from the request.

## The genealogy map

**View the genealogy of the selected documents** opens `/genealogy` in a new
tab, showing the entire weakly connected component the selection belongs to —
following edges in both directions, so other parents that merged in and other
successors that branched off are included. Selections in the same component are
drawn once. Retired documents remain; an unconnected selection is shown as its
own lineage.

It shows confirmed successions across all questions by default; an option adds
proposed edges as dashed lines. The selection is fixed at what the editor
handed over — to change it, reopen from the editor.

Documents are ordered top to bottom by original date or first Stemma save, in
columns by succession depth. Spacing is not proportional to elapsed time, and
older Stemma documents without a date sit at the bottom as undated. Dates are
never guessed for existing manuscripts, and reworking does not move them.

That is the one date a document has, and every screen shows it: the shelf, the
source reader and the map all say the same thing about the same document, and
the detail views name which date it is — **Date in the source** for one recorded
in the source, **First saved in Studio** for the first save here, **Date
unknown** for neither.
Editing a document later never changes it.

Cards open the current body; edges open the questions, the change note and the
parent and child revisions as they were. The map is read-only.

## Storage and recovery

| Path | What it holds |
|---|---|
| `data/workspaces/work-<UUID>.json` | Mutable working file: title, body, the exact selected revisions, review settings. A monotonic `version` rejects stale saves from the same server. |
| `data/revisions/<id>/rN.md` | Explicitly stored immutable revisions. Never overwritten. |
| `data/studio.json` | Documents, lineage and questions. `editor_sources` is a private record of what was referred to; `editor_receipt` marks a completed save whose working-file update failed, so it can be retried. |
| Browser `localStorage` | A temporary backup of input that never reached the server. Recover it as a separate working file, or download it. It never overwrites newer server-side text automatically. |

Working files belong in your data root's version control along with everything
else. If a working file is stale or conflicts with an outside edit, copy your
text aside and reopen the current document; if the server restarted, refresh.

There is no multi-file transaction, no support for several servers or CLI
processes writing at once, and no general rollback.

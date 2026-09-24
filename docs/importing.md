# Importing your existing writing

There are two ways in, and most people want the first.

| | Use it when | Needs Git? |
|---|---|---|
| **Import screen** | Your writing is a folder of Markdown files with pictures | No |
| **`stemma sync-archive`** | Your writing lives in a Git repository you keep updating | Yes |

Both are **read-only and append-only**: your files are never modified, moved or
deleted, and nothing already imported is overwritten.

## Importing a folder

Open **Import** in the top bar, give it the absolute path of the folder your
writing lives in, and press **Scan**. Nothing is saved until you press the
import button — the scan only reports what would happen.

Your folder can look however it already looks:

```
my-old-blog/
  posts/
    2009-some-post.md      ![](images/cat.png)
    images/cat.png
  shared/logo.png          referenced from posts as ../shared/logo.png
  고양이.md
```

**Picture links are never rewritten.** A picture is recorded at the path it
occupies relative to the post that references it, so `![](images/cat.png)`,
`![](./images/cat.png)` and `![](../shared/logo.png)` all keep working exactly
as written. This is why the importer takes a *folder* and not a list of files:
the folder's shape is what makes the links resolve.

### What it reports before importing anything

- **New pieces to import** — with the identifier, title and date it worked out.
- **Needs attention** — anything that needs you:
  - *Picture missing*: a link points at a picture that is nowhere in the folder. The
    post is still imported and its text is left alone; only the picture is
    missing. Put the picture where the post says it is and scan the folder
    again — it is attached then, without the post being imported twice.
  - *Picture outside the folder*: a link such as `../../assets/cat.png` points above the
    folder you chose. The picture probably exists — it is just outside what you
    asked to import. Choose the parent folder instead and the picture comes with
    it. This is the usual result of pointing the importer at one subfolder of an
    archive whose pictures sit beside it rather than inside it. A link that
    leaves the folder through a symlink is reported the same way: the import
    reads only what is really inside the folder you chose.
  - *Duplicate ID*: two files would get the same identifier. Change the ID rule, or
    give one of them an `id` in its frontmatter.
  - *Already here, with different content*: this identifier was imported before with different
    bytes. What you imported is never overwritten. An imported document cannot
    be revised in place either, so the newer text becomes a **new document**
    that succeeds it, written in the editor. The original keeps its provenance.
- **Already imported and unchanged** — re-scanning the same folder is safe and changes
  nothing about the writing.
- **Missing pictures found** — posts that are already imported and unchanged,
  whose missing pictures are now in the folder. Confirming attaches those
  pictures; the text of the post is not touched and no document is created.
  This is the one thing a re-scan of an unchanged folder can still do, and it
  is why a folder with nothing new in it may still offer a button to press.

What you confirm is the plan you read, not the folder as it stands at that
moment. Changing the folder or the ID rule clears the result and asks for
another look, and a file edited between the scan and the confirmation is
imported as it was reviewed rather than as it now reads. Import that folder
again to pick the newer text up.
- **Pictures no piece uses** — pictures no post links to. They are not
  imported. A picture an imported post already uses is not counted here.
- **Links to outside addresses** — `https://` images. Left exactly as they are.

Files with problems are skipped; everything else is imported. Fix them and scan
again.

### Identifiers

Every document needs a stable identifier. In order of preference:

1. An `id` in the file's frontmatter, if there is one.
2. Otherwise, derived from the file path (`posts/2009/cat.md` →
   `posts-2009-cat`) or from the file name alone (`cat`), whichever rule you
   pick on the screen.
3. A name with no ASCII in it — `고양이.md` — has no identifier to derive, so it
   gets a stable digest instead (`doc-fba29df84e`). It is the same on every
   re-scan. The *title* still reads properly; only the internal identifier is a
   digest. Add an `id:` to the frontmatter if you want to choose it.

### Titles and dates

A `title` in the frontmatter is used as written. Without one, the first heading
in the body becomes the title; failing that, Stemma builds a display label from
the date and the opening words (`2011-09-27 · 소셜 네트워크 이론이…`) and records
that it generated it, which the editor shows as a *generated display title*.

Frontmatter written by an exporter often says `title: null` or `date: ~` for a
post that never had one. Those mean absent, not the word "null" — the same rule
the Git route uses, so one archive reads alike whichever route brings it in.

### What is kept

Each imported post becomes a confirmed document with one revision, plus two
preserved copies in your data root: the complete original file byte for byte in
`data/imports/<id>.md`, and its body in `data/revisions/<id>/r1.md`. Pictures
are stored by content hash in `data/assets/`, so the same picture used by ten
posts is stored once.

Imported posts start with no questions and no succession. Connecting them to
each other, and to new writing, is what the editor is for.

## Importing from a Git archive

`stemma sync-archive` imports from a Git repository in one particular layout.
Use the folder screen unless you specifically want this. The rest of this
document is that contract; nothing else about your archive matters.

The import is **read-only and append-only**. Stemma runs only `git` read
commands against your archive — it never commits, checks out or modifies
anything there — and it refuses to change or delete anything it has already
imported.

### Repository layout

```
your-archive/
  .git/
  corpus/              documents, as Markdown files
    2009/some-post.md
    notes/another.md
  assets/              images and attachments referenced by documents
    0f1e2d3c....png
```

- Only `corpus/**/*.md` and `assets/**` are read. Everything else in the
  repository is ignored.
- Files must be **committed**. Working-tree changes are invisible to the
  import, which reads a single resolved `HEAD` commit so that documents and
  assets always come from the same snapshot.
- Subdirectories under `corpus/` are free-form; documents are identified by the
  `id` in their frontmatter, not by their path. Moving a file later is
  recorded, not treated as a new document.
- Regular files only. Symbolic links and submodules are rejected.

### Document format

Each document is a Markdown file that begins with a frontmatter block delimited
by `---` lines:

```markdown
---
id: 2009-some-post
date: 2009-04-11
title: "On reading again"
assets:
  - path: assets/0f1e2d3c4b5a69788796a5b4c3d2e1f0.png
---

The body of the document starts here.
```

Only `id` is required. Any other keys you keep — where the text came from, how
you classified it, who wrote it — are preserved untouched; see below.

### Fields

Only four things are interpreted:

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Stable identifier, `[A-Za-z0-9_-]+`. This is the document's identity across imports; never reuse or change one. |
| `date` | no | The original date. Used for display and ordering; `null` means unknown. |
| `title` | no | If absent, Stemma generates a display label from the date and first line, and records that it did. |
| `assets` | no | A list of `- path:` entries, each starting with `assets/`. |

**Everything else you write in the frontmatter is kept but not interpreted.**
The complete original file is preserved byte for byte as an immutable snapshot
in `data/imports/<id>.md`, and the parsed frontmatter is retained alongside the
document as an inert provenance record. So fields like `source`, `kind`,
`status`, `visibility`, `original_author`, `original_url` or `duplicate_of` are
safe to include — nothing in the tool branches on them, and nothing is lost if
you do.

The practical consequence: **you do not need to shape your archive to a rich
schema.** An `id` and a body are enough. Add `date` and `title` when you have
them.

### The frontmatter parser is not YAML

It reads a deliberately small scalar subset, so that importing an archive can
never execute anything:

- `null`, `~` and empty mean *no value*.
- Double-quoted values are parsed as JSON strings, so `"\n"` and escapes work.
  Literal control characters inside them are preserved.
- Single-quoted values are literal, with `''` meaning one `'`.
- Anything else is taken as plain text up to the end of the line.
- Multi-line scalars (`|` and `>`) are **rejected** with an explicit error
  rather than silently mis-parsed.

Each field is matched at the start of a line, so a key must not be indented.

### Assets

`assets:` is a block of `- path:` items. Each path must start with `assets/`
and must not contain `..`. If a referenced asset is not committed, the import
does not fail: it records a warning (`asset_not_committed`) and continues, so a
missing image never blocks the rest of your archive.

Asset bytes are copied into your Stemma data root. Links inside document bodies
are preserved as written, so the reading screens resolve them through the
recorded asset mapping rather than by rewriting your text.

### What an import produces

Each new document becomes a confirmed, imported document with one revision
(`r1`), plus two preserved copies in your data root:

- `data/imports/<id>.md` — the complete original file, byte for byte
- `data/revisions/<id>/r1.md` — the body, with frontmatter removed

Imported documents start with no questions and no succession edges. Connecting
them to each other, and to new writing, is what the editor is for.

### Running it

```sh
stemma sync-archive --archive /absolute/path/to/your-archive --dry-run
stemma sync-archive --archive /absolute/path/to/your-archive
```

The first successful sync remembers the path, so later runs need only
`sync-archive`. Pointing an existing data root at a *different* archive is
refused, because two archives can use the same `id` for different writing.

`--dry-run` reports what would happen and writes nothing. The report tells you:

| Field | Meaning |
|---|---|
| `commit` | The archive commit that was read |
| `added` | Document IDs imported by this run |
| `unchanged` | Documents already imported, with matching content |
| `moved` | Documents whose file path changed in the archive |
| `conflicts` | Documents that could not be imported (see below) |
| `warnings` | Non-blocking problems, such as an uncommitted asset |
| `status` | `up_to_date` when the archive commit has not changed |

### Conflicts

A conflict blocks the whole batch — not just the document it was found on — and
`sync-archive` exits non-zero having imported nothing. `unchanged` in the report
is a count, not a list:

- `duplicate_id` — two committed files claim the same `id`.
- `existing_content_changed` — a document already imported has different bytes
  in the archive now. Stemma preserves what it imported and refuses to
  overwrite it. Resolve it deliberately: decide which version is the real one.
  Writing a successor document in the editor records the newer text, but it
  does not unblock this ID — the archive and what was imported under that ID
  still have to be reconciled, by restoring the archived bytes or by retiring
  the identifier.
- `existing_document_missing` and `existing_asset_missing` or
  `existing_asset_changed` — something that was imported before is gone from
  the archive, or its bytes changed underneath. These block the batch too.
- A parse failure, such as missing frontmatter boundaries, an unsafe `id`, an
  unsafe asset path, or a multi-line scalar. The reason is reported per path.

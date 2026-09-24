# Moving an existing data root in

If you already have writing in a Stemma data root — from an older checkout, a
private version of this project, or another machine — you do not import it. You
point the installed tool at the folder you already have.

Importing is for Markdown that was never in Stemma. It reads `.md` files, and
your succession edges, questions, translations, publication pairs and release
history are not `.md` files. Pointing `--root` at the existing folder keeps all
of it; importing the same writing would keep the text and silently lose the rest.
See [importing.md](importing.md) for the case where importing *is* what you want.

## The whole state is `data/`

Everything Stemma knows lives under one folder:

```
data/
    studio.json        documents, revisions, succession edges, questions, releases
    imports/           preserved originals, byte for byte
    revisions/         every stored revision
    assets/            pictures and files, by content hash
    translations/      reviewed bilingual bodies
    blog/              site.json, the deploy destination, release records
    workspaces/        drafts you have open
```

Everything you have written is in there — not the code, not a virtualenv, not
the folder it used to sit in. So moving your writing is a copy and a flag:

```sh
cp -R /old/place/data /new/place/data
stemma --root /new/place editor
```

`--root` names the folder *containing* `data/`, not `data/` itself. Leave it out
and the current directory is the root.

Check it arrived intact before you do anything else:

```sh
stemma --root /new/place --no-sync validate
```

That reads every document, recomputes each stored hash against the actual bytes,
and rebuilds the genealogy. If it prints counts, the move is sound. `--no-sync`
keeps the check strictly read-only: without it, `validate` also reaches for the
Git archive and may save newly imported writing, which is not what you want
from a verification step.

Two things live outside `data/` and do not travel with it:

- **The paths you configured** — your Git archive and your deployment
  destination are recorded in `data/`, but what they point at is not. Check
  both after moving, and reconfigure them if the machine's layout differs.
- **In-flight pull requests.** A homepage PR receipt lives in that checkout's
  `.git/stemma-pr/`, not in `data/`. Move or re-clone the checkout to pick up a
  release whose PR is still open; a release whose checkout is gone simply shows
  without its PR detail.

## Two things to do after moving, before deploying

### 1. Set your blog's identity

If your writing predates `data/blog/site.json` — an older version may have had
the blog's name in its code rather than in a setting — Stemma has nothing to go
on and will publish under placeholder names (`나의 블로그` and `지은이` on the
Korean pages, `My Blog` and `Author` on the English ones). Deploying
in that state rewrites your whole live site with the placeholders.

Open **Settings** and fill in **Blog settings** first: the language you write
in, the name, author, byline and intro in both languages, and the licence your
writing carries. A root that has published before is already taken to write in
the language its posts came from, so saving the settings only records that. If your site is already
live, copy the values off it so the pages stay identical. See
[site-settings.md](site-settings.md).

### 2. Finish any deployment left in flight

A release that was sent but never confirmed stays *in progress*. That is not damage —
Stemma does not record a deployment as successful until it has checked that the
site actually serves it, so an interrupted session leaves the record open.

Reading and writing are unaffected. Only deployment is held:

| | With a deployment in flight |
|---|---|
| Reading, searching, opening posts | works |
| Writing, succeeding, revising | works |
| Importing | works |
| Saving blog settings | works |
| **Starting a new deployment** | held |
| **Changing the deploy destination** | held |

On the site screen, press **Check deployment**. If the release did land, it is
recorded as successful and the hold clears. If it truly never landed,
**Deployment recovery** → **Record the interruption and prepare a retry** marks it failed so you can send the same frozen release again.

Check the live site before assuming: a pull request that merged after you closed
the tool is live even though the record still says *in progress*.

## Confirming the move reproduces your site

The most direct check is to build the site locally and compare it with what is
already published.

1. In **Settings** → **Deployment destination**, choose to write files to a
   local folder, give it an empty folder, and set the
   base path to match where the site is served (`/` or `/blog/`).
2. On the site screen, deploy. The folder fills immediately — no account, no
   waiting.
3. Compare the generated pages with your live ones.

Expect differences that are not data loss: timestamps move because a new release
was made, and stylesheets differ if the live site was built from older code. A
difference in a post's *text* means a revision was selected that has not been
deployed yet, which the site screen will already be telling you about.

Switching the destination back afterwards sends the whole site rather than a
difference, so this costs you nothing.

## Keeping the old copy around

Two things worth knowing if the old checkout stays on disk:

- **Do not run both against the same `data/`.** Stemma assumes a single local
  author and one write lock. An older version of the code sharing the folder can
  interleave writes with it.
- **If the old repository tracked `data/` in git**, every post you write now
  appears as a change in that repository. That is harmless, but if you would
  rather keep writing separate from code history, move `data/` somewhere of its
  own and point `--root` there.

## Upgrading the stored format

Stemma reads schema version 4 and converts older roots on the way in, preserving
the complete original JSON before the first save in the new format (see
`core/migrations.py`). You do not run a migration command; opening the root is
enough. A root Stemma cannot read is refused rather than half-converted.

# Publishing

How a confirmed document becomes a page on a live site. The short version:
write in the language you publish from, add the translation into the other,
confirm the pair, then deploy everything confirmed since the last release.

## Before the first post

Set your blog's name, byline, the language you write in and the licence on your
writing on the **Settings** screen, under **Blog settings**. Until you do, pages
publish under placeholder names and reserve all rights by default, and a data
root that has never published cannot publish until it knows which language you
write in. See [site-settings.md](site-settings.md).

Settings are a site change like any other: after saving they appear under
*what this deployment changes* and reach readers on the next deployment.

## The screens

The editor and the publication screens are one local server, sharing one write
lock. The site screen is what you check each time you publish; the settings
screen is what you decide once:

| Screen | URL | What it is for |
|---|---|---|
| Editor | `/` | Writing, revisions, succession review |
| Publication | `/publish/` | Per-post: the translation, public titles, series membership, genealogy wording |
| Site | `/publish/?view=site` | What this deployment changes, series, deploying, release history |
| Settings | `/publish/?view=settings` | The blog's name, byline, writing language and licence, and where it deploys to |

They share a top bar showing the name, the three screens, and a count of local
changes not yet deployed.

To run the publication screens alone, against your own data but unable to write
to it:

```sh
stemma --root . blog-admin --read-only --port 8769
```

## From a draft to a confirmed pair

1. Write and confirm the document in the editor, then store a revision.
   Unsaved text is refused: you are asked to store the revision first.
2. **Translate and publish** carries the same document and revision to the
   publication screen. The revision is the original, read-only; paste the
   translation's title, summary and body, or import a UTF-8 Markdown file.
   Which language is the original follows the blog settings — see
   [Which side is the original](#which-side-is-the-original).
3. Preview. The preview renders with the same renderer readers get, so what you
   check is what ships.
4. **Confirm.** Confirming after the preview *is* the review — there is no
   separate "bilingual body reviewed" step. The variants, their review records
   and the pair are all written at that moment.

Previewing on its own records nothing. A preview is the review of the exact
input that produced it, so changing the input voids it, including a restore
from the browser's draft recovery.

While you revise one side, the currently published pair stays live. For a new
base revision the previous translation is offered as a starting point, but is
not treated as reviewed for the new revision.

### Which side is the original

You write in Korean and translate into English, or write in English and
translate into Korean; the blog settings say which. A post keeps the side it
was given: once it has a stored variant, or a translation draft you have begun,
changing the setting does not turn it round. A data root published before the
setting existed is taken to write in the language its posts came from. A data
root that has published nothing and has not been told is asked on the post
screen, and nothing is saved until you choose, because the choice is written
into records that never change.

A post's address is made from its English title either way.

To change a live post, edit and confirm it directly. Withdrawing means taking
down something that was live, not a step on the way to editing it.

## What this deployment changes

The site screen compares the currently deployed public JSON against the
prospective JSON built from your local selections, ignoring publication times,
and groups the result by **the decision that caused it**:

- A **post row** gathers one document's decision: new, edited or withdrawn, the
  revision change (`r3 → r4`), and detail lines for the body, the genealogy
  links, series membership and genealogy wording — plus the consequences, such
  as a series disappearing when its last published post leaves, or a connected
  post's genealogy picture changing.
- A **wording row** is a genealogy wording change with no post change to
  attach it to; it names the post whose genealogy shows it.
- A **site setting row** is a series name, summary or order change, or the home
  ordering.

Each row's **✕** reverts that item to the live site's state, telling you what
will be reverted first. Immutable records are never erased by this. Rows are
hidden while a pull request is in flight.

Whether something changed is judged by the files that would be deployed, not
only by the JSON — a change to CSS, scripts, fonts or the 404 page alone is
deployable and shows as a "site appearance" row. If the files match the live
site, no release is built, and the server refuses one.

## Deploying

A release goes to one **destination**, chosen on the **Settings** screen under
**Deployment destination**. Deployment never force-pushes and never publishes anything you have not
confirmed.

### A local folder (default)

Writes the finished static site into a folder you name. No account, no GitHub,
no `gh`, nothing to wait for — the release is delivered the moment every frozen
byte is verified back off the disk.

That folder is then yours to move: drag it into any static host, `rsync` it to
a server, sync it to an object store, or copy it to a USB stick. A folder of
static files is what every host consumes, which is the point — the tool does
not tie your writing to one service.

Two settings:

- **Folder to write to** — an absolute path. It may not sit inside your Stemma data
  root, your archive or the installed code.
- **Site base path** — `/` if the site lives at the root of its domain, or
  `/blog/` if it will be served under a subpath. This has to match where the
  site actually ends up, because it is baked into every link.

### Reading a release before it goes out

Every release is frozen locally before it is sent anywhere, so it can be read here
first — **Preview** on the site screen opens it in a new tab, in either mode. For a
pull request that is the point: the page you read is what merging will publish, so the
decision to merge can be made from the writing rather than from a diff. For a folder it
answers the same question before anyone relies on the files.

The preview is rendered from the release's own frozen snapshot at a local address, since
a published page links its assets by the path they will have on the site and those
cannot resolve here. If the site's name, licence or design has changed since the release
was frozen, the screen says so rather than showing today's design over that release's
writing.

A folder you have already exported can also be opened on its own:

```sh
stemma preview --folder /path/to/the/folder
```

That checks every file against the `.stemma-release.json` receipt, says whether the
folder still matches it, and serves the folder so the stylesheet and pictures resolve —
which opening `index.html` as a file cannot do.

Safety rules, so a wrong path cannot destroy anything:

- A file this tool never wrote is never overwritten. Publishing into a folder
  that already holds something else is refused, naming what clashed.
- Files unrelated to the site — a `CNAME`, a `.git`, your own notes — are left
  alone.
- Pages you withdraw are deleted on the next release, but only ones a previous
  release wrote, tracked in a `.stemma-release.json` receipt.
- Every path is resolved inside the destination before anything is written. A
  symlink anywhere along the way — the folder itself, a folder below it, or a
  published page replaced by one — stops the release. Nothing outside the folder
  you chose is written to or deleted, and a link is never followed out of it.
  Each file is written through a temporary name beside it, and that name is
  checked the same way: anything already sitting there, link or file, stops the
  release rather than being written through and carried off by the move.
  A retry uses a fresh temporary name. A hard crash can leave a temporary sibling
  behind; it is left untouched because a failed attempt record alone cannot prove
  that the attempt created it. Such leftovers do not block a retry.
- An attempt that fails part way can be retried with the same release. It
  recognises the files it already wrote and finishes them; a file it did not
  write still stops the retry, as it would the first time.
- Every published byte is read back and compared to the frozen release. A
  mismatch fails the attempt rather than reporting success.

### A GitHub Pages pull request

Opens a pull request against a Pages repository you control, adding to `/blog/`
there, so you see the diff before it goes live.

Configure it once with the local clone folder and the Pages branch. The
repository is read from the checkout's GitHub `origin`. The target may not
overlap your Stemma data root, your archive or the installed code.

1. Confirm every post you want in this release, then **Open a deployment pull
   request**. The
   release is frozen, the files are generated and verified, one branch is
   pushed and a pull request opened. With nothing to deploy the button is
   disabled.
2. Review and merge it on GitHub. Then use **Check deployment** to check that Pages
   built the matching commit. Before the merge, or while the build runs, it
   stays in progress.

A pull request in flight blocks a new deployment and shows you separately what
you have confirmed since. Writing and translating continue regardless.

Your homepage checkout is left untouched: generated files go to a worktree
under `.git/stemma-worktrees/<release>/blog/`, and only `blog/` is
committed there. Unsent local commits and unknown pre-existing blog files are
never sent. Settings live in `data/blog/homepage.json`; recovery information
for the pull request lives in the homepage's `.git/stemma-pr/`.

Requires the GitHub CLI: install `gh` and run `gh auth login`. Pages must be
set to *Deploy from a branch → your branch → /(root)*, and the same branch
must be entered in the settings. Stemma never changes your Pages
configuration, never auto-merges, and never edits your homepage's own menus.

### Switching destinations

You have one destination at a time; choosing a folder clears a homepage
connection and the reverse. Publishing to a destination this tool has not
written to before sends the whole site rather than a difference, so moving
hosts works without any extra step — including when nothing about the writing
has changed, since the new destination is empty however familiar the site is.

A frozen release names the destination it was made for. Choosing a different one
ends it: the screen stops offering it and sending it is refused, rather than
writing to the folder you just moved away from. Press the export button again to
freeze a release for the destination you actually chose.

Folders you publish to in turn each stay at the release they were given, and you
can come back to any of them. Returning publishes over what that folder holds,
and the folder you left keeps what it was given: moving is not a takedown.

### Failure rules

- Pushing or opening a pull request is never treated as success on its own. If
  it cannot be verified, it stays running and is checked again.
- A failure is retried with the *same* frozen release bytes, even if the input
  or the skin changed since.
- If a local interruption leaves a run in progress, check the remote first.
  Recording it as abandoned leaves a failure record; it does not cancel
  anything remote.
- **Roll back to this release** shows what reverting changes, then builds the
  earlier content as a *new* release. Publication history is preserved and old
  releases are never edited.
- The first publication date is fixed once, on success. Unchanged posts keep
  their updated date. Withdrawing and republishing keeps the original first
  publication date.
- Local state alone is never taken as proof of what is merged on GitHub.

## Pictures in a published post

What you wrote is never rewritten. The stored revision and its language
variants keep the exact bytes they were saved with, so a body still refers to a
picture by the path it had where it was written — `images/cat-3f9a21b0.png`
after an editor upload, `../../assets/cat.jpg` after an import from an archive.

Preparing a release is a separate step that does rewrite: on the way into the
frozen release, links are resolved to the public slugs and opaque asset names
that readers see. That rewriting produces the published copy and never touches
the stored original, which is what a later revision is compared against.

That step parses your Markdown and writes it back out, so anything you escaped
has to be escaped again on the way out or the next parse would read it as
markup. Punctuation you wrote literally — `\*stars\*`, `\<b>`, `\[label]` —
stays literal for the reader. Parentheses, closing brackets and table pipes are
the exception: `\(…\)` and `\[…\]` are how you write mathematics here, so
escaping those would turn ordinary punctuation into a formula.

Only names the published text already contains travel in the payload. A file
attached and never linked is not published at all, and neither is its name, so
a private path in your data root cannot ride out with the site.

## The reader's site

- The site's root opens in the language you write in. KR/EN switch to the same
  post, series or genealogy URL, and `html lang` is `ko` or `en`.
- The home page shows the introduction, up to three series, and all posts by
  publication date. Empty series are hidden.
- Series keep the author's order. Previous/next within a post follow overall
  publication date.
- The body and the genealogy are separate pages. The genealogy opens centred on
  the current post and supports fit-all, zoom, pointer drag and arrow keys.
  Published nodes link; unpublished ones show only a year and month.
- Mathematics is rendered to static MathML at build time with a vendored KaTeX
  and a local Node run. Readers never execute it. This is the only part of the
  toolchain that needs Node.

## Data contract

The public payload is schema v3 and carries only what readers need: reviewed
bilingual pairs, approved structure, public identifiers, series and selected
attachments. Local-only authority and private data are never exported.
`export-public` is read-only — it computes a prospective publication time and
never records deployment success, and it does not sync the archive.

Private identifiers are never reused publicly. Public IDs and slugs are
prepared locally before a release, so a public URL never leaks an internal
document ID.

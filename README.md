# Stemma

**English** · [한국어](https://github.com/byeongsuyu/stemma/blob/main/README.ko.md)

A local writing desk for people who rewrite. You keep a private archive of
everything you have written, find an old piece, write a new one that carries it
forward, and publish the versions you choose as a bilingual static blog — with
the lineage from the old piece to the new one preserved and, if you want,
visible to readers.

It runs entirely on your own machine. Nothing is uploaded except the static
site you explicitly deploy.

> A *stemma codicum* is the diagram textual scholars draw to show which
> manuscript descends from which. This tool builds one for your own writing.

> The interface speaks Korean or English — switch it from the top bar. The
> documentation, the code and the command line are in English. Published sites
> are Korean/English pairs: you write in one of the two languages and translate
> into the other.

## What makes it different

Most blogging tools treat a post as a standalone artifact. Stemma treats it as
a **succession**: this piece came out of that one, in answer to a particular
question. That relationship is first-class data.

- **Questions** are what you are asking. A document belongs to one or more.
- **Succession edges** record that one document grew out of another.
- **Revisions** are immutable. Editing never overwrites what you wrote before.
- **Publication pairs** are a reviewed Korean + English version of a document:
  the revision in the language you write in, and its translation. You publish a
  pair, never a bare revision.
- **Genealogy** is the resulting graph, which readers can explore on the
  published site.

## Requirements

- Python 3.12 or newer. The core, the editor and the blog use only the standard
  library.
- Node.js, **only** if you publish posts containing mathematics. KaTeX renders
  formulas to static MathML at build time; readers never run it. See
  `src/stemma_studio/blog/math_support.py`.
- Git, only if you import from a Git archive or deploy through a pull request.
  Publishing to a folder needs neither.

## Install

```sh
python3.12 -m venv .venv
.venv/bin/pip install ./packages/stemma_graph .
```

That gives you the `stemma` command. Once the packages are published, this
becomes `pip install stemma-studio`, which will pull in `stemma-graph` with it;
until then, install from a checkout as above.

To work on the code, you can run everything from a checkout with no install at
all:

```sh
python3.12 -B scripts/dev.py test        # the Python suite
python3.12 -B scripts/dev.py example     # the genealogy library on its own
```

## Quick start

```sh
mkdir my-writing && cd my-writing
stemma init                      # creates data/studio.json here
stemma editor                    # http://127.0.0.1:8787
```

`init` creates an empty data root in the current folder. Every command takes
`--root` if you want to keep your data somewhere else; without it, the current
working directory is the root.

To see what a published site looks like before you have written anything, run
`stemma preview` and open <http://127.0.0.1:8766/blog/>. It serves a
synthetic sample from memory and writes nothing.

## The workflow

Everything happens on one local server, in four steps:

| | Step | Where |
|---|---|---|
| 1 | **Set up your blog** — its name, byline, the language you write in and the licence on your writing | Settings screen at `/publish/?view=settings` |
| 2 | **Import** what you have already written, then **write** | Import, then the editor at `/` |
| 3 | **Publish** — add the translation, review the pair, confirm it | Publication screen at `/publish/` |
| 4 | **Deploy** — write the site to a folder, or open one pull request | Site screen at `/publish/?view=site` |

Then read it on your own site. Step 1 is worth doing first: until you do, pages
publish under placeholder names, your writing reserves all rights by default,
and a new data root cannot publish at all until you have said which language
you write in.

## Setting up your blog

Your blog's name, byline and tagline, the language you write in, and the
licence your writing carries, are configuration rather than code — one installed
copy can publish anybody's blog. Set them on the **Settings** screen under
**Blog settings**, which writes `data/blog/site.json`.

The language you write in decides which side of each pair is the original. Write
in Korean and you add an English translation; write in English and you add a
Korean one. A post keeps the side it was first published or translated from, so
changing this later never turns round a post you have already started. That screen holds what you decide once — the blog's
identity and where it deploys to — apart from the site screen, which is what you
check each time you publish.

Note that two different licences meet on a published page:

- **This tool is MIT.** See [LICENSE](https://github.com/byeongsuyu/stemma/blob/main/LICENSE). That covers the software.
- **Your writing is yours.** Its terms are a setting, defaulting to reserving
  all rights. Presets for the Creative Commons licences and CC0 are offered,
  or you can write your own wording. Nothing gives your readers rights you did
  not choose.

See [docs/site-settings.md](https://github.com/byeongsuyu/stemma/blob/main/docs/site-settings.md).

## Writing

The editor at <http://127.0.0.1:8787> has three panes: search your archive,
read the sources you picked, and write. When you save, Stemma stores an
immutable revision and asks which parent documents this one carries forward,
and under which question.

**Add pictures or files** attaches pictures — several at once — storing each under its own
content hash and writing the Markdown link where your cursor is.

The same server hosts the publication screens at `/publish/`, where you add the
translation of a post, review the pair, and confirm it for publication. The
`/publish/?view=site` screen shows everything that would change on the live
site and deploys it.

The model's own workflow is available on the command line:

| Command | What it does |
|---|---|
| `create` | Start a draft, with repeated `--parent` and `--question` |
| `revise` | Store an input file as a new immutable revision |
| `confirm` | Confirm a document and its proposed successions |
| `archive` / `restore` | Retire a document from future use, or bring it back |
| `represent` | Choose which documents represent a question |
| `publish --pair` | Select a reviewed Korean/English pair locally |
| `unpublish` | Clear that selection |
| `export-public --planned-at` | Print the prospective public payload as JSON |
| `validate` | Check metadata and content hashes |

Run `stemma <command> --help` for the arguments. `publish` records a
local choice; it never uploads anything. Deployment is a separate, explicit
step. Global options come before the subcommand: `stemma --root . validate`.

Some work happens only in the editor and publication screens: writing a
question, preparing and reviewing a translation pair, attaching a file, and
importing a folder. `create` needs a question that already exists, so a fresh
data root is set up through the editor rather than the command line alone.

## Importing your existing writing

Open **Import** and give it the folder your writing lives in. It reads the
folder — never modifies it — and shows exactly what it would import before
anything is saved.

**Picture links are not rewritten.** A picture is recorded at the path it
occupies relative to the post that references it, so `![](images/cat.png)` and
`![](../shared/logo.png)` keep working as written. That is why it takes a
folder: the folder's shape is what makes the links resolve.

If your writing lives in a Git repository you keep updating, a second route
tracks it by commit:

```sh
stemma sync-archive --archive /absolute/path/to/your-archive
stemma sync-archive --dry-run     # later runs remember the path
```

Both are read-only and append-only. See [docs/importing.md](https://github.com/byeongsuyu/stemma/blob/main/docs/importing.md).

Already have writing in a Stemma data root? Do not import it — point the tool
at it: `stemma --root /path/containing/data editor`. See
[docs/moving-in.md](https://github.com/byeongsuyu/stemma/blob/main/docs/moving-in.md).

## Publishing

Deployment builds the static site and sends it to one destination, chosen on
the site screen:

- **A local folder** (default) — writes the finished site to a folder you name.
  No account and nothing to wait for. Move that folder wherever you like: any
  static host, `rsync`, an object store, a USB stick. Files this tool did not
  write are never touched.
- **A GitHub Pages pull request** — opens a PR against a Pages repository you
  control, so you see the diff before it goes live. Needs the `gh` CLI.

The folder is the general case and the reason the tool is not tied to one
service. See [docs/publishing.md](https://github.com/byeongsuyu/stemma/blob/main/docs/publishing.md).

## Layout

```
packages/stemma_graph/    pip: stemma-graph    the genealogy graph, stdlib only
    examples/             a runnable demo of the graph on its own
src/stemma_studio/        pip: stemma-studio   installs the `stemma` command
    core/    the model, storage, archive sync and publication rules
    blog/    Markdown rendering, the reader's site, publication admin, deploy
    editor/  the writing desk, which mounts the blog's publication screens
    cli.py   the stemma command
```

The dependency direction runs one way — `core` imports neither sibling, and
`blog` never imports `editor`. A test enforces it. `stemma-graph` is a
separate package because it is useful on its own and depends on nothing; you
can install it alone if all you want is the graph.

Neither distribution needs a third-party package installed alongside it, beyond
Studio's dependency on `stemma-graph`. Studio is not pure standard library
though: it ships vendored copies of mistune and KaTeX inside the wheel, under
their own licences.

Your writing lives in the data root, never in the package: `data/studio.json`
holds the metadata, with preserved copies under `imports/`, `revisions/`,
`assets/` and `translations/`. No personal data is included in either wheel.

## Documentation

| Document | Read it for |
|---|---|
| [Design](https://github.com/byeongsuyu/stemma/blob/main/docs/design.md) | The rules for documents, succession, retirement and publication, and why they hold |
| [Code tour](https://github.com/byeongsuyu/stemma/blob/main/docs/code-tour.md) | Where code lives, entry points, and how to run it |
| [Editor](https://github.com/byeongsuyu/stemma/blob/main/docs/editor.md) | The writing desk, and its save and recovery boundaries |
| [Publishing](https://github.com/byeongsuyu/stemma/blob/main/docs/publishing.md) | Bilingual publication, releases and deployment |
| [Importing](https://github.com/byeongsuyu/stemma/blob/main/docs/importing.md) | Bringing your existing writing in, by folder or from Git |
| [Site settings](https://github.com/byeongsuyu/stemma/blob/main/docs/site-settings.md) | Naming your blog, and licensing your writing |
| [Moving in](https://github.com/byeongsuyu/stemma/blob/main/docs/moving-in.md) | Bringing an existing data root into a new install |
| [Contributing](https://github.com/byeongsuyu/stemma/blob/main/CONTRIBUTING.md) | Tests, style and the rules a change must keep |

## Status

This is one person's tool, published in case it is useful to others. It assumes
a single local author and does not enforce that assumption: each running server
serializes its own requests, but nothing coordinates between two servers, or
between a server and the command line. Do not run two of them against one data
root.

## License

The **code** is MIT — see [LICENSE](https://github.com/byeongsuyu/stemma/blob/main/LICENSE). Bundled third-party code keeps
its own licence: mistune (BSD-3-Clause), KaTeX (MIT) and the MaruBuri font
(SIL OFL 1.1). See `src/stemma_studio/blog/vendor/README.md` and
`src/stemma_studio/blog/frontend/fonts/README.md`.

The **writing** you publish with it is not covered by that licence. Its terms
are yours to choose, in the blog settings; see
[docs/site-settings.md](https://github.com/byeongsuyu/stemma/blob/main/docs/site-settings.md).

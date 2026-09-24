# Code tour

Where things are and which file to open first.

## Layout

```
packages/stemma_graph/                     pip: stemma-graph
    src/stemma_graph/
        contracts.py    immutable value types
        genealogy.py    the graph, validation and queries
    examples/graph_only.py  a runnable demo, and the proof it stands alone

src/stemma_studio/                         pip: stemma-studio (command: stemma)
    core/           the model, storage and policy
        domain.py       state shape, validation, confirmation
        application.py  Studio: the use-case entry point
        repository.py   file and memory persistence, content hashing
        editing.py      drafts and revisions
        adapters.py     core state -> stemma_graph values
        archive_sync.py importing a Git archive
        folder_import.py importing a plain folder of Markdown
        blog.py         publication validation rules
        publication.py  building the public payload
        disclosure.py   what may be disclosed, and dates
        releases.py     release records and output paths
        containment.py  keeping a path inside a folder this tool does not own
        public_assets.py attachment selection
        migrations.py   v1-v3 state upgraded to v4
        __main__.py     the shared argument parser and dispatcher
    blog/
        render.py       public payload -> static files. Pure; no filesystem
        markdown.py     Markdown with link sanitising
        footnotes.py    footnote rendering
        math_support.py KaTeX via a local Node run
        input.py        publication input preparation, link rewriting
        attachments.py  which attachments a post references
        preview.py      memory-only loopback preview
        author_preview.py the editor's in-page preview assets
        admin.py        publication and site logic
        admin_server.py the publication HTTP handler
        deploy.py       freezing a release, artifacts, attempts, shared guards
        local_folder.py writing a release into a plain folder
        homepage.py     the GitHub pull-request path
        site_settings.py the author's blog identity and writing language
        frontend/       the reader's site assets
        admin_frontend/ the publication screens
        vendor/         mistune and KaTeX, vendored
        sample/         the synthetic payload `preview` serves
    editor/
        service.py          editor use cases over the core
        server.py           the editor HTTP handler
        workspace_server.py one listener for the editor and /publish/
        frontend/           the writing desk
    locale/         the desk's wording: ko.json and en.json, and choosing between them
    cli.py          the stemma command
```

The dependency direction runs one way: `core` imports neither sibling, and
`blog` never imports `editor`. `locale` sits beside all three because each of
them raises refusals the author reads; it imports none of them. `tests/test_package_layout.py` enforces it, and
`tests/test_graph_core.py` separately proves `stemma_graph` runs with nothing
else present, by copying the package and its example into an empty directory
and running them there.

## Entry points

| You want to | Start at |
|---|---|
| Understand the data | `core/domain.py`, then `core/blog.py` |
| Change how a page looks | `blog/render.py` and `blog/frontend/site.css` |
| Change the publication screens | `blog/admin.py` and `blog/admin_frontend/` |
| Change the writing desk | `editor/service.py` and `editor/frontend/app.js` |
| Change or add interface wording | `locale/ko.json` and `locale/en.json`, together |
| Change deployment | `blog/deploy.py`, then `blog/local_folder.py` or `blog/homepage.py` |
| Add a command | `core/__main__.py` for model commands, `cli.py` for servers |

## Running without installing

`scripts/dev.py` wires the source paths so a checkout runs with no install:

```sh
python3.12 -B scripts/dev.py test          # the Python suite
python3.12 -B scripts/dev.py test -v       # verbose
python3.12 -B scripts/dev.py example       # stemma_graph on its own
python3.12 -B scripts/dev.py studio --no-sync validate
python3.12 -B scripts/dev.py editor        # same as: stemma editor
python3.12 -B scripts/dev.py blog          # the synthetic sample site
python3.12 -B scripts/dev.py blog-admin --demo
```

It is a development adapter only. No package imports it, and it is in neither
wheel.

## How state is saved

`Studio.load()` verifies content hashes before any command reads or changes
metadata, and is the point where an archive's new commits are noticed — there
is no background watcher. Use `--no-sync`, or `--dry-run`, for a read-only
check.

Saving writes content copies first and metadata last, so a failed retry reuses
the same copies instead of overwriting different content.

`migrations.py` reads v1 to v3 state into v4 in memory, and the first save
keeps a byte-exact backup of the original JSON. `--no-sync validate` never
migrates on disk.

## Tests

```sh
python3.12 -B scripts/dev.py test
cd src/stemma_studio/blog/frontend && npm test     # reader-side navigation
cd src/stemma_studio/editor/frontend && npm test   # editor buffering
```

Every test builds its own synthetic data in a temporary directory; none reads
real writing. `tests/blog_fixtures.py` is the factory they share, and it also
backs `blog-admin --demo`.

The JavaScript suites use `node --test` with no dependencies, and cover the
logic that cannot be exercised from Python: history and scroll restoration on
the reader's site, and the editor's autosave buffer.

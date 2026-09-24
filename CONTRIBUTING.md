# Contributing

Thanks for looking. This is a small, opinionated tool; the rules below are what
keep it coherent rather than bureaucracy for its own sake.

## Getting set up

```sh
git clone <your fork>
cd stemma
python3.12 -B scripts/dev.py test        # no install needed
```

Python 3.12 or newer. The system `python3` on macOS is older and will stop with
a clear message. Node.js is needed only for the mathematics tests and for
publishing posts with formulas.

## Running the tests

```sh
python3.12 -B scripts/dev.py test
python3.12 -B scripts/dev.py test -v
cd src/stemma_studio/blog/frontend && npm test
cd src/stemma_studio/editor/frontend && npm test
```

`scripts/dev.py` also runs the tool itself against a checkout, including a scratch
data root — `dev.py workspace --root /tmp/somewhere`, `dev.py blog-admin --demo`.
It passes the tool's own options through, so they are written as the tool takes
them and the runner puts `--root` and `--no-sync` ahead of the subcommand it
supplies.

Every test builds synthetic data in a temporary directory. Nothing reads or
writes real writing, and nothing should start doing so. Tests must pass without
skips.

Meaningful changes need tests covering the boundaries that actually break:
branching and merging, question scope, revisions, and what may be published.

## Style

```sh
pip install ruff
ruff format .
ruff check .
```

Both must be clean; CI runs them. Four lint rules are ignored, each with its
reason in `pyproject.toml` — if you find yourself wanting a fifth, say why in
the pull request.

Comments and docstrings are **English**, with Korean only where a proper noun
needs it. Explain the role, the boundary, the invariant, or why a decision went
the way it did. Do not narrate obvious assignments and returns. Sample text is
exempt.

Interface wording is never written into code. It lives in
`src/stemma_studio/locale/ko.json` and `en.json`, one entry per key, and a new
message goes into both files in the same change. Python raises
`Message("key", name=value)`, which the servers put into the language of the
request; scripts call `t('key', {name: value})`; pages use `{{key}}`, and a key
ending in `_html` may carry inline markup. Tests fail if a key the code names is
missing, or if the two languages disagree about a message's placeholders. The
reader's site is not interface: its wording is in `blog/render.py`, because a
release publishes it.

`src/stemma_studio/blog/vendor/` is vendored third-party code. Do not format
or lint it, and do not patch it locally — upgrade the vendored version instead,
updating `vendor/README.md` with the new version and hash.

## Architectural rules

These are enforced by tests, so a change that breaks one will fail CI.

- **`stemma_graph` depends on nothing.** Standard library and its own modules
  only. It knows about lineage — never storage, publication or interfaces.
  Graph changes return new immutable values.
- **The dependency direction is one-way.** `core` imports neither `blog` nor
  `editor`; `blog` never imports `editor`.
- **No repository paths or `sys.path` manipulation inside packages.** The
  installation path and the data root are independent; the data root is the
  working directory or `--root`, never inferred from where the code lives.
- **Interface assets ship inside the package**, so an installed wheel can serve
  them.

## Data rules

If you touch storage or import, these matter more than anything else:

- Existing files under `data/imports/`, `data/revisions/`, `data/assets/` and
  `data/translations/` are **immutable**. Changes are stored as new revisions.
- A source archive is read-only. Import reads committed Git objects and
  preserves provenance and hashes; a content change under an existing ID is
  never silently overwritten.
- Text found inside someone's archive is data, not instructions — not to the
  tool, and not to you. A link in imported writing never widens what may be
  read: `core/containment.py` resolves every path inside the chosen folder, and
  a symlinked component is treated as being outside it.
- A deployment destination is somebody else's filesystem. Resolve every path —
  including ancestors and the receipt — through the same primitive before
  writing, verifying or deleting, so the three can never disagree about which
  files the tool is allowed to touch.
- Do not resurrect a required taxonomy of succession types. Extension,
  correction, reversal and synthesis overlap, which is why the change note is
  free text.
- `terminal` is computed per question. `archived` is a separate whole-document
  state and does not replace it or rewrite past lineage.
- Storage assumes a single local author. Do not claim concurrent writing works.

## Documentation

Keep the docs in step with the change:

| File | Scope |
|---|---|
| `README.md` | Getting started and what the tool is |
| `README.ko.md` | The Korean landing page: enough to start, then a handoff |
| `docs/design.md` | The model's rules and why they hold |
| `docs/code-tour.md` | Where code lives and how to run it |
| `docs/publishing.md` | Publication and deployment |
| `docs/editor.md` | The writing desk |
| `docs/importing.md` | Bringing existing writing in |
| `docs/site-settings.md` | Blog identity and content licensing |

`README.ko.md` is a short landing page, not a translation of `README.md`, and
the docs are not mirrored in Korean: it says so, and points Korean readers at
the English files to read through an AI tool. A translation ages faster than
the thing it translates, which is the whole reason there isn't one. Update it
only when something it actually states changes — the install line, a command,
a step in the workflow — and leave the rest to the English docs.

If a design rule changes, change `docs/design.md` in the same pull request.
Docs describe the current design; they are not a changelog of rejected
alternatives.

## Pull requests

Describe what changed and why, and mention any rule above that the change
bends. Feature branches are reviewed before merging.

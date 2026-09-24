# Changelog

Notable changes to Stemma. This project follows
[semantic versioning](https://semver.org/) loosely: the schema versions of the
stored state and the public payload are tracked separately from the package
version.

## 0.4.0 — first public release

The first release intended for people other than the original author. The
project was called Writing Studio while it was one person's tool; it is now
**Stemma**, after the *stemma codicum* — the diagram textual scholars draw to
show which manuscript descends from which.

Packages are `stemma-studio` (installing the `stemma` command) and
`stemma-graph`; the import names are `stemma_studio` and `stemma_graph`. The
data format is unchanged, so an existing `data/` root keeps working.

### Added
- **The interface speaks English as well as Korean.** Every screen, notice and
  refusal comes from one catalog per language (`src/stemma_studio/locale/`),
  shared by the servers and both frontends. The desk follows the browser until
  you switch it from the top bar, and then remembers the choice for the data
  root in `data/desk.json`. It is never published.
- **Write in English and translate into Korean**, or the other way round. The
  blog settings gain the language you write in; each post's revision is the
  original in that language and the translation is added in the other. A post
  keeps the side it was first given, so changing the setting never turns round
  a post already published or being translated. Existing data roots are taken to
  write in Korean, the language their posts came from, and behave exactly as
  before; a new root is asked before its first publication, because the choice
  is written into immutable records. The site's root page now opens in the
  language you write in.
- One `stemma` command covering the whole tool: `init`, `editor`,
  `blog-admin` and `preview` alongside the model commands.
- `stemma init`, which creates an empty data root and refuses to
  overwrite an existing one.
- Configurable site identity in `data/blog/site.json` — blog name, author,
  byline and tagline, per language, with neutral placeholders.
- A blog settings panel on the site screen, so identity and licensing are
  configured in the interface rather than by editing JSON.
- A licence setting for the author's own writing, shown in the site footer:
  presets for the Creative Commons licences and CC0, or custom wording per
  language with an optional link. It defaults to reserving all rights, and is
  separate from this project's MIT licence on the code.
- **An Import screen**: import a plain folder of Markdown and its pictures, with
  no Git and no reshaping. The scan reports what it would do — new posts,
  duplicate identifiers, missing pictures, unused images — and writes nothing
  until you confirm. Files with problems are skipped and named; everything else
  goes in. Frontmatter is read by the same rule as the Git route, so one archive
  imports alike either way; a picture that lives above the chosen folder is
  reported as such rather than as missing.
- **Pictures and files in the editor**: attach one or many at once with **Add
  pictures or files** — png, jpg, gif, webp, pdf or plain text. Each is stored under its own
  content hash, named so that two files sharing a name cannot collide, and
  verified against its own bytes before it is kept. **Preview text** shows the
  draft's own pictures, and nothing else.
- **Attached pictures now reach the published page.** The public payload lists,
  for each asset, the link forms the text uses for it, so a body that says
  `![](images/cat.png)` resolves to the asset the site serves. Previously the
  bytes were deployed but no page ever referenced them, for imported posts as
  well as written ones. Only names the published text already contains travel in
  the payload, so no private path leaves the data root.
- A data root that has never been deployed now says so on the site screen
  instead of reporting one unexplained change.
- **A Settings screen**, split out of the site screen: the blog's name, byline and
  licence, and where it deploys to. What is decided once no longer sits beside
  what you check on every publication.
- `docs/moving-in.md`, for bringing an existing data root into a new install
  rather than importing it.
- Documentation in English, including the previously undocumented import
  contract in `docs/importing.md`.
- `README.ko.md`, a short Korean landing page: enough to install and start,
  then a handoff to the English documentation, which it suggests reading
  through an AI tool. It is not a translation, and the documentation is not
  mirrored in Korean.
- **Local folder publishing**, now the default destination: the finished site is
  written to a folder you name, verified byte for byte, with no account and
  nothing to wait for. That folder feeds any static host, `rsync` or object
  store, so publishing is no longer tied to GitHub. Files the tool did not
  write are never overwritten or deleted.
- An MIT license, contribution guidelines and continuous integration.
- Tests covering the subpackage dependency direction and that an installed
  wheel carries the interface assets it serves.

### Changed
- The core, editor and blog merged into one `stemma_studio` package with
  `core`, `blog` and `editor` subpackages. `stemma-graph` remains a separate
  package with no dependencies.
- Interface assets, fonts, vendored code and the sample payload now ship inside
  the wheel, so the editor and blog run from an install rather than only from a
  checkout.
- Deployment accepts any GitHub Pages repository, not only
  `owner/owner.github.io`, and the pull-request path is now one destination
  among several rather than the only way out.
- The documented archive import contract covers only the four fields that
  affect behaviour (`id`, `date`, `title`, `assets`). Any other frontmatter is
  still preserved byte for byte, so nothing is lost and no archive needs
  reshaping to a rich schema.
- `examples/` moved under `packages/stemma_graph/`, beside the package it
  demonstrates and whose independence it proves.
- `AGENTS.md` reduced to a pointer, so the contribution rules live in exactly
  one place.
- `ruff` adopted; the codebase reformatted in one mechanical pass.
- User-facing validation errors no longer surface an unrelated chained
  traceback.

### Fixed
Found by a pre-publication review of the paths that touch other people's files.

- **Folder publishing followed symlinks out of the destination.** Only the
  destination root was checked, so a symlinked folder below it carried a whole
  site write outside the folder you chose — recorded as a success — and a
  published page replaced by a symlink was followed, destroying the file it
  pointed at before verification noticed. Every path component is now resolved
  before anything is written, and writing, verification and cleanup share one
  rule about which files the tool may touch. Cleanup leaves alone anything it
  can no longer vouch for owning.
- **Folder import read files outside the chosen folder.** An asset reached
  through a symlinked directory was copied in; it is now reported as being
  outside the folder, like `../` already was.
- **An interrupted folder deployment could not be retried.** Files written by
  the failed attempt were treated as somebody else's on the next try. Output is
  now written aside and moved into place, and a retry recognises its own
  earlier work — but still refuses a file it did not write.
- **Publishing at a base other than `/blog/` showed permanent phantom changes.**
  The prospective render ignored the configured base, so a no-op deployment
  reported most of the site as rewritten.
- **Choosing a new destination was refused as "nothing changed."** Unchanged
  writing now blocks a release only where those bytes already are; a fresh
  destination receives the whole site.
- **The command line could publish a retired document**, which the design
  forbids and the editor refused. The rule now lives in the model, where both
  interfaces reach it.
- **A failed save could strand a draft or revision.** Retrying the identical
  request now reuses the snapshot it already wrote, as saving elsewhere already
  did; different bytes at that path are still refused.
- `scripts/dev.py` passes a data root through to the server tasks. The tool reads
  `--root` before a subcommand and the runner supplies that subcommand itself, so
  `dev.py workspace --root somewhere` exited 2 rather than starting.
- **A frozen release can be read locally before it is sent.** Every release is
  frozen here before it goes anywhere, but its pages link assets by the path they
  will have on the site, so it could not be opened. **Preview** now renders it
  at a local address, in both modes: a pull request can be judged from the pages
  it would publish rather than from a diff, and a folder before anyone relies on
  it. The screen says so when the design has changed since the freeze.
- **`stemma preview --folder` reads an exported folder back.** It checks every
  file against the receipt, says whether the folder still matches, and serves it
  so the stylesheet resolves — which opening `index.html` as a file cannot do.
- **The genealogy map fills the window.** It was laid out as an article with the
  map as a fixed box inside it, so most of the screen went unused. The cards also
  reserved room for three lines of title and left the rest blank; they are smaller
  now, at the same text size.
- **Browser back and forward lost a draft that was still being saved.** Leaving a
  screen by an in-app link queued the pending save before the navigation; the
  browser's own buttons went straight to routing, so the save ran afterwards and
  read a document that had already been replaced. Both ways out of a screen now
  take the same step. The browser copy always covered the text, so this cost a
  server-side save rather than the writing itself.
- **One date policy across the desk.** The shelf, the source reader and the
  genealogy each worked their date out separately, and the reader used the last
  time the desk touched a document rather than when it was written — so an
  edited document showed two different dates on two screens, and an imported one
  that had never been edited here showed none while the others showed its date.
  All three now answer from the model, and say which date they are showing.
- **Dialogs and the publication preview tabs are operable without a mouse.**
  Dialogs are named by their own heading, and the preview tabs have the keyboard
  contract the reader's tabs already had: one stop in the tab order, arrows
  between them, and the frame named by the selected tab.
- **Importing could apply a folder other than the one reviewed.** The screen sent
  whatever the folder box held when the button was clicked, and the server
  re-read the folder at that moment, so changing the box after a scan imported
  writing the author had never seen described. Confirming now names the reviewed
  plan and writes the bytes that were scanned; a folder or rule that no longer
  matches asks for another look, and so does a file that changed in between.
- **A finished import still said nothing had been saved** and offered to import
  again, because the result of applying was drawn as though it were another scan.
- **Exporting to a folder told the author to merge a pull request** that does not
  exist. The button already knew which destination was configured, but the
  progress steps, the completion notice and the screen's own explanation did not.
- **Folder-import provenance printed `undefined`** where a Git commit would be.
  A folder import has no commit; it now says where the writing came from instead.
- **The editor called every refusal a failed save** and offered to retry it, even
  when the problem was an unsaved revision or a missing question — a retry only
  re-sends the draft, so it could not help. The server already distinguishes
  these, and that distinction now reaches the author.
- **The Writing link kept a document from a screen ago.** Global navigation goes to
  one place; continuing with a particular document is the detail page's own link.
- Publication recovery drafts held in the browser are now namespaced by workspace,
  as the editor's already were, so two data roots served from one local origin
  cannot offer each other's drafts when imported IDs collide.
- **Escaped punctuation was reinterpreted on the way to the reader.** Preparing
  a release parses the body and writes it back out, and the serialiser put back
  only backslashes and dollar signs. `\*stars\*` reached readers as emphasis,
  `\[label](url)` as a live link, and `\<b>` as a tag that then vanished. The
  stored writing was never affected; what readers saw was.
- **Release history needed every old homepage checkout to still exist.** A
  moved or deleted checkout took down the whole release screen; it now costs
  that release its pull-request detail and nothing more.
- Asking a folder destination to run a build step raised `AttributeError`
  instead of saying that folders have no build step.
- `stemma-graph` shipped without a licence file or licence metadata, and both
  distributions declared a setuptools version too old for the licence fields
  they use.
- **Writing into a destination folder ignored its own temporary names.** Every
  file is written through a sibling named after it and then moved into place, but
  only the final paths were checked. A link left at `index.html.stemma-part`
  carried a page's bytes onto the file it pointed at — destroying it before
  verification could reject the release — and an unrelated file at that name was
  written through and then carried off by the move. The receipt's temporary name
  had the same hole. Both are now resolved by the rule the rest of the
  destination uses and created exclusively, so whatever is already there stops
  the release instead.
- **A release frozen for one destination could be sent to another.** Choosing a
  different folder left the prepared release both current and deployable, since
  only the output was compared, and sending it wrote the site into the folder the
  screen no longer named. A frozen release now belongs to the destination it
  names: the screen stops offering it, and delivery refuses it.
- **The export button stayed off for a destination that had never had the site.**
  Publishing unchanged writing to a fresh destination was allowed again, but the
  screen still read "nothing changed" and disabled the button, so nobody could
  reach it. The screen now tells unchanged writing apart from a destination
  waiting for it, and that decision sits with the other tested ones rather than
  inline in the view.
- **Returning to a folder published to before was refused.** The receipt in that
  folder was compared against the newest release rather than the one that wrote
  it, so publishing to a second folder made the first unreachable — "the
  destination folder changed since the last release" about this tool's own work.
  Each folder is now judged against the release it actually holds.
- **The editor offered to retry a save it had refused itself.** A guard like an
  unsaved Korean revision never becomes a request, so it carried no status and
  was read as a request that failed. Those now say so, and the desk asks for the
  thing that actually unblocks the author instead of another save.
- **A picture added after its post was imported could never be attached.** The
  post was unchanged, so a re-scan passed over it: the picture stayed missing and
  was reported as belonging to no post at all. A re-scan now reconciles the
  pictures of posts it has already imported, attaching what it can without
  touching a byte of the writing, and no longer calls a picture in use an orphan.

### Removed
- The original author's blog name, byline and tagline, which were constants in
  the renderer.
- A hard-coded personal filesystem path in the homepage deployment guard, which
  now reads the archive location the author actually configured.

### Notes
- The interface is Korean or English; documentation, code and the command line
  are English.
- Published sites remain a fixed Korean/English pair; either side may be the
  original.
- Deployment failures are now recorded as message keys so either language can
  explain them. Failures recorded by earlier versions are shown as written.
- Storage assumes a single local author.

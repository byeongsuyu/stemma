# Site settings

Three things about a published site are yours and cannot be decided by this
repository: **what your blog is called**, **which language you write it in**,
and **what other people may do with your writing**. All three are settings,
edited on the settings screen.

## Where to set them

Run the editor and open **Settings**:

```sh
stemma editor        # then http://127.0.0.1:8787/publish/?view=settings
```

That screen holds what you decide once and rarely revisit — your blog's identity
and where it deploys to. What you check each time you publish stays on the site
screen.

Open **Blog settings**. Everything below is on that panel, and
saving writes `data/blog/site.json` in your data root. You can edit that file
directly instead; the panel is the same data.

Settings change every rendered page, so they behave like any other change:
after saving, the **site** screen lists them under *what this deployment
changes*, and they reach readers on your next deployment.

## Identity

| Field | Where it appears |
|---|---|
| `name` | The brand link in the header, and the page `<title>` |
| `author` | The `<title>` suffix and the `©` line in the footer |
| `byline` | Under the brand in the header |
| `intro` | The tagline under the byline — header only, never the footer |

Each is set per language. Anything you leave blank falls back to a neutral
placeholder, so an unconfigured site reads as unconfigured rather than as
somebody else's. Values are escaped when rendered, so punctuation and markup
characters in your name are safe.

```json
{
  "ko": {"name": "나의 기록", "author": "홍길동", "byline": "홍길동", "intro": "읽고 다시 묻는 기록"},
  "en": {"name": "My Record", "author": "Gildong Hong", "byline": "by Gildong Hong", "intro": "Reading, and asking again."}
}
```

## The licence on your writing

This is separate from the licence on the tool. **Stemma's code is MIT**
— that is settled in [LICENSE](../LICENSE) and is about the software. **Your
posts are yours**, and their terms are your decision. Nothing here grants
anyone rights to your writing unless you choose to.

The default is to reserve all rights. That is deliberate: publishing should
never give away terms you did not pick.

The panel offers these presets, rendered with a link to the licence deed:

| Choice | Footer |
|---|---|
| `all-rights-reserved` *(default)* | `© You. All rights reserved.` |
| `cc-by-4.0` | Credit required |
| `cc-by-sa-4.0` | Credit, and share alike |
| `cc-by-nc-4.0` | Credit, non-commercial |
| `cc-by-nc-sa-4.0` | Credit, non-commercial, share alike |
| `cc-by-nd-4.0` | Credit, no derivatives |
| `cc0-1.0` | Public domain dedication |
| `custom` | Your own wording, per language, with an optional link |

Stored form — for a preset, only the choice is kept, so the label and link stay
correct if a preset is ever corrected:

```json
{"license": {"id": "cc-by-4.0"}}
```

For your own terms, the wording is kept per language:

```json
{
  "license": {
    "id": "custom",
    "ko": "인용 시 출처를 밝혀 주세요",
    "en": "Please credit the author",
    "url": "https://example.com/terms"
  }
}
```

A custom link must be `http://` or `https://`; anything else is dropped, so a
footer can never carry a script URL. Custom wording is escaped like any other
setting.

If you want different terms for different posts, say so in the post itself —
the footer notice is site-wide.

## Languages

Korean and English are a fixed pair. Publishing a post requires a reviewed
version in both, and every reader page exists in both. Supporting an arbitrary
set of languages would touch the renderer, the routing, the fonts and the
publication rules, and is not part of this version.

### The language you write in

`language` is `"ko"` or `"en"`: the one you write in. In each post, the revision
you write is the original in that language, and you add its translation into
the other on the publication screen. It also decides where the site's root page
sends readers.

```json
{"language": "en", "ko": {"name": "…"}, "en": {"name": "…"}}
```

Changing it affects posts you have not started publishing. A post that already
has a stored variant, or a translation draft you have begun, keeps the side it
was given — the choice is recorded in the post's own records, which never
change. A data root that published before this setting existed is taken to write
in the language its posts came from. A data root that has published nothing and
has no `language` is asked on the post screen before anything is saved.

### The desk's own language

The editor and publication screens speak Korean or English, switched from their
top bar. That is a preference of your data root, kept in `data/desk.json`, and
it never reaches the published site: you can write in English with a Korean
desk, or the other way round.

The rest of the site's wording — “All posts”, “Series”, “Date unknown” and so
on — is interface text, not identity. It stays in `COPY` in
`src/stemma_studio/blog/render.py`.

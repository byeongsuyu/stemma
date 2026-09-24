"""Per-site identity and content licensing, stored with the author's data.

Two different licenses meet on a published page. The *code* that builds the
site is MIT, and that is settled here in the repository. The *writing* the site
publishes belongs to whoever wrote it, and only they can choose its terms — so
the footer notice is a setting, not a constant, and it defaults to reserving
all rights rather than giving anything away on the author's behalf.

Everything in this module lives in ``data/blog/site.json`` beside the other
blog settings, and is edited on the site screen's settings panel. The rest of
the site's wording, in :data:`stemma_studio.blog.render.COPY`, is interface
text rather than identity and stays in the code. Korean and English are a fixed
pair; see docs/site-settings.md.

``language`` is the one the author writes in: the side of every new post that is
its revision, with the other side its translation. It is None until chosen, which
is different from any choice — see ``Admin.writing_language`` for what an unset
root falls back to.
"""

import json
from pathlib import Path

LANGUAGES = ("ko", "en")
FIELDS = ("name", "author", "byline", "intro")
# Deliberately generic, so an unconfigured site reads as unconfigured.
DEFAULTS = {
    "ko": {
        "name": "나의 블로그",
        "author": "지은이",
        "byline": "지은이",
        "intro": "블로그 소개를 여기에 적습니다.",
    },
    "en": {
        "name": "My Blog",
        "author": "Author",
        "byline": "by Author",
        "intro": "A short description of this blog.",
    },
}

# Presets the settings screen offers. The author may also write their own.
# Reserving all rights is the default: publishing must never give away terms
# the author did not choose.
LICENSES = {
    "all-rights-reserved": {"ko": "모든 권리 보유", "en": "All rights reserved", "url": None},
    "cc-by-4.0": {"ko": "CC BY 4.0", "en": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
    "cc-by-sa-4.0": {
        "ko": "CC BY-SA 4.0",
        "en": "CC BY-SA 4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    "cc-by-nc-4.0": {
        "ko": "CC BY-NC 4.0",
        "en": "CC BY-NC 4.0",
        "url": "https://creativecommons.org/licenses/by-nc/4.0/",
    },
    "cc-by-nc-sa-4.0": {
        "ko": "CC BY-NC-SA 4.0",
        "en": "CC BY-NC-SA 4.0",
        "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    },
    "cc-by-nd-4.0": {
        "ko": "CC BY-ND 4.0",
        "en": "CC BY-ND 4.0",
        "url": "https://creativecommons.org/licenses/by-nd/4.0/",
    },
    "cc0-1.0": {
        "ko": "CC0 1.0 (퍼블릭 도메인 기증)",
        "en": "CC0 1.0 (public domain dedication)",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
    },
}
CUSTOM = "custom"
DEFAULT_LICENSE = "all-rights-reserved"


def settings_path(root):
    return Path(root) / "data" / "blog" / "site.json"


def clean(value, fallback=""):
    """Take a stored scalar only when it is a non-blank string."""
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def clean_url(value):
    """Accept only an absolute http(s) link, so a footer can never carry a script URL."""
    text = clean(value)
    return text if text.startswith(("https://", "http://")) else ""


def normalise_license(raw):
    """Resolve the stored licence choice, falling back to reserving all rights."""
    stored = raw if isinstance(raw, dict) else {}
    identifier = clean(stored.get("id"), DEFAULT_LICENSE)
    if identifier not in LICENSES and identifier != CUSTOM:
        identifier = DEFAULT_LICENSE
    result = {"id": identifier, "url": clean_url(stored.get("url"))}
    for language in LANGUAGES:
        result[language] = clean(stored.get(language))
    if identifier != CUSTOM:
        # Presets are authoritative: a stale label stored earlier never wins.
        result["url"] = LICENSES[identifier]["url"] or ""
        for language in LANGUAGES:
            result[language] = LICENSES[identifier][language]
    else:
        for language in LANGUAGES:
            result[language] = result[language] or LICENSES[DEFAULT_LICENSE][language]
    return result


def normalise(raw):
    """Merge stored values over the placeholders; unknown keys and blanks are ignored."""
    stored = raw if isinstance(raw, dict) else {}
    result = {"language": stored.get("language") if stored.get("language") in LANGUAGES else None}
    for language in LANGUAGES:
        entry = stored.get(language)
        if not isinstance(entry, dict):
            entry = {}
        result[language] = {field: clean(entry.get(field), DEFAULTS[language][field]) for field in FIELDS}
    result["license"] = normalise_license(stored.get("license"))
    return result


def load(root):
    """Read the author's site identity, falling back to the placeholders."""
    path = settings_path(root)
    if not path.exists():
        return normalise(None)
    try:
        return normalise(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid site settings in {path}: {error}") from error


def storable(settings):
    """Keep only what the author chose; preset labels are resolved on read."""
    result = {language: dict(settings[language]) for language in LANGUAGES}
    if settings["language"]:
        result["language"] = settings["language"]
    chosen = settings["license"]
    entry = {"id": chosen["id"]}
    if chosen["id"] == CUSTOM:
        entry.update({language: chosen[language] for language in LANGUAGES})
        if chosen["url"]:
            entry["url"] = chosen["url"]
    result["license"] = entry
    return result


def save(root, settings):
    """Write normalised site identity and return the resolved settings."""
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = normalise(settings)
    path.write_text(json.dumps(storable(normalised), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalised


def rights(site, language):
    """The footer notice as (copyright text, licence label, licence url)."""
    chosen = site["license"]
    return "© {}.".format(site[language]["author"]), chosen[language], chosen["url"]


def choices():
    """Licence presets for the settings screen, in offer order."""
    return [
        {"id": identifier, "url": entry["url"] or "", **{lang: entry[lang] for lang in LANGUAGES}}
        for identifier, entry in LICENSES.items()
    ]

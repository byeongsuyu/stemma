"""The desk's own wording, in every language it speaks, and which one it speaks now.

This is interface text: menus, buttons, notices and the refusals a screen shows.
The author's writing is never translated here, and neither is the reader's site,
whose wording is part of what a release publishes (see ``blog/render.py``).

Wording lives in one catalog per language, ``ko.json`` and ``en.json``, shared by
the Python servers and both frontends so that the two sides cannot drift. Code
names a message by key. A refusal raised deep inside the model carries its key in
a :class:`Message`, and only the server that answers the browser decides which
language to say it in. Everywhere else — the command line, a log, a test — a
Message reads as its English text.

This package sits beside ``core``, ``blog`` and ``editor`` rather than inside any
of them, because all three raise messages and ``core`` may import neither sibling.
"""

import json
import re
from functools import cache
from html import escape
from pathlib import Path

LANGUAGES = ("ko", "en")
# What a desk speaks when neither the author nor their browser has said otherwise.
FALLBACK = "en"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TEMPLATE = re.compile(r"\{\{([\w.]+)\}\}")
HERE = Path(__file__).parent


@cache
def catalog(language):
    return json.loads((HERE / (language + ".json")).read_text(encoding="utf-8"))


def translate(language, key, **params):
    """One message in one language, with its `{name}` placeholders filled."""
    text = catalog(language if language in LANGUAGES else FALLBACK)[key]
    values = {
        name: translate(language, v.key, **v.params) if isinstance(v, Message) else v for name, v in params.items()
    }
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


class Message(str):
    """Wording for the author, carried by key until a screen knows its language.

    It is a ``str`` so it passes through every existing ``raise ValueError(...)`` and
    ``_require(...)`` unchanged; as a plain string it is the English text.
    """

    def __new__(cls, key, **params):
        value = super().__new__(cls, translate(FALLBACK, key, **params))
        value.key, value.params = key, params
        return value

    def __reduce__(self):
        # Copies are rebuilt from the key; the default would treat the English text as one.
        return rebuild, (self.key, self.params)

    @classmethod
    def stored(cls, text):
        """Text kept in the data root: a message key since keys existed, prose before that.

        Prose written by an older version is shown exactly as it was saved.
        """
        return cls(text) if isinstance(text, str) and text in catalog(FALLBACK) else text


def rebuild(key, params):
    return Message(key, **params)


def carried(error):
    """What an exception has to say, keeping the key when it has one."""
    if len(error.args) == 1 and isinstance(error.args[0], Message):
        return error.args[0]
    return str(error)


def localise(value, language):
    """Replace every Message inside a response with its wording in `language`."""
    if isinstance(value, Message):
        return translate(language, value.key, **value.params)
    if isinstance(value, dict):
        return {k: localise(v, language) for k, v in value.items()}
    if isinstance(value, list):
        return [localise(v, language) for v in value]
    return value


def negotiate(header):
    """The first supported language an Accept-Language header asks for, or None.

    Order in the header is taken as preference; quality weights are honoured only as
    far as a zero excludes a language, which is all a two-language desk needs.
    """
    for part in (header or "").split(","):
        tag, _, quality = part.strip().partition(";")
        language = tag.strip().lower().split("-")[0]
        if language in LANGUAGES and quality.strip().replace(" ", "") not in ("q=0", "q=0.0", "q=0.00", "q=0.000"):
            return language
    return None


def preference_path(root):
    return Path(root) / "data" / "desk.json"


def stored_language(root):
    """The interface language the author chose, or None if they never chose one."""
    try:
        value = json.loads(preference_path(root).read_text(encoding="utf-8")).get("language")
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return None
    return value if value in LANGUAGES else None


def interface_language(root, accept_language=None):
    """The author's choice, else what their browser asks for, else the fallback."""
    return stored_language(root) or negotiate(accept_language) or FALLBACK


def save_language(root, language):
    """Remember the desk's language. It is a preference of this data root, never published."""
    if language not in LANGUAGES:
        raise ValueError(Message("error.unsupported_language"))
    path = preference_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"language": language}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return language


def page(path, language):
    """An interface page with its `{{key}}` wording filled in for `language`.

    The page also carries the whole catalog for its scripts, as inert JSON: the
    Content-Security-Policy runs no inline script, and none is needed to read data.
    """
    table = catalog(language)
    special = {
        "lang": language,
        # `<` is escaped so no message can close the element that carries the catalog.
        "messages": json.dumps(table, ensure_ascii=False).replace("<", "\\u003c"),
    }
    source = Path(path).read_text(encoding="utf-8")

    def fill(match):
        key = match.group(1)
        if key in special:
            return special[key]
        # A key ending in `_html` carries its own inline markup; the catalog ships inside
        # the package, so it is trusted the way the page itself is.
        return table[key] if key.endswith("_html") else escape(table[key])

    return TEMPLATE.sub(fill, source).encode("utf-8")

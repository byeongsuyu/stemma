"""Parse TeX before Markdown escapes; convert it to static, offline MathML."""

import json
import re
import subprocess
from pathlib import Path

from stemma_studio.locale import Message


def tex_plugin(md):
    def block(parser, m, state):
        raw = m.group(0).strip()
        body = raw[2:-2].strip()
        state.append_token({"type": "block_math", "raw": body})
        return m.end()

    def inline(parser, m, state):
        raw = m.group(0)
        if raw.startswith("$$"):
            body, kind = raw[2:-2], "block_math"
        elif raw.startswith("\\("):
            body, kind = raw[2:-2], "inline_math"
        else:
            body, kind = raw[1:-1], "inline_math"
        state.append_token({"type": kind, "raw": body})
        return m.end()

    md.block.register(
        "block_math", r"^ {0,3}(?:\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\])[ \t]*(?:\n|$)", block, before="fenced_code"
    )
    md.inline.register(
        "inline_math", r"\$\$[^\n]+?\$\$|\\\([^\n]+?\\\)|\$(?![\s$])[^$\n]+?(?<!\s)\$(?!\d)", inline, before="escape"
    )
    md.block.insert_rule(md.block.block_quote_rules, "block_math", before="fenced_code")
    md.block.insert_rule(md.block.list_rules, "block_math", before="fenced_code")


def render_formulas(formulas):
    if not formulas:
        return []
    if any(re.search(r"\\(?:href|url|includegraphics|html\w*)\b", f["text"]) for f in formulas):
        raise ValueError(Message("error.math.unsafe"))
    if any(len(f["text"]) > 20000 for f in formulas):
        raise ValueError(Message("error.math.too_long"))
    try:
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("math-render.cjs"))],
            input=json.dumps(formulas),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        raise ValueError(Message("error.math.node")) from None
    except subprocess.TimeoutExpired:
        raise ValueError(Message("error.math.timeout")) from None
    if result.returncode:
        raise ValueError(Message("error.math.failed", detail=result.stderr[:400]))
    return json.loads(result.stdout)

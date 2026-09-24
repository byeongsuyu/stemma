"""Memory-only author previews using the public typography renderer."""

from html import escape
from pathlib import Path
from urllib.parse import unquote

from stemma_studio.locale import FALLBACK, Message, translate

from .markdown import markdown

FRONTEND = Path(__file__).parent / "frontend"
ASSETS = {"theme.css", "site.css", "studio-header.css", "fonts/MaruBuri-Regular.woff2", "fonts/MaruBuri-Bold.woff2"}
# One worked example per interface language: the same constructs, written the way that
# language's author would write them.
EXAMPLES = {}
EXAMPLES["ko"] = r"""기록은 끝맺음보다 다음 질문에 가깝습니다. 첫 문단의 첫 글자는 이렇게 자동으로
커집니다. 한 줄짜리 짧은 문단으로 시작해도 다음 문단이 글자를 피해 밀려나지 않으니,
길이를 억지로 맞출 필요는 없습니다.

## 각주

문장에 각주를 붙일 수 있습니다.[^1]

[^1]: 각주 설명입니다. 본문 숫자와 되돌아가기 링크로 이동할 수 있습니다.

## 소제목과 강조

**굵은 글자**, *기울임*, `코드`를 쓸 수 있습니다.

> 인용문은 이렇게 씁니다.

- 첫 번째 항목
- 두 번째 항목

## 표와 수식

함수 $f(x)=x^2$의 변화율은 \(f'(x)=2x\)입니다.

| 구분 | 표현 | 값 |
| :--- | :---: | ---: |
| 미분 | $f'(x)$ | $2x$ |
| 정적분 | $\int_0^1 f(x)\,dx$ | $1/3$ |

$$
\int_0^1 x^2\,dx=\frac{1}{3}
$$

```math
\begin{pmatrix}1&2\\3&4\end{pmatrix}
```

일반 코드 블록 안의 수식은 변환하지 않습니다.

```python
f = "수식이 아닌 코드"
```

달러 기호는 \$처럼 쓰고, 표 안의 세로선은 \|처럼 씁니다.
"""
EXAMPLES["en"] = r"""A record is closer to the next question than to an ending. The first letter of
the first paragraph is enlarged automatically. Even a one-line opening paragraph
does not push the next one aside, so there is no need to pad it out.

## Footnotes

A sentence can carry a footnote.[^1]

[^1]: This is the footnote. The number in the text and the return link move between them.

## Headings and emphasis

You can write **bold**, *italic* and `code`.

> A quotation is written like this.

- First item
- Second item

## Tables and mathematics

The rate of change of $f(x)=x^2$ is \(f'(x)=2x\).

| Kind | Expression | Value |
| :--- | :---: | ---: |
| Derivative | $f'(x)$ | $2x$ |
| Definite integral | $\int_0^1 f(x)\,dx$ | $1/3$ |

$$
\int_0^1 x^2\,dx=\frac{1}{3}
$$

```math
\begin{pmatrix}1&2\\3&4\end{pmatrix}
```

Mathematics inside an ordinary code block is not converted.

```python
f = "code, not mathematics"
```

Write a dollar sign as \$, and a vertical bar inside a table as \|.
"""


def preview(title, body, language="ko", summary="", assets=None, interface=FALLBACK):
    """Render a draft with its own attachments and nothing else.

    ``assets`` maps the link a manuscript uses to a local URL the editor serves.
    Only the draft's own attachments belong in it, so a preview can show the
    pictures the writer just added without reaching anything else: navigation
    away from the draft stays blocked, and no external address is ever fetched.
    ``language`` is the language of the writing; ``interface`` is the desk's own, used
    for the banner and the placeholder title.
    """
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError(Message("error.preview.text"))
    if language not in ("ko", "en"):
        raise ValueError(Message("error.unsupported_language"))
    assets = assets or {}
    rendered = markdown(body, lambda url: assets.get(unquote(url)), assets)
    from .markdown import inline_markdown

    intro = '<p class="article-summary">' + inline_markdown(summary) + "</p>" if summary else ""
    return (
        '<!doctype html><html lang="' + language + '"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'self'; font-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'\">"
        '<link rel="stylesheet" href="/render-assets/site.css"></head><body>'
        '<aside class="preview">' + escape(translate(interface, "preview.banner")) + "</aside>"
        '<main><header class="article-header"><h1>'
        + escape(title or translate(interface, "editor.untitled"))
        + "</h1>"
        + intro
        + '</header><article class="prose">'
        + rendered
        + "</article></main></body></html>"
    )

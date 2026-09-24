"""Pure public-payload to static-file mapping. No corpus or filesystem access."""

import posixpath
import re
import textwrap
from html import escape
from urllib.parse import unquote

from .markdown import external_url, inline_markdown, markdown
from .site_settings import normalise as normalise_site
from .site_settings import rights

COPY = {
    "ko": dict(
        posts="전체 글",
        series="시리즈",
        all_series="모든 시리즈",
        empty="아직 공개된 글이 없습니다.",
        count="편",
        graph="이 글의 계보 보기",
        back="본문으로 돌아가기",
        scope="공개 허용된 계보",
        alone="이 글은 독립된 계보입니다.",
        private="미공개",
        unknown="시점 미상",
        current="현재 글",
        source="원문 시점",
        created="Studio 최초 저장",
        published="블로그 공개",
        updated="공개 갱신",
        previous="이전 공개 글",
        next="다음 공개 글",
        fit="전체 보기",
        center="현재 글",
        zoomin="확대",
        zoomout="축소",
        missing="페이지를 찾을 수 없습니다.",
        home="목록",
        read="한국어로 읽기 →",
        maphelp="선을 따라 부모에서 자식으로 이어집니다. 날짜 간격은 기간에 비례하지 않습니다. 드래그 또는 방향키로 이동할 수 있습니다.",
    ),
    "en": dict(
        posts="All posts",
        series="Series",
        all_series="All series",
        empty="No posts published yet.",
        count="posts",
        graph="Explore this post’s genealogy",
        back="Return to article",
        scope="Approved genealogy",
        alone="This post stands on its own.",
        private="Unpublished",
        unknown="Date unknown",
        current="Current post",
        source="Original date",
        created="First saved in Studio",
        published="Published",
        updated="Updated",
        previous="Previous post",
        next="Next post",
        fit="Fit all",
        center="Current post",
        zoomin="Zoom in",
        zoomout="Zoom out",
        missing="Page not found.",
        home="Home",
        read="Read in English →",
        maphelp="Arrows run from parent to child. Date spacing is not proportional to elapsed time. Drag or use arrow keys to pan.",
    ),
}
CSP = "default-src 'none'; style-src 'self'; font-src 'self'; script-src 'self'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"


def e(value):
    return escape(str(value), quote=True)


def base_path(value):
    if not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*", value):
        raise ValueError("Base must be / or a slash-terminated safe path")
    return value


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("Unsafe public slug")
    return value


def render_site(public, assets=None, base="/", preview=False, site=None):
    """Return bytes keyed by safe relative paths; missing bilingual bodies fail closed."""
    base_path(base)
    site = normalise_site(site)
    if public.get("schema_version") != 3:
        raise ValueError("Public schema v3 required")
    assets = assets or {}
    docs = list(public["documents"])
    docs.sort(key=lambda d: d["first_published_at"], reverse=True)
    by_id = {d["id"]: d for d in docs}
    if len(by_id) != len(docs) or len({d["slug"] for d in docs}) != len(docs):
        raise ValueError("Duplicate public document identity")
    by_slug = {slug(d["slug"]): d for d in docs}
    series = [s for s in public["series"] if s["documents"]]
    if len({slug(s["slug"]) for s in series}) != len(series):
        raise ValueError("Duplicate series slug")
    for item in docs + series:
        for lang in ("ko", "en"):
            val = item["translations"].get(lang)
            if not val or not val.get("title") or (item in docs and not val.get("body")):
                raise ValueError("Reviewed bilingual content required")
    for s in series:
        if any(d not in by_id for d in s["documents"]) or len(set(s["documents"])) != len(s["documents"]):
            raise ValueError("Invalid public series membership")
    allowed_assets = {a["url"] for d in docs for a in d["assets"]}
    if set(assets) != allowed_assets:
        raise ValueError("Exact selected asset bytes required")
    for path, content in assets.items():
        if not re.fullmatch(r"assets/[a-f0-9]{32}\.(png|jpg|gif|webp|pdf|txt)", path) or not isinstance(content, bytes):
            raise ValueError("Unsafe asset path or bytes")
    files = dict(assets)

    def footer(lang):
        """Copyright and the author's chosen terms for their writing, not for this code."""
        copyright_text, label, url = rights(site, lang)
        if not url:
            return e(copyright_text) + " " + e(label) + "."
        return (
            f'{e(copyright_text)} <a href="{e(url)}" rel="license noopener noreferrer" target="_blank">{e(label)}</a>.'
        )

    def page(lang, route, title, body, wide=False):
        s = site[lang]
        languages = '<a lang="ko" href="{}ko/{}" {}>KR</a><span>/</span><a lang="en" href="{}en/{}" {}>EN</a>'.format(
            base,
            route,
            'aria-current="page"' if lang == "ko" else "",
            base,
            route,
            'aria-current="page"' if lang == "en" else "",
        )
        banner = (
            '<aside class="preview">'
            + e(preview if isinstance(preview, str) else "임시 fixture · 로컬 시안 / Synthetic local preview")
            + "</aside>"
            if preview
            else ""
        )
        result = '<!doctype html><html lang="{}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{}"><meta name="referrer" content="no-referrer">{}<title>{} · {} — {}</title><link rel="stylesheet" href="{}site.css"><script src="{}site.js" defer></script></head><body>{}<header class="site-header"><div class="site-identity"><a class="brand" href="{}{}/">{}</a><span class="byline">{}</span><p class="site-tagline">{}</p></div><nav aria-label="Language">{}</nav></header><main id="main" class="{}">{}</main><footer class="site-footer">{}</footer></body></html>'.format(
            lang,
            e(CSP),
            '<meta name="robots" content="noindex,nofollow">' if preview else "",
            e(title),
            e(s["name"]),
            e(s["author"]),
            base,
            base,
            banner,
            base,
            lang,
            e(s["name"]),
            e(s["byline"]),
            e(s["intro"]),
            languages,
            "wide" if wide else "",
            body,
            footer(lang),
        )
        return result.encode("utf-8")

    for lang in ("ko", "en"):
        t = COPY[lang]

        def url(doc):
            return base + lang + "/posts/" + doc["slug"] + "/"

        def link(doc):
            return '<a href="{}">{}</a>'.format(url(doc), e(doc["translations"][lang]["title"]))

        def rows(items):
            return (
                '<ul class="posts">'
                + "".join(
                    "<li><time>{}</time><h2>{}</h2>{}</li>".format(
                        e(d["first_published_at"][:10]),
                        link(d),
                        "<p>" + inline_markdown(d["translations"][lang]["summary"]) + "</p>"
                        if d["translations"][lang].get("summary")
                        else "",
                    )
                    for d in items
                )
                + "</ul>"
            )

        def series_rows(items):
            return (
                '<ul class="series-list">'
                + "".join(
                    '<li><a href="{}{}/series/{}/">{}</a>{}<small>{} {}</small></li>'.format(
                        base,
                        lang,
                        s["slug"],
                        e(s["translations"][lang]["title"]),
                        "<p>" + inline_markdown(s["translations"][lang]["summary"]) + "</p>"
                        if s["translations"][lang].get("summary")
                        else "",
                        len(s["documents"]),
                        t["count"],
                    )
                    for s in items
                )
                + "</ul>"
            )

        home = '<h1 class="visually-hidden">{}</h1>'.format(t["home"])
        if series:
            home += '<section><h2 class="section-label">{}</h2>{}{}</section>'.format(
                t["series"],
                series_rows(series[:3]),
                '<a href="{}{}/series/">{}</a>'.format(base, lang, t["all_series"]) if len(series) > 3 else "",
            )
        home += '<section><h2 class="section-label">{}</h2>{}</section>'.format(
            t["posts"], rows(docs) if docs else "<p>" + t["empty"] + "</p>"
        )
        files[lang + "/index.html"] = page(lang, "", t["home"], home)
        files[lang + "/series/index.html"] = page(
            lang, "series/", t["series"], "<h1>" + t["series"] + "</h1>" + series_rows(series)
        )
        for s in series:
            text = s["translations"][lang]
            files[lang + "/series/" + s["slug"] + "/index.html"] = page(
                lang,
                "series/" + s["slug"] + "/",
                text["title"],
                "<h1>"
                + e(text["title"])
                + "</h1><p>"
                + inline_markdown(text.get("summary") or "")
                + "</p>"
                + rows([by_id[i] for i in s["documents"]]),
            )
        for index, d in enumerate(docs):
            text = d["translations"][lang]
            local_assets = {a["url"]: base + a["url"] for a in d["assets"]}
            # The body still names its pictures the way the author wrote them.
            for a in d["assets"]:
                for name in a.get("names", ()):
                    local_assets.setdefault(name, base + a["url"])

            def resolve(value):
                # Only canonical public destinations are accepted as local URLs.
                raw = unquote(value)
                if raw.startswith("post:") and raw[5:] in by_slug:
                    return url(by_slug[raw[5:]])
                if raw in local_assets:
                    return local_assets[raw]
                if posixpath.normpath(raw) in local_assets:
                    return local_assets[posixpath.normpath(raw)]
                for target in docs:
                    if raw in (base + language + "/posts/" + target["slug"] + "/" for language in ("ko", "en")):
                        return url(target)
                if re.fullmatch(r"#[a-zA-Z0-9_-]+", raw):
                    return raw
                return external_url(value)

            memberships = " · ".join(
                '<a href="{}{}/series/{}/">{}</a>'.format(base, lang, s["slug"], e(s["translations"][lang]["title"]))
                for s in series
                if d["id"] in s["documents"]
            )
            date = d["date"]
            info = (
                (t.get(date["kind"], t["unknown"]) + " " + (date["value"] or ""))
                + " · "
                + t["published"]
                + " "
                + d["first_published_at"][:10]
            )
            if d["published_updated_at"] != d["first_published_at"]:
                info += " · " + t["updated"] + " " + d["published_updated_at"][:10]
            summary_html = (
                '<p class="article-summary">' + inline_markdown(text["summary"]) + "</p>" if text.get("summary") else ""
            )
            body = '<article><header class="article-header"><p class="eyebrow">{}</p><h1>{}</h1>{}<p class="dates">{}</p><p class="memberships">{}</p></header><div class="prose">{}</div></article>'.format(
                t["posts"],
                e(text["title"]),
                summary_html,
                e(info),
                memberships,
                markdown(text["body"], resolve, local_assets),
            )
            body += '<div class="article-end"><a data-open-map href="{}genealogy/">{} <span aria-hidden="true">↗</span></a></div><nav class="chronology" aria-label="{}">'.format(
                url(d), t["graph"], t["posts"]
            )
            for offset, key in ((1, "previous"), (-1, "next")):
                neighbor = docs[index + offset] if 0 <= index + offset < len(docs) else None
                body += "<div><small>{}</small>{}</div>".format(t[key], link(neighbor) if neighbor else "—")
            body += "</nav>"
            route = "posts/" + d["slug"] + "/"
            files[lang + "/" + route + "index.html"] = page(lang, route, text["title"], body)
            component = next((g for g in public["genealogies"] if g["document"] == d["id"]), None)
            if component is None:
                raise ValueError("Missing public genealogy")
            graph = render_graph(component, by_id, d["id"], lang, base)
            graph_body = '<a data-close-map href="{}">← {}</a><header class="map-header"><p class="eyebrow">{}</p><h1>{}</h1></header>{}'.format(
                url(d), t["back"], t["scope"], e(text["title"]), graph
            )
            files[lang + "/" + route + "genealogy/index.html"] = page(
                lang, route + "genealogy/", t["scope"], graph_body, len(component["nodes"]) > 1
            )
    # The root sends readers to the language the author writes in; a site whose author
    # never chose one is one that has always been published from Korean.
    home = site["language"] or "ko"
    files["index.html"] = page(
        home,
        "",
        COPY[home]["home"],
        "<h1>"
        + e(site[home]["name"])
        + '</h1><a href="'
        + base
        + home
        + '/">'
        + COPY[home]["read"]
        + "</a><span data-default-language></span>",
    )
    files["404.html"] = page(
        home,
        "",
        "404",
        '<h1>404</h1><p>페이지를 찾을 수 없습니다. / Page not found.</p><a href="' + base + home + '/">목록 / Home</a>',
    )
    return files


def render_graph(graph, docs, current, lang, base):
    """Chronology orders rows; topological depth separates columns."""
    t = COPY[lang]
    nodes = {n["id"]: n for n in graph["nodes"]}
    if current not in nodes:
        raise ValueError("Genealogy lacks current document")
    depth = {i: 0 for i in nodes}
    pending = set(nodes)
    while pending:
        ready = sorted(
            i for i in pending if all(edge["parent"] not in pending for edge in graph["edges"] if edge["child"] == i)
        )
        if not ready:
            raise ValueError("Invalid genealogy cycle")
        for i in ready:
            parents = [edge["parent"] for edge in graph["edges"] if edge["child"] == i]
            if any(p not in nodes for p in parents):
                raise ValueError("Unknown genealogy endpoint")
            depth[i] = max([depth[p] + 1 for p in parents] or [0])
            pending.remove(i)

    def date(i):
        n = nodes[i]
        return docs[i]["date"]["value"] if n["kind"] == "public" else n.get("month")

    ordered = sorted(nodes, key=lambda i: (date(i) or "9999", depth[i], i))
    positions = {i: (30 + depth[i] * 300, 30 + row * 118) for row, i in enumerate(ordered)}
    width, height = 300 + max(depth.values()) * 300, 30 + len(nodes) * 118
    if len(nodes) == 1:
        # Keep a lone node at the same readable scale as a multi-node map.
        width, height = 760, 350
        positions[current] = (260, 133)
    svg = '<svg class="genealogy" role="group" aria-label="{}" viewBox="0 0 {} {}" data-width="{}" data-height="{}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'.format(
        t["scope"], width, height, width, height
    )
    edge_markers = ""
    for edge in graph["edges"]:
        x, y = positions[edge["parent"]]
        u, v = positions[edge["child"]]
        svg += f'<path class="edge" marker-end="url(#arrow)" d="M {x + 240} {y + 42} C {x + 275} {y + 42}, {u - 35} {v + 42}, {u} {v + 42}"/>'
        labels = [q["translations"][lang] for q in edge["questions"] if lang in q["translations"]]
        if edge["change_note"].get(lang):
            labels.append(edge["change_note"][lang])
        if labels:
            description = " · ".join(labels)
            mx, my = (x + 240 + u) / 2, (y + v) / 2 + 42
            edge_markers += f'<g class="edge-info" tabindex="0" role="button" aria-label="{e(description)}" data-edge-note="{e(description)}" transform="translate({mx} {my})"><title>{e(description)}</title><circle r="12"/><text text-anchor="middle" y="5">i</text></g>'
    textlist = {}
    for i in ordered:
        n = nodes[i]
        x, y = positions[i]
        title = docs[i]["translations"][lang]["title"] if n["kind"] == "public" else t["private"]
        label = t["current"] if i == current else (t["private"] if n["kind"] != "public" else "")
        href = base + lang + "/posts/" + docs[i]["slug"] + "/" if n["kind"] == "public" else None
        date_label = date(i) or t["unknown"]
        svg += '<g class="node {}" {} transform="translate({} {})">'.format(
            "current" if i == current else "", 'data-current="true"' if i == current else "", x, y
        )
        if href:
            svg += f'<a href="{href}" aria-label="{e(title)}">'
        # A truncated title is still readable on hover, without leaving the map.
        svg += f"<title>{e(title)}</title>"
        svg += f'<rect width="240" height="84" rx="4"/><text x="14" y="22" class="node-date">{e(date_label)} {e(label)}</text>'
        # SVG title is available in full through its accessible link and text list.
        lines = textwrap.wrap(title, width=28 if lang == "en" else 17)
        if len(lines) > 2:
            lines = lines[:2]
            lines[-1] += "…"
        for row, part in enumerate(lines):
            if part:
                svg += f'<text x="14" y="{44 + row * 19}">{e(part)}</text>'
        if href:
            svg += "</a>"
        svg += "</g>"
        textlist[i] = "<li>{} <small>{} {}</small></li>".format(
            '<a href="' + href + '">' + e(title) + "</a>" if href else e(title), e(date_label), e(label)
        )
    svg += edge_markers + "</svg>"
    grouped = ""
    for level in sorted(set(depth.values())):
        members = sorted((i for i in nodes if depth[i] == level), key=lambda i: (date(i) or "9999", i))
        label = f"{level + 1}단계" if lang == "ko" else f"Level {level + 1}"
        grouped += (
            '<section class="genealogy-level"><h3>'
            + label
            + "</h3><ul>"
            + "".join(textlist[i] for i in members)
            + "</ul></section>"
        )
    controls = "".join(
        f'<button type="button" data-map="{action}" aria-label="{t[key]}">{label}</button>'
        for action, key, label in [
            ("in", "zoomin", "+"),
            ("out", "zoomout", "−"),
            ("fit", "fit", t["fit"]),
            ("center", "center", t["center"]),
        ]
    )
    return (
        ("<p>" + t["alone"] + "</p>" if len(nodes) == 1 else "")
        + '<div class="map-controls">'
        + controls
        + '</div><p class="map-help">'
        + t["maphelp"]
        + '</p><div class="map-surface"><div class="map-viewport" tabindex="0" role="region" aria-label="'
        + t["scope"]
        + '">'
        + svg
        + '</div><p class="edge-tooltip" role="status" hidden></p></div><details><summary>'
        + t["posts"]
        + "</summary>"
        + grouped
        + "</details>"
    )

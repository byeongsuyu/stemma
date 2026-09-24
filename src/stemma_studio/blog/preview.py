"""Read-only, memory-only loopback preview; never a deployment server."""

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .render import CSP, render_site

SAMPLE = Path(__file__).parent / "sample"


def static_files(public, assets=None, base="/blog/", preview=False, site=None):
    files = render_site(public, assets, base, preview, site)
    frontend = Path(__file__).parent / "frontend"
    for name in ("site.css", "site.js", "theme.css"):
        files[name] = (frontend / name).read_bytes()
    for name in ("MaruBuri-Regular.woff2", "MaruBuri-Bold.woff2", "OFL.txt"):
        files["fonts/" + name] = (frontend / "fonts" / name).read_bytes()
    return files


def fixture_public():
    public = json.loads((SAMPLE / "public-v3.json").read_text())
    titles = [
        ("다시 읽는다는 것", "On reading again"),
        ("어느 오후의 단상", "An afternoon note"),
        ("첫 문장 앞에서", "Before the first sentence"),
        ("생각이 만나는 자리", "Where thoughts meet"),
    ]
    for i, doc in enumerate(public["documents"]):
        for lang, title in zip(("ko", "en"), titles[i]):
            doc["translations"][lang]["title"] = title
            doc["translations"][lang]["summary"] = (
                "이전의 생각에 질문을 건네는 가상의 글입니다."
                if lang == "ko"
                else "A fictional note that asks a new question of an earlier thought."
            )
            paragraph = (
                "한 번 읽은 글을 다시 펼친다. 문장은 그대로인데, 그 문장을 읽는 나는 조금 달라졌다. 기록은 생각을 끝내기보다 다음 질문이 시작될 자리를 남긴다."
                if lang == "ko"
                else "I open a text I have read before. The sentences remain, but the person reading them has changed a little. Writing leaves a place for the next question to begin."
            )
            doc["translations"][lang]["body"] = (
                "## "
                + ("남겨 둔 질문" if lang == "ko" else "A question left open")
                + "\n\n"
                + paragraph
                + "\n\n> "
                + paragraph
                + "\n\n"
                + "**"
                + ("다시 읽기" if lang == "ko" else "Reading again")
                + "**\n\n"
                + (paragraph + "\n\n") * 10
                + "[다른 글 / Another post](post:post-c)\n"
            )
    for i, series in enumerate(public["series"]):
        series["translations"]["ko"]["title"] = ["읽기와 쓰기", "생각의 갈래"][i]
        series["translations"]["en"]["title"] = ["Reading & writing", "Paths of thought"][i]
    for doc in public["documents"]:
        for lang, value in doc["translations"].items():
            intro = (
                "기록은 끝맺음보다 다음 질문에 가깝다. 어제의 문장을 다시 읽을 때, 우리는 같은 생각의 다른 면을 발견한다."
                if lang == "ko"
                else "Writing leaves room for the next question. Returning to an old sentence, we find another side of a familiar thought."
            )
            value["body"] = intro + "\n\n" + value["body"]
    specimen = public["documents"][1]
    for lang, value in specimen["translations"].items():
        heading = "수식과 표의 조판" if lang == "ko" else "Mathematics and tables"
        value["body"] = (
            value["body"].split("## ")[0]
            + "## "
            + heading
            + "\n\n"
            + r"함수 $f(x)=x^2$의 변화율은 \(f'(x)=2x\)로 쓴다."
            + "\n\n"
            + r"""$$
\int_0^1 x^2\,dx=\left[\frac{x^3}{3}\right]_0^1=\frac{1}{3}
$$

| 구분 / Method | 표현 / Expression | 값 / Value |
| :--- | :---: | ---: |
| 미분 / Derivative | $f'(x)$ | $2x$ |
| 정적분 / Integral | $\int_0^1 f(x)\,dx$ | $1/3$ |

$$
\begin{aligned}
A&=\begin{pmatrix}1&2\\3&4\end{pmatrix}\\
\det A&=1\cdot4-2\cdot3=-2
\end{aligned}
$$

> 짧은 문단과 절제된 여백으로 긴 글의 호흡을 유지합니다.

"""
            + value["body"]
        )
    return public


def handler(files, base, port):
    class PreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") not in ("127.0.0.1:" + str(port), "localhost:" + str(port)):
                self.send_error(403)
                return
            path = unquote(urlsplit(self.path).path)
            key = path[len(base) :] if path.startswith(base) else None
            if key == "" or (key is not None and key.endswith("/")):
                key += "index.html"
            found = key in files
            data = files[key] if found else files["404.html"]
            self.send_response(200 if found else 404)
            self.send_header(
                "Content-Type",
                (mimetypes.guess_type(key or "")[0] if found else "text/html") or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP + "; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_HEAD = do_GET

    return PreviewHandler


def main():
    parser = argparse.ArgumentParser(description="Memory-only blog preview on loopback")
    parser.add_argument("--base", default="/blog/")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    files = static_files(fixture_public(), base=args.base, preview=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(files, args.base, args.port))
    print(f"Local preview: http://127.0.0.1:{args.port}{args.base}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""The website: every report, RFC, study README and page of the current
design as HTML, with an index, full-text search and the browser tools, for
GitHub Pages.

    heron site [--out DIR] [--apps] [--serve] [--port N]

Pages mirror the repository: reports/0028-rfc-draft-2-isa.md becomes
reports/0028-rfc-draft-2-isa.html, a README its folder's index.html, and
the reports index (reports/README.md) the site's own index.html. Links
between rendered files stay relative, so the site works under any URL
prefix or straight from disk; links to anything else (code, data,
folders) go to GitHub at main. site.css is the look and site.js the
behaviour (filters, search, highlighting); every page reads without the
script.

--apps also builds the browser tools (the schematic viewer, the reference
cards), which takes a few minutes. .github/workflows/pages.yml publishes
the site from main, with them.

Needs markdown-it-py and mdit-py-plugins: pip install -e '.[site]'.
"""

import argparse
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.parse

from heron import BUILD, ROOT, meta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "site")
GH = "https://github.com/aiju/heron"
FONTS = ("https://fonts.googleapis.com/css2?family=Libre+Franklin:ital,wght@0,400..900;1,400..700"
         "&family=Newsreader:ital,opsz,wght@0,6..72,400..700;1,6..72,400..600"
         "&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap")
MATHJAX = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
MARKER = ".heron-site"

# Generated pages that stand in for a Markdown file of the repository.
GENERATED = {"reports/README.md": "index.html", "studies/README.md": "studies/index.html"}


def missing():
    """What `heron site` needs that isn't installed, or None."""
    try:
        import markdown_it  # noqa: F401
        import mdit_py_plugins  # noqa: F401
    except ImportError:
        return "heron site needs markdown-it-py and mdit-py-plugins: pip install -e '.[site]'"
    return None


def slug(text):
    """GitHub's anchor for a heading, as tests/test_repository.py checks them."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def markdown():
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.dollarmath import dollarmath_plugin
    from mdit_py_plugins.footnote import footnote_plugin

    def math(content, opts):
        content = html.escape(content)
        return f"\\[{content}\\]" if opts.get("display_mode") else f"\\({content}\\)"

    return (MarkdownIt("commonmark", {"html": True})
            .enable(["table", "strikethrough"])
            .use(footnote_plugin)
            .use(dollarmath_plugin, renderer=math, double_inline=True)
            .use(anchors_plugin, min_level=1, max_level=6, slug_func=slug))


def esc(s):
    return html.escape(str(s), quote=True)


def date(s):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)$", str(s))
    return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m else esc(s)


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def show(commit, path):
    """A file's bytes at a commit, or None."""
    r = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def inline_text(tok):
    """A heading's text, as GitHub reads it for the anchor."""
    out = []
    for c in tok.children or []:
        if c.type in ("text", "code_inline"):
            out.append(c.content)
        elif c.type in ("softbreak", "hardbreak"):
            out.append(" ")
    return "".join(out)


def plain(body):
    """Rendered HTML as plain text, for the abstracts and the search."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def rel(target, page):
    """The URL of one site path from the page at another."""
    return posixpath.relpath(target, posixpath.dirname(page) or ".")


def sources():
    """{repository path: site path} for every Markdown file the site renders."""
    pages = {"README.md": "about.html"}
    for path, _ in meta.reports():
        name = os.path.basename(path)
        pages[f"reports/{name}"] = f"reports/{name[:-3]}.html"
        if os.path.isdir(path[:-3]):
            for f in sorted(os.listdir(path[:-3])):
                if f.endswith(".md"):
                    pages[f"reports/{name[:-3]}/{f}"] = f"reports/{name[:-3]}/{f[:-3]}.html"
    for name in meta.studies():
        pages[f"studies/{name}/README.md"] = f"studies/{name}/index.html"
    for f in sorted(os.listdir(os.path.join(ROOT, "docs"))):
        if f.endswith(".md"):
            pages[f"docs/{f}"] = "docs/index.html" if f == "README.md" else f"docs/{f[:-3]}.html"
    return pages


STUB = re.compile(r"Reserved; being written on the branch `([^`]+)`")
SECNO = re.compile(r'<h([1-6]) id="([^"]*)">(Part [IVX]+|\d+(?:\.\d+)*\.?)(:?)\s+')
FIGURE = re.compile(r'<p>(<img [^>]*alt="([^"]*)"[^>]*>)</p>')


class Site:
    def __init__(self, out):
        self.out = out
        self.md = markdown()
        self.pages = sources()
        self.targets = {**self.pages, **GENERATED}
        self.images = set()
        self.rendered = {}
        self.refs = {}
        self.commit = git("rev-parse", "--short", "HEAD") or "main"
        self.built = git("log", "-1", "--format=%cs")
        with open(os.path.join(HERE, "heron.svg")) as f:
            svg = f.read().strip()
        self.heron = re.sub(r' xmlns="[^"]*"', "", svg)
        self.favicon = svg.replace(">", "><style>svg{color:#171615}@media (prefers-color-scheme:dark){svg{color:#ECE7DE}}</style>", 1)
        self.docs = []
        for path, fm in meta.reports():
            name = os.path.basename(path)
            d = {"src": f"reports/{name}", "path": self.pages[f"reports/{name}"],
                 "type": "ideas" if "-rfc-ideas-" in name else fm["type"], "status": fm["status"],
                 "subs": [s for s in self.pages if s.startswith(f"reports/{name[:-3]}/")]}
            self.describe(d, fm)
            self.docs.append(d)
        self.by_no = {d["n"]: d for d in self.docs}
        self.studies = meta.studies()
        self.branch = {}        # repository path -> (commit, branch) for files read from a branch
        self.branch_text = {}   # repository path -> its text there

    @staticmethod
    def describe(d, fm):
        """A document's number, title and context, from its front matter."""
        ctx = fm.get("context") if isinstance(fm.get("context"), dict) else {}
        d.update({
            "n": f"{fm['number']:04d}", "label": "RFC" if fm["type"] == "rfc" else "Report",
            "title": fm["title"], "date": fm.get("date", ""),
            "sup": f"{int(fm['superseded-by']):04d}" if fm.get("superseded-by") else None,
            "studies": ctx.get("studies") or [], "commit": str(ctx.get("commit", "")).split(" ")[0],
            "discussion": fm.get("discussion"),
        })

    def fetch_drafts(self):
        """Drafts reserved on main and being written on a branch: read them,
        and their folders, from the branch, so the site shows the work so
        far. A branch that can't be fetched leaves the stub."""
        shallow = git("rev-parse", "--is-shallow-repository") == "true"
        for d in self.docs:
            if d["status"] != "draft":
                continue
            with open(os.path.join(ROOT, d["src"])) as f:
                m = STUB.search(f.read())
            if not m:
                continue
            branch = m.group(1)
            r = subprocess.run(["git", "fetch", "--quiet", *(["--depth=1"] if shallow else []),
                                "origin", f"refs/heads/{branch}"], cwd=ROOT, capture_output=True, text=True)
            if r.returncode:
                print(f"{d['label']} {d['n']}: can't fetch {branch}; showing the stub", file=sys.stderr)
                continue
            sha = git("rev-parse", "FETCH_HEAD")
            # A new title or type renames the file: find it by its number.
            there = d["src"]
            if show(sha, there) is None:
                for f in git("ls-tree", "--name-only", sha, "--", "reports/").split("\n"):
                    m = meta.REPORT_RE.match(posixpath.basename(f))
                    if m and m.group(4) and m.group(1) == d["n"]:
                        there = f
            text = show(sha, there)
            if text is None or STUB.search(text.decode(errors="replace")):
                continue
            text = text.decode()
            fm = meta.parse_front_matter(text) or {}
            if fm.get("number") == int(d["n"]) and fm.get("title") and fm.get("type") in meta.STATUSES:
                self.describe(d, fm)
                d["type"] = "ideas" if "-rfc-ideas-" in there else fm["type"]
            # The page keeps the stub's address, which main links to; links
            # to the name on the branch land on it too.
            d["branch"], d["sha"], d["there"] = branch, sha, there
            self.branch[d["src"]], self.branch_text[d["src"]] = (sha, branch), text
            self.branch[there] = (sha, branch)
            self.targets.setdefault(there, d["path"])
            folder = there[:-3]
            for f in git("ls-tree", "-r", "--name-only", sha, "--", folder + "/").split("\n"):
                if not f:
                    continue
                self.branch[f] = (sha, branch)
                if f.endswith(".md") and f.count("/") == 2:
                    self.branch_text[f] = show(sha, f).decode()
                    self.pages[f] = self.targets[f] = f[:-3] + ".html"
                    if f not in d["subs"]:
                        d["subs"].append(f)

    # -------------------------------------------------------------- rendering

    def url(self, src, href, links):
        """A link in the repository file src, as a URL from src's page."""
        if re.match(r"[a-z][a-z0-9+.-]*:", href) or href.startswith("//"):
            return href
        path, sep, anchor = href.partition("#")
        if not path:
            return sep + anchor
        target = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
        readme = "README.md" if target == "." else posixpath.join(target, "README.md")
        site = self.targets.get(target) or self.targets.get(readme)
        if site:
            links.add(site)
            return rel(site, self.pages[src]) + sep + anchor
        ref = self.branch[src][1] if src in self.branch else "main"
        kind = "tree" if os.path.isdir(os.path.join(ROOT, target)) else "blob"
        return f"{GH}/{kind}/{ref}/{target}{sep}{anchor}"

    def image(self, src, url):
        if re.match(r"[a-z][a-z0-9+.-]*:", url) or url.startswith("//"):
            return url
        target = posixpath.normpath(posixpath.join(posixpath.dirname(src), url))
        if not (src in self.branch and target in self.branch) and not os.path.isfile(os.path.join(ROOT, target)):
            return url
        self.images.add(target)
        return rel(target, self.pages[src])

    def render(self, src):
        """A Markdown file of the repository as the body of its page."""
        text = self.branch_text.get(src)
        if text is None:
            with open(os.path.join(ROOT, src)) as f:
                text = f.read()
        if text.startswith("---\n"):
            text = text[text.index("\n---\n", 3) + 5:]
        tokens = self.md.parse(text)
        title, toc, h1, title_id = None, [], None, ""
        for i, t in enumerate(tokens):
            if t.type == "heading_open":
                words = inline_text(tokens[i + 1])
                if t.tag == "h1" and title is None:
                    title, h1, title_id = words, i, t.attrs.get("id", "")
                elif t.tag in ("h2", "h3"):
                    toc.append((int(t.tag[1]), t.attrs.get("id", ""), words))
        if h1 is not None:
            del tokens[h1:h1 + 3]
        body = self.md.renderer.render(tokens, self.md.options, {})

        def secno(m):
            hang = " hang" if m.group(3)[0].isdigit() and m.group(1) in "23" else ""
            return f'<h{m.group(1)} id="{m.group(2)}"><span class="secno{hang}">{m.group(3)}</span> '
        body = SECNO.sub(secno, body)
        figures = iter(range(1, 1000))
        body = FIGURE.sub(lambda m: f'<figure>{m.group(1)}<figcaption><span class="fig">Figure {next(figures)}</span> '
                                    f'{m.group(2)}</figcaption></figure>', body)
        body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        links = set()
        body = re.sub(r'(<img [^>]*?)src="([^"]*)"',
                      lambda m: f'{m.group(1)}src="{esc(self.image(src, html.unescape(m.group(2))))}"', body)

        def href(m):
            url = self.url(src, html.unescape(m.group(1)), links)
            ext = ' class="ext"' if url.startswith(("http:", "https:")) else ""
            return f'href="{esc(url)}"{ext}'
        body = re.sub(r'href="([^"]*)"', href, body)
        first = next((p for p in re.findall(r"<p>(.*?)</p>", body, re.S) if "<img" not in p), "")
        return {"html": body, "title": title or src, "title_id": title_id, "toc": toc, "links": links,
                "math": 'class="math ' in body, "text": plain(body), "abstract": plain(first)}

    # -------------------------------------------------------------- labels

    def label(self, path):
        """(number, what it is, title) of a site page, for cross-references."""
        for d in self.docs:
            if d["path"] == path:
                return d["n"], f"{d['label']} {d['n']}", d["title"]
        src = next((s for s, p in self.pages.items() if p == path), None)
        r = self.rendered.get(src, {})
        if m := re.match(r"reports/(\d{4})-", src or ""):
            d = self.by_no[m.group(1)]
            return d["n"], f"{d['label']} {d['n']} ›", r.get("title", src)
        if m := re.match(r"studies/([a-z0-9_]+)/", src or ""):
            return "", f"Study {m.group(1)}", r.get("title", src)
        if (src or "").startswith("docs/"):
            return "", "Design", r.get("title", src)
        return "", "About", r.get("title", "Heron")

    # -------------------------------------------------------------- pieces

    def shell(self, path, title, body, nav=None, description="", math=False, src=None, ref="main", cls=""):
        root = "../" * path.count("/")

        def cur(k):
            return ' aria-current="page"' if nav == k else ""
        head = ""
        if math:
            head = ('<script>window.MathJax = { tex: { inlineMath: [["\\\\(", "\\\\)"]], '
                    'displayMath: [["\\\\[", "\\\\]"]] }, svg: { fontCache: "global" } };</script>\n'
                    f'<script src="{MATHJAX}" defer></script>\n')
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{f'<meta name="description" content="{esc(description[:300])}">' if description else ""}
<link rel="icon" href="{root}heron.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{root}site.css">
<script src="{root}site.js" defer></script>
{head}</head>
<body data-root="{root}"{f' data-src="{esc(src)}" data-ref="{esc(ref)}"' if src else ""}{f' class="{cls}"' if cls else ""}>
<header class="mast gutter">
  <div class="mast-in wrap">
    <a class="brand" href="{root}index.html" aria-label="Heron Reference Library: the index">{self.heron}<span class="wm">heron</span><span class="lib">Reference Library</span></a>
    <nav aria-label="Sections">
      <a href="{root}index.html"{cur("library")}>Reports &amp; RFCs</a>
      <a href="{root}docs/index.html"{cur("design")}>Design</a>
      <a href="{root}studies/index.html"{cur("studies")}>Studies</a>
      <a href="{root}apps/index.html"{cur("apps")}>Apps</a>
    </nav>
    <form class="find" role="search" action="{root}index.html" method="get"><input id="q" name="q" type="search" autocomplete="off" spellcheck="false" placeholder="Search all documents" aria-label="Search all documents"><kbd>/</kbd></form>
  </div>
</header>
<main class="gutter">
{body}
</main>
<footer class="colophon gutter">
  <div class="colophon-in wrap">
    <span class="left">{self.heron}<span>Built from <a href="{GH}/tree/{esc(self.commit)}">{esc(self.commit)}</a>{f" on {date(self.built)}" if self.built else ""}</span></span>
    <a href="{GH}">aiju/heron on GitHub</a>
  </div>
</footer>
</body>
</html>
"""

    def chip(self, status):
        return f'<span class="chip {esc(status)}">{esc(status)}</span>'

    def toc(self, entries):
        items = []
        for level, anchor, words in entries:
            m = re.match(r"(\d+(?:\.\d+)*)\.?\s+(.*)$", words)
            no, words = (m.group(1), m.group(2)) if m else (None, words)
            num = f'<span class="t-no">{esc(no)}</span>' if no else ""
            items.append(f'<li class="l{level}{"" if no else " nonum"}"><a href="#{esc(anchor)}">{num}<span>{esc(words)}</span></a></li>')
        return f'<ol class="toc">{"".join(items)}</ol>'

    def xref(self, paths, here):
        items = []
        for p in paths:
            no, what, title = self.label(p)
            text = title if no else f"{what} · {title}"
            n = f'<span class="x-n">{no}</span>' if no else ""
            items.append(f'<li><a href="{esc(rel(p, here))}" class="{"" if no else "nonum"}" title="{esc(what + ": " + title)}">'
                         f'{n}<span class="x-t">{esc(text)}</span></a></li>')
        return f'<ul class="xref">{"".join(items)}</ul>'

    def section(self, label, inner, count=None):
        n = f"<span>{count}</span>" if count is not None else ""
        return f'<section><p class="label"><span>{esc(label)}</span>{n}</p>{inner}</section>'

    def document(self, src, head, side=(), after="", listed=()):
        """A rendered file's page: its contents, cross-references and text.
        listed: pages the side already links to, left out of the references."""
        path, r = self.pages[src], self.rendered[src]
        toc = [t for t in r["toc"] if t[0] == 2 or len(r["toc"]) < 70]
        parts = [self.section("Contents", self.toc(toc))] if toc else []
        parts += side
        refs = sorted(set(self.refs.get(path, ())) - set(listed), key=lambda p: (self.label(p)[0] == "", p))
        if refs:
            parts.append(self.section("Referenced by", self.xref(refs, path), len(refs)))
        aside = "".join(parts)
        mobile = (f'<details class="side-m"><summary class="label">Contents{" and references" if refs else ""}</summary>'
                  f'<div class="in">{aside}</div></details>') if parts else ""
        return f"""<article class="wrap"><div class="doc-grid">
<aside class="side" aria-label="Contents and cross-references">{aside}</aside>
<div class="doc-main"{f' id="{esc(r["title_id"])}"' if r["title_id"] else ""}>
{head}
{mobile}
<div class="prose" id="prose">
{r["html"]}</div>
{after}</div>
</div></article>"""

    def header(self, kind, title, meta_items=(), acts=(), extra="", top=""):
        meta_html = "".join(f"<span><b>{esc(k)}</b>{v}</span>" for k, v in meta_items if v)
        acts_html = "".join(f'<a href="{esc(u)}">{esc(t)}</a>' for t, u in acts if u)
        return f"""<header class="dh">
<div class="dh-top"><span class="kind">{esc(kind)}</span>{top}<span class="dh-acts">{acts_html}</span></div>
<h1>{esc(title)}</h1>
{f'<p class="dh-meta">{meta_html}</p>' if meta_html else ""}{extra}
</header>"""

    # -------------------------------------------------------------- pages

    def report_page(self, d):
        path = d["path"]
        studies = ", ".join(f'<a class="mono" href="{esc(rel(f"studies/{s}/index.html", path))}">{esc(s)}</a>'
                            if s in self.studies else f'<span class="mono">{esc(s)}</span>' for s in d["studies"])
        supersedes = [x for x in self.docs if x["sup"] == d["n"]]
        meta_items = [
            ("Date", date(d["date"])),
            ("Studies", studies),
            ("Context", f'<a class="mono" href="{GH}/commit/{esc(d["commit"])}">{esc(d["commit"])}</a>' if d["commit"] else ""),
            ("Supersedes", ", ".join(f'<a href="{esc(rel(x["path"], path))}">{x["label"]} {x["n"]}</a>' for x in supersedes)),
        ]
        ref, there = d.get("branch", "main"), d.get("there", d["src"])
        acts = [("Discussion", d["discussion"]), ("Source", f"{GH}/blob/{ref}/{there}"),
                ("History", f"{GH}/commits/{ref}/{there}"),
                ("Comment", f"{GH}/issues/new?title=" + urllib.parse.quote(f"{d['label']} {d['n']}: "))]
        extra = ""
        if d["status"] == "obsolete" and d["sup"] in self.by_no:
            s = self.by_no[d["sup"]]
            extra = (f'<p class="notice">Obsolete: superseded by <a href="{esc(rel(s["path"], path))}">'
                     f'{s["label"]} {s["n"]}, {esc(s["title"])}</a>.</p>')
        elif d.get("branch"):
            extra = (f'<p class="notice">Draft, from the branch <a class="mono" href="{GH}/tree/{esc(d["branch"])}">'
                     f'{esc(d["branch"])}</a> at <a class="mono" href="{GH}/commit/{d["sha"]}">{d["sha"][:7]}</a>: '
                     f'still being written, and not on main yet.</p>')
        elif d["status"] == "draft":
            extra = '<p class="notice">Draft: still being written, and it may change.</p>'
        head = self.header(f"{d['label']} {d['n']}", d["title"], meta_items, acts, extra, self.chip(d["status"]))
        side = []
        if d["subs"]:
            side.append(self.section("Supplements", self.xref([self.pages[s] for s in d["subs"]], path)))
        nos = [x["n"] for x in self.docs]
        i = nos.index(d["n"])
        cells = []
        for j, arrow in ((i - 1, "p"), (i + 1, "n")):
            if 0 <= j < len(nos):
                x = self.docs[j]
                lab = f"← {x['label']} {x['n']}" if arrow == "p" else f"{x['label']} {x['n']} →"
                cells.append(f'<a href="{esc(rel(x["path"], path))}" rel="{"prev" if arrow == "p" else "next"}">'
                             f'<span class="label">{lab}</span><span class="t">{esc(x["title"])}</span></a>')
            else:
                cells.append("<span></span>")
        pn = f'<nav class="pn" aria-label="Previous and next">{"".join(cells)}</nav>'
        r = self.rendered[d["src"]]
        body = self.document(d["src"], head, side, pn)
        self.write(path, self.shell(path, f"{d['label']} {d['n']}: {d['title']}", body, "library",
                                    r["abstract"], r["math"], there, ref))

    def sub_page(self, d, src):
        path, r = self.pages[src], self.rendered[src]
        meta_items = [("Part of", f'<a href="{esc(rel(d["path"], path))}">{d["label"]} {d["n"]}, {esc(d["title"])}</a>')]
        ref = self.branch[src][1] if src in self.branch else "main"
        acts = [("Source", f"{GH}/blob/{ref}/{src}"), ("History", f"{GH}/commits/{ref}/{src}")]
        head = self.header(f"{d['label']} {d['n']} · supplement", r["title"], meta_items, acts)
        others = [d["path"]] + [self.pages[s] for s in d["subs"] if s != src]
        body = self.document(src, head, [self.section("The rest of it", self.xref(others, path))])
        self.write(path, self.shell(path, f"{r['title']} · {d['label']} {d['n']}", body, "library",
                                    r["abstract"], r["math"], src, ref))

    def study_page(self, name, fm):
        src = f"studies/{name}/README.md"
        path, r = self.pages[src], self.rendered[src]
        uses = ", ".join(f'<a class="mono" href="{esc(rel(f"studies/{x}/index.html", path))}">{esc(x)}</a>'
                         for x in fm.get("depends-on") or [])
        meta_items = [("Command", f'<span class="mono">heron {esc(name)}</span>'), ("Uses", uses)]
        if fm.get("frozen-at"):
            meta_items.append(("Frozen at", f'<a class="mono" href="{GH}/tree/{esc(fm["frozen-at"])}">{esc(fm["frozen-at"])}</a>'))
        acts = [("Folder", f"{GH}/tree/main/studies/{name}"), ("History", f"{GH}/commits/main/studies/{name}")]
        status = fm.get("status", "")
        head = self.header(f"Study · {name}", r["title"], meta_items, acts,
                           top=f'<span class="lamp {esc(status)}">{esc(status)}</span>')
        reps = [self.by_no[f"{int(x):04d}"]["path"] for x in fm.get("reports") or [] if f"{int(x):04d}" in self.by_no]
        side = [self.section("Its reports", self.xref(reps, path))] if reps else []
        body = self.document(src, head, side, listed=reps)
        self.write(path, self.shell(path, f"{r['title']} · Heron", body, "studies", r["abstract"], r["math"], src))

    def plain_page(self, src, kind, nav):
        path, r = self.pages[src], self.rendered[src]
        acts = [("Source", f"{GH}/blob/main/{src}"), ("History", f"{GH}/commits/main/{src}")]
        side = []
        if src.startswith("docs/"):
            others = [p for s, p in self.pages.items() if s.startswith("docs/") and s != src]
            if others:
                side.append(self.section("Also in the design", self.xref(others, path)))
        body = self.document(src, self.header(kind, r["title"], (), acts), side)
        self.write(path, self.shell(path, f"{r['title']} · Heron", body, nav, r["abstract"], r["math"], src))

    def index_page(self):
        rows = []
        for d in sorted(self.docs, key=lambda d: d["n"], reverse=True):
            r = self.rendered[d["src"]]
            sup = (f'<span class="by">→ <a href="{esc(self.by_no[d["sup"]]["path"])}">{d["sup"]}</a></span>'
                   if d["sup"] in self.by_no else "")
            kind = {"rfc": "RFC", "ideas": "Ideas", "report": "Report"}[d["type"]]
            rows.append(f"""<tr data-type="{d["type"]}" data-status="{esc(d["status"])}" data-n="{d["n"]}" data-date="{esc(d["date"])}" data-title="{esc(d["title"].lower())}"{' class="is-obsolete"' if d["status"] == "obsolete" else ""}>
<td class="c-no">{d["n"]}</td><td class="c-kind"><span class="kind">{kind}</span></td>
<td class="c-title"><a href="{esc(d["path"])}">{esc(d["title"])}</a><span class="abs">{esc(r["abstract"])}</span></td>
<td class="c-st">{self.chip(d["status"])}{sup}</td>
<td class="c-studies"><span title="{esc(", ".join(d["studies"]))}">{" · ".join(esc(s) for s in d["studies"])}</span></td>
<td class="c-date">{date(d["date"])}</td></tr>""")

        def th(key, label, cls):
            sort = ' aria-sort="descending"' if key == "n" else ""
            inner = f'<button type="button" class="label" data-sort="{key}">{label}</button>' if key else f'<span class="label">{label}</span>'
            return f'<th class="{cls}"{sort}>{inner}</th>'
        body = f"""<div class="wrap">
<p class="intro">Heron is a 32-bit minicomputer to be built from 7400-series logic. Reports say what was done and found; RFCs propose what the machine should be and wait for a decision. Both share one numbering. <a href="about.html">About Heron</a> · <a href="docs/index.html">The current design</a></p>
<div id="libbody">
<div class="bar" id="bar" hidden></div>
<div class="tbl-wrap"><table class="dir" id="dir">
<thead><tr>{th("n", "No.", "c-no")}{th("", "Type", "c-kind")}{th("title", "Title", "c-title")}{th("status", "Status", "c-st")}{th("", "Studies", "c-studies")}{th("date", "Date", "c-date")}</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table></div>
</div>
<div id="results" hidden></div>
</div>"""
        self.write("index.html", self.shell("index.html", "Heron Reference Library", body, "library",
                                            "Reports and RFCs of Heron, a minicomputer built from 7400-series logic.",
                                            cls="index"))

    def studies_page(self):
        path = "studies/index.html"
        rows = []
        for name, fm in self.studies.items():
            r = self.rendered[f"studies/{name}/README.md"]
            reps = " ".join(f'<a href="{esc(rel(self.by_no[f"{int(x):04d}"]["path"], path))}">{int(x):04d}</a>'
                            for x in fm.get("reports") or [] if f"{int(x):04d}" in self.by_no)
            status = fm.get("status", "")
            rows.append(f"""<tr><td class="c-name">{esc(name)}</td>
<td class="c-title"><a href="{esc(name)}/index.html">{esc(r["title"])}</a></td>
<td class="c-st"><span class="lamp {esc(status)}">{esc(status)}</span></td>
<td class="c-refs">{reps}</td><td class="c-uses">{" · ".join(esc(x) for x in fm.get("depends-on") or [])}</td></tr>""")
        active = sum(1 for fm in self.studies.values() if fm.get("status") == "active")
        body = f"""<div class="wrap">
<div class="h-page"><h1>Studies</h1><span class="label">{len(self.studies)} studies · {active} active</span></div>
<p class="intro">Each study is one experiment: the code that builds or measures a design, run as <span class="mono">heron &lt;study&gt;</span>. Active studies run in the slow CI; frozen ones are kept as they last ran.</p>
<div class="tbl-wrap"><table class="dir studies">
<thead><tr><th class="c-name"><span class="label">Study</span></th><th class="c-title"><span class="label">Title</span></th><th class="c-st"><span class="label">Status</span></th><th class="c-refs"><span class="label">Reports</span></th><th class="c-uses"><span class="label">Uses</span></th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table></div>
</div>"""
        self.write(path, self.shell(path, "Studies · Heron", body, "studies"))

    def apps_page(self):
        path = "apps/index.html"
        items = []
        for app in APPS:
            have = [(t, f) for t, f in app["files"] if os.path.exists(os.path.join(self.out, "apps", f))]
            shot = app["id"] + ".png"
            img = (f'<a class="shot" href="{esc(have[0][1])}"><img src="{esc(shot)}" alt="{esc(app["alt"])}" loading="lazy"></a>'
                   if have and os.path.exists(os.path.join(self.out, "apps", shot)) else "")
            links = "".join(f'<a class="btn{" ghost" if i else ""}" href="{esc(f)}">{esc(t)}</a>' for i, (t, f) in enumerate(have))
            if not have:
                links = '<span class="note">Not built in this copy of the site: <span class="mono">heron site --apps</span> builds it.</span>'
            items.append(f"""<article class="app{"" if img else " noshot"}">
{img}<div>
<span class="kind">{esc(app["kind"])}</span>
<h2>{esc(app["title"])}</h2>
<p>{esc(app["desc"])}</p>
<div class="acts">{links}<span class="cmd">{esc(app["cmd"])}</span></div>
</div>
</article>""")
        body = f"""<div class="wrap">
<div class="h-page"><h1>Apps</h1><span class="label">Built from the repository on every push to main</span></div>
<div class="apps">
{chr(10).join(items)}
</div>
</div>"""
        self.write(path, self.shell(path, "Apps · Heron", body, "apps"))

    # -------------------------------------------------------------- output

    def write(self, path, text, mode="w"):
        full = os.path.join(self.out, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, mode) as f:
            f.write(text)

    def build(self, apps=False, drafts=True):
        if os.path.isdir(self.out) and os.listdir(self.out):
            if not os.path.exists(os.path.join(self.out, MARKER)):
                raise RuntimeError(f"{self.out} isn't empty and wasn't built by heron site; not writing over it")
            for f in os.listdir(self.out):
                if f == "apps" and not apps:
                    continue  # tools built before, kept since they take minutes
                full = os.path.join(self.out, f)
                if os.path.isdir(full):
                    shutil.rmtree(full)
                else:
                    os.remove(full)
        os.makedirs(self.out, exist_ok=True)
        self.write(MARKER, "built by heron site; it rebuilds this folder\n")
        if drafts:
            self.fetch_drafts()
        for src in self.pages:
            self.rendered[src] = self.render(src)
        for src, r in self.rendered.items():
            here = self.pages[src]
            for target in r["links"]:
                for t in {target, re.sub(r"(reports/\d{4}-[a-z0-9-]+)/.*$", r"\1.html", target)}:
                    if t != here and not here.startswith(t[:-5] + "/") and not t.startswith(here[:-5] + "/"):
                        self.refs.setdefault(t, set()).add(here)
        for d in self.docs:
            self.report_page(d)
            for s in d["subs"]:
                self.sub_page(d, s)
        for name, fm in self.studies.items():
            self.study_page(name, fm)
        for src in self.pages:
            if src.startswith("docs/"):
                self.plain_page(src, "The current design", "design")
        self.plain_page("README.md", "About", None)
        if apps:
            build_apps(os.path.join(self.out, "apps"))
        self.index_page()
        self.studies_page()
        self.apps_page()
        for img in self.images:
            os.makedirs(os.path.dirname(os.path.join(self.out, img)), exist_ok=True)
            if img in self.branch:
                self.write(img, show(self.branch[img][0], img) or b"", "wb")
            else:
                shutil.copy(os.path.join(ROOT, img), os.path.join(self.out, img))
        for f in ("site.css", "site.js"):
            shutil.copy(os.path.join(HERE, f), os.path.join(self.out, f))
        self.write("heron.svg", self.favicon + "\n")
        index = []
        for src, r in self.rendered.items():
            no, what, title = self.label(self.pages[src])
            d = self.by_no.get(no) if not what.endswith("›") else None
            extra = " ".join(d["studies"]) + " " + r["abstract"] if d else ""
            index.append({"u": self.pages[src], "id": what, "no": no, "title": title,
                          "meta": f"{what} {title} {extra}".lower(), "t": r["text"]})
        self.write("search.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")))
        return len(self.pages)


# ------------------------------------------------------------------ apps

def _schematic(out):
    from heron.infra.hw import schematic
    from heron.studies.v1b_system import machine
    from heron.studies.v1b_system.cli import CARDS
    page = schematic.page(machine.build(), "Heron draft 1b system", CARDS, standalone=True)
    with open(os.path.join(out, "schematic-1b.html"), "w") as f:
        f.write(page)
    return ["schematic-1b.html"]


def _refcards(out):
    from heron.studies.v1_isa import refcard
    made, chrome = [], refcard.find_chrome()
    for isa in ("v1b", "v1a"):
        page = os.path.join(out, f"refcard-{isa}.html")
        with open(page, "w") as f:
            f.write(refcard.build_html(isa))
        made.append(os.path.basename(page))
        if chrome:
            try:
                refcard.print_pdf(chrome, page, page[:-5] + ".pdf")
                made.append(os.path.basename(page)[:-5] + ".pdf")
            except (subprocess.SubprocessError, OSError) as e:
                print(f"  no PDF of {os.path.basename(page)}: {why(e)}", file=sys.stderr)
    return made


APPS = [
    {"id": "schematic-1b", "title": "Schematic viewer", "build": _schematic,
     "kind": "Hardware · draft 1b", "cmd": "heron v1b_system schematic",
     "desc": "Every card of the draft 1b system, one sheet per section of the design. Follow any net "
             "from its driver to every receiver, across sheets and cards.",
     "alt": "The schematic viewer's overview of the draft 1b system",
     "files": [("Open", "schematic-1b.html")]},
    {"id": "refcard-v1b", "title": "Quick reference cards", "build": _refcards,
     "kind": "Instruction set · drafts 1a and 1b", "cmd": "heron v1_isa refcard",
     "desc": "Opcodes, addressing modes, conditions and the system group on two printable A4 pages "
             "for each encoding, with examples run through the assembler.",
     "alt": "Page one of the draft 1b quick reference card",
     "files": [("Draft 1b", "refcard-v1b.html"), ("Draft 1a", "refcard-v1a.html"),
               ("1b PDF", "refcard-v1b.pdf"), ("1a PDF", "refcard-v1a.pdf")]},
]


def why(e):
    """A failed browser run, with the last thing it said."""
    err = getattr(e, "stderr", None) or b""
    last = (err.decode(errors="replace") if isinstance(err, bytes) else err).strip().splitlines()[-1:]
    return f"{e} ({last[0].strip()})" if last else str(e)


def screenshot(chrome, page, png):
    """A picture of a page's first screen, for the apps page. The PDFs and
    pictures need Chrome or Chromium (CHROME names one); without one, or if
    it fails, the apps are built without them."""
    cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,750",
           "--virtual-time-budget=8000", f"--screenshot={png}", "file://" + os.path.abspath(page)]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def build_apps(out):
    from heron.studies.v1_isa import refcard
    os.makedirs(out, exist_ok=True)
    chrome = refcard.find_chrome()
    for app in APPS:
        print(f"building {app['title'].lower()} ({app['cmd']})", flush=True)
        made = app["build"](out)
        if chrome and made:
            try:
                screenshot(chrome, os.path.join(out, made[0]), os.path.join(out, app["id"] + ".png"))
            except (subprocess.SubprocessError, OSError) as e:
                print(f"  no picture of {made[0]}: {why(e)}", file=sys.stderr)


# ------------------------------------------------------------------ command

def serve(out, port):
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=out)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {os.path.relpath(out)} at http://localhost:{port}/ (Ctrl-C stops)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="heron site", description="Build the website into build/site")
    p.add_argument("--out", default=OUT, help="where to write it (default build/site)")
    p.add_argument("--apps", action="store_true", help="also build the browser tools (a few minutes)")
    p.add_argument("--no-drafts", action="store_true",
                   help="show drafts' stubs, not the text on their branches (which needs a fetch)")
    p.add_argument("--serve", action="store_true", help="then serve it on localhost")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    if (msg := missing()):
        print(msg, file=sys.stderr)
        return 1
    try:
        n = Site(os.path.abspath(a.out)).build(a.apps, not a.no_drafts)
    except RuntimeError as e:
        print(f"heron site: {e}", file=sys.stderr)
        return 1
    print(f"wrote {n} pages to {os.path.relpath(a.out)}")
    return serve(os.path.abspath(a.out), a.port) if a.serve else 0

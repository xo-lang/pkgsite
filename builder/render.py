"""Static HTML pages for pkg.xolang.org (decision 0589).

Every text from a module (names, signatures, doc comments, file names) is
escaped; a doc comment's markdown is rendered to paragraphs, code spans and
code blocks only, never raw HTML or links from the module. Each symbol's
anchor is its exact name (`Client.get`), so links stay stable across
versions.
"""

import html
import re

from . import paths

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#5f6368;--line:#e3e3e6;--code:#f5f5f7;--link:#0b5cad}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececf0;--mut:#a0a0a8;--line:#2c2c31;--code:#1e1e22;--link:#7ab4ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:960px;margin:0 auto;padding:16px}
header.top{border-bottom:1px solid var(--line);padding:10px 16px}
header.top a{color:var(--fg);text-decoration:none;font-weight:600}
a{color:var(--link)}
h1{font-size:1.6rem;margin:.6em 0 .2em;overflow-wrap:anywhere}
h2{font-size:1.25rem;margin-top:2em;border-bottom:1px solid var(--line);padding-bottom:.2em}
h3{font-size:1.05rem;margin:1.6em 0 .3em;overflow-wrap:anywhere}
.meta{color:var(--mut);font-size:.9rem}
.meta span{margin-right:1.2em}
pre,code{font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{background:var(--code);padding:10px 12px;border-radius:6px;overflow-x:auto}
p code,li code{background:var(--code);padding:1px 4px;border-radius:4px}
.sym a.src{font-size:.85rem;font-weight:400;margin-left:.6em}
.note{border:1px solid var(--line);border-radius:6px;padding:10px 14px}
ul.idx{columns:2;padding-left:1.2em}
@media (max-width:640px){ul.idx{columns:1}}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def _inline(text):
    """Escaped text with `code` spans."""
    out = []
    for i, part in enumerate(re.split(r"(`[^`\n]+`)", text)):
        if i % 2 == 1:
            out.append("<code>%s</code>" % esc(part[1:-1]))
        else:
            out.append(esc(part))
    return "".join(out)


def doc_html(doc):
    """A doc comment as HTML: paragraphs, fenced or indented code blocks,
    and `-` lists."""
    if not doc:
        return ""
    out = []
    lines = doc.replace("\r\n", "\n").split("\n")
    i = 0
    para = []
    items = []

    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(l.strip() for l in para)))
            para.clear()
        if items:
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _inline(t) for t in items))
            items.clear()

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>%s</pre>" % esc("\n".join(block)))
            continue
        if line.startswith(("    ", "\t")) and not para and not items:
            flush()
            block = []
            while i < len(lines) and (lines[i].startswith(("    ", "\t")) or not lines[i].strip()):
                block.append(lines[i][4:] if lines[i].startswith("    ") else lines[i].lstrip("\t"))
                i += 1
            out.append("<pre>%s</pre>" % esc("\n".join(block).rstrip("\n")))
            continue
        if not line.strip():
            flush()
        elif re.match(r"^\s*[-*] ", line):
            if para:
                flush()
            items.append(re.sub(r"^\s*[-*] ", "", line))
        elif items and line.startswith("  "):
            items[-1] += " " + line.strip()
        else:
            if items:
                flush()
            para.append(line)
        i += 1
    flush()
    return "\n".join(out)


def href(path, version="", rel=""):
    """The URL of a module version's page (or a package in it, or with no
    version the module's latest-version redirect). R2 serves no directory
    index, so every link names index.html."""
    base = "/" + path + ("@" + version if version else "")
    return base + ("/" + rel if rel else "") + "/index.html"


def page(title, body, description=""):
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>%s</title>%s<style>%s</style></head><body>"
        "<header class=\"top\"><a href=\"/index.html\">pkg.xolang.org</a></header>"
        "<main>%s</main></body></html>\n"
    ) % (
        esc(title),
        "<meta name=\"description\" content=\"%s\">" % esc(description) if description else "",
        CSS,
        body,
    )


def _symbol(entry, src):
    name = entry.get("name", "")
    link = ""
    if src:
        link = " <a class=\"src\" href=\"%s\" rel=\"nofollow\">source</a>" % esc(src)
    parts = [
        "<div class=\"sym\"><h3 id=\"%s\">%s%s</h3>" % (esc(name), _inline("`%s`" % name), link),
        "<pre>%s</pre>" % esc(entry.get("signature", "")),
        doc_html(entry.get("doc", "")),
    ]
    for ex in entry.get("examples") or []:
        code = ex.get("code", "") if isinstance(ex, dict) else str(ex)
        if code:
            parts.append("<pre>%s</pre>" % esc(code))
    parts.append("</div>")
    return "\n".join(parts)


def package_body(pkg, srcfn):
    """The HTML of one package's API: an index, then constants, types (with
    their methods) and functions, each anchored by its exact name. srcfn
    maps a pos dict to a source URL ("" for none)."""
    consts = sorted(pkg.get("constants") or [], key=lambda e: e.get("name", ""))
    types = sorted(pkg.get("types") or [], key=lambda e: e.get("name", ""))
    funcs = sorted(pkg.get("functions") or [], key=lambda e: e.get("name", ""))
    names = [c["name"] for c in consts]
    for t in types:
        names.append(t["name"])
        names += [m["name"] for m in sorted(t.get("methods") or [], key=lambda e: e.get("name", ""))]
    names += [f["name"] for f in funcs]
    out = []
    if names:
        out.append("<h2 id=\"index\">Index</h2><ul class=\"idx\">%s</ul>" % "".join(
            "<li><a href=\"#%s\">%s</a></li>" % (esc(n), esc(n)) for n in names))
    else:
        out.append("<p class=\"meta\">This package exports nothing.</p>")
    if consts:
        out.append("<h2 id=\"constants\">Constants</h2>")
        out += [_symbol(c, srcfn(c.get("pos"))) for c in consts]
    if types:
        out.append("<h2 id=\"types\">Types</h2>")
        for t in types:
            out.append(_symbol(t, srcfn(t.get("pos"))))
            for m in sorted(t.get("methods") or [], key=lambda e: e.get("name", "")):
                out.append(_symbol(m, srcfn(m.get("pos"))))
    if funcs:
        out.append("<h2 id=\"functions\">Functions</h2>")
        out += [_symbol(f, srcfn(f.get("pos"))) for f in funcs]
    return "\n".join(out)


def license_html(found, ok=True):
    if not found:
        return "<p class=\"meta\">License: none found</p>"
    return "<p class=\"meta\">License: %s</p>" % ", ".join(
        "%s (%s)" % (esc(spdx if spdx != "unknown" else "not recognized"), esc(name)) for name, spdx in found)


def no_license_body(path, version, found):
    what = "has no LICENSE file" if not found else "has a license file this site does not recognize"
    return (
        "<h1>%s</h1><p class=\"meta\"><span>%s</span></p>"
        "<div class=\"note\"><p>Documentation is not shown: this module version %s. "
        "pkg.xolang.org shows docs only for a version that carries a license the site recognizes "
        "(as pkg.go.dev does).</p></div>%s"
    ) % (esc(path), esc(version), what, license_html(found, False))


def get_line(path, version):
    return "<pre>xo get %s@%s</pre>" % (esc(path), esc(version))


def module_header(path, version, latest, found):
    vh = "/" + path + "/versions.html"
    tag = " (latest)" if version == latest else ' (<a href="%s">latest is %s</a>)' % (esc(href(path, latest)), esc(latest))
    return (
        "<h1>%s</h1><p class=\"meta\"><span>Version %s%s</span><span><a href=\"%s\">versions</a></span></p>%s%s"
    ) % (esc(path), esc(version), tag, esc(vh), license_html(found, True), get_line(path, version))


def versions_body(path, versions):
    items = "".join(
        "<li><a href=\"%s\">%s</a></li>" % (esc(href(path, v)), esc(v))
        for v in sorted(versions, key=paths.version_key, reverse=True))
    return "<h1>%s</h1><h2>Versions</h2><ul>%s</ul>" % (esc(path), items)


def redirect(target):
    t = esc(target)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta http-equiv=\"refresh\" content=\"0; url=%s\"><link rel=\"canonical\" href=\"%s\">"
        "<title>Redirect</title></head><body><a href=\"%s\">%s</a></body></html>\n"
    ) % (t, t, t, t)

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

# xolang.dev's palette and fonts (its assets/css/main.css): dark first,
# light by the reader's preference. The fonts load from xolang.dev, which
# serves them with Access-Control-Allow-Origin: *; system fonts until then.
SITE = "https://xolang.dev"
CSS = """
@font-face{font-family:"Space Grotesk";font-weight:300 700;font-display:swap;src:url("https://xolang.dev/fonts/space-grotesk-latin.woff2") format("woff2")}
@font-face{font-family:"JetBrains Mono";font-weight:100 800;font-display:swap;src:url("https://xolang.dev/fonts/jetbrains-mono-latin.woff2") format("woff2")}
:root{--bg:#14110f;--bg-2:#1c1815;--ink:#f1e6d6;--ink-2:#a8998a;--line:#342b24;--accent:#e8743b;--link:#f2b45a;--code:#211c18}
@media (prefers-color-scheme:light){:root{--bg:#faf6f0;--bg-2:#f2ebe1;--ink:#241d18;--ink-2:#6e6053;--line:#e2d6c6;--link:#a84f1c;--code:#f2ebe1}}
*{box-sizing:border-box}
html,body{margin:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{background:var(--bg);color:var(--ink);font:16px/1.6 "Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:0 16px}
a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
header.top{border-bottom:1px solid var(--line)}
header.top nav{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:14px 0}
header.top .brand{color:var(--ink);font-weight:700;font-size:20px;letter-spacing:-.01em;white-space:nowrap}
header.top .brand span{color:var(--accent)}
header.top ul{display:flex;gap:18px;list-style:none;margin:0;padding:0;font:500 13px "JetBrains Mono",ui-monospace,monospace}
header.top ul a{color:var(--ink-2)}
header.top ul a::before{content:"./";color:var(--accent);opacity:.7}
main{padding:8px 0 40px;overflow-wrap:anywhere}
pre{overflow-wrap:normal}
h1{font-size:1.7rem;line-height:1.2;letter-spacing:-.02em;margin:.8em 0 .3em;overflow-wrap:anywhere}
h2{font-size:1.25rem;margin-top:2em;border-bottom:1px solid var(--line);padding-bottom:.2em}
h3{font-size:1.05rem;margin:1.6em 0 .3em;overflow-wrap:anywhere}
.meta{color:var(--ink-2);font-size:.9rem}
.meta span{margin-right:1.2em}
pre,code{font:14px/1.45 "JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-ligatures:none}
pre{background:var(--code);border:1px solid var(--line);padding:10px 12px;border-radius:8px;overflow-x:auto}
p code,li code{background:var(--code);padding:1px 4px;border-radius:4px}
.sym a.src{font-size:.85rem;font-weight:400;margin-left:.6em}
.note{border:1px solid var(--line);border-radius:8px;padding:10px 14px}
ul.idx{columns:2;padding-left:1.2em}
ul.mods{list-style:none;padding:0}
ul.mods li{padding:6px 0;border-bottom:1px solid var(--line)}
ul.mods .meta{display:block}
.search{margin:1em 0}
.search input{width:100%;font:16px "JetBrains Mono",ui-monospace,monospace;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg-2);color:var(--ink)}
.search input:focus{outline:2px solid var(--accent);outline-offset:1px}
.search .hint{font-size:.8rem}
#results{list-style:none;padding:0}
#results li{padding:6px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
#results .kind{font:12px "JetBrains Mono",ui-monospace,monospace;color:var(--ink-2);margin-left:.6em}
footer{overflow-wrap:anywhere;border-top:1px solid var(--line);color:var(--ink-2);font:13px/1.6 "JetBrains Mono",ui-monospace,monospace;padding:24px 0 40px}
footer .links{display:flex;flex-wrap:wrap;gap:4px 16px}
footer p{margin:.6em 0 0}
@media (max-width:640px){ul.idx{columns:1}header.top ul{gap:12px}}
"""

# The trademark and non-affiliation line of each port repository (its
# README's), shown on that repository's module pages.
PORT_NOTICES = {
    "github.com/xo-lang/aws": "A community AWS SDK for the Xo language. Not affiliated with or endorsed by Amazon Web Services. AWS and Amazon Web Services are trademarks of Amazon.com, Inc. or its affiliates.",
    "github.com/xo-lang/azure": "A community Azure SDK for the Xo language. Not affiliated with or endorsed by Microsoft. Microsoft and Azure are trademarks of the Microsoft group of companies.",
    "github.com/xo-lang/gcp": "A community Google Cloud SDK for the Xo language. Not affiliated with or endorsed by Google. Google Cloud is a trademark of Google LLC.",
    "github.com/xo-lang/openai": "A community library for the Xo language. Not affiliated with or endorsed by OpenAI or Microsoft. OpenAI is a trademark of OpenAI; Azure is a trademark of the Microsoft group of companies.",
}

# What the footer says about the build: the xo release that rendered the
# pages and the day (UTC); set by build.main.
BUILD = {"xo": "", "date": ""}


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


def port_notice(path):
    """The trademark line of the port repository path is in, or ""."""
    for repo, text in PORT_NOTICES.items():
        if path == repo or path.startswith(repo + "/"):
            return text
    return ""


def repo_url(path):
    """The source repository of a module path on a known host, or ""."""
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] in ("github.com", "gitlab.com", "codeberg.org"):
        return "https://%s/%s/%s" % tuple(parts[:3])
    return ""


def footer(source="", license_note="", generated="", notice=""):
    """The footer every page carries: xolang.dev's links, the page's source
    repository, its license, how and when it was generated, and for a port
    its repository's trademark line."""
    # the repository the page comes from: xo-lang/xo for std and the
    # index, the module's own repository for a module page
    gh = ("GitHub xo-lang/xo", source or "https://github.com/xo-lang/xo")
    if source and not source.startswith("https://github.com/xo-lang/xo/"):
        gh = ("source " + "/".join(source.split("/")[2:5]) if source.count("/") >= 4 else "source", source)
        if source.startswith("https://github.com/"):
            gh = ("GitHub " + "/".join(source.split("/")[3:5]), source)
    links = [("xolang.dev", SITE + "/"), ("docs", SITE + "/docs/"), gh]
    out = ["<footer><div class=\"wrap\"><div class=\"links\">%s</div>" % "".join(
        "<a href=\"%s\">%s</a>" % (esc(u), esc(t)) for t, u in links)]
    for t in (license_note, generated, notice):
        if t:
            out.append("<p>%s</p>" % esc(t))
    out.append("</div></footer>")
    return "".join(out)


def inline_code(text):
    """text escaped, with `code` spans as <code>."""
    parts = text.split("`")
    if len(parts) % 2 == 0:
        return esc(text)
    return "".join(esc(x) if i % 2 == 0 else "<code>%s</code>" % esc(x) for i, x in enumerate(parts))


def generated_line(what):
    """"Generated from WHAT with Xo X.Y.Z on DAY", the parts BUILD has."""
    s = "Generated from %s" % what
    if BUILD.get("xo"):
        s += " with Xo %s" % BUILD["xo"]
    if BUILD.get("date"):
        s += " on %s" % BUILD["date"]
    return s + "."


def page(title, body, description="", foot=None, head=""):
    if foot is None:
        foot = footer(generated=generated_line("the published catalog") if BUILD.get("date") else "")
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"dark light\">"
        "<title>%s</title>%s<style>%s</style>%s</head><body>"
        "<header class=\"top\"><div class=\"wrap\"><nav><a class=\"brand\" href=\"/index.html\">pkg<span>.</span>xolang.org</a>"
        "<ul><li><a href=\"%s/\">xolang.dev</a></li><li><a href=\"%s/docs/\">docs</a></li>"
        "<li><a href=\"https://github.com/xo-lang/xo\">github</a></li></ul></nav></div></header>"
        "<main class=\"wrap\">%s</main>%s</body></html>\n"
    ) % (
        esc(title),
        "<meta name=\"description\" content=\"%s\">" % esc(description) if description else "",
        CSS,
        head,
        SITE,
        SITE,
        body,
        foot,
    )


# A std file's header comment, as xo's std_summary reads it
# (compiler/cli/core/doc.xo), without its 100 character cut.
_PORT_RE = re.compile(r"^((?:Go's )?[A-Za-z0-9][A-Za-z0-9.\-]*(?:/[A-Za-z0-9_.\-]+)+|Go's [A-Za-z0-9_.\-]+):\s+")


def std_paragraph(src, name=""):
    """The first paragraph of a std file's header comment that describes
    the module: without the `std/NAME (spec ...).` opening, the declaration
    file's boilerplate and a "Notes for this file:" block. A leading Go
    path (`golang.org/x/crypto/bcrypt: password hashes ...`) becomes a
    trailing "(port of golang.org/x/crypto/bcrypt)". "" when the header
    says nothing more."""
    lines = []
    for l in src.split("\n"):
        if not l.startswith("//"):
            break
        x = l[2:].strip()
        if not x or x.startswith("-"):
            break
        lines.append(x)
    text = " ".join(lines).strip()
    if text.startswith("std/"):
        i = text.find("). ")
        if i >= 0:
            text = text[i + 3:]
        elif name and text.startswith(name + ": "):
            text = text[len(name) + 2:]
    if text.startswith("Declaration file;"):
        i = text.find("prelude.xo. ")
        text = text[i + 12:] if i >= 0 else ""
    if text.startswith("Declaration file. "):
        text = text[len("Declaration file. "):]
    if text.startswith("Notes for this file:") or text == "Declaration file.":
        text = ""
    text = text.strip()
    m = _PORT_RE.match(text)
    if m:
        src_name = m.group(1)
        rest = text[m.end():]
        if rest:
            rest = rest[0].upper() + rest[1:]
            end = first_sentence(rest)
            text = end[:-1] + " (port of %s)." % src_name + rest[len(end):] if end.endswith(".") else rest + " (port of %s)" % src_name
    return text


def first_sentence(text):
    """text up to the end of its first sentence: a period, question or
    exclamation mark followed by a space and a capital, a backtick or the
    end. Never cut mid-word; the whole text when it has no such end."""
    m = re.search(r"[.!?](?=\s+[A-Z`(]|\s*$)", text)
    return text[:m.end()] if m else text


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
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"refresh\" content=\"0; url=%s\"><link rel=\"canonical\" href=\"%s\">"
        "<title>Redirect</title></head><body><a href=\"%s\">%s</a></body></html>\n"
    ) % (t, t, t, t)

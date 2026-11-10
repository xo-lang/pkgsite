"""pkg.xolang.org's builder (decision 0589): new module versions from the
index feed, or named ones, rendered into a static site.

    python3 -I -m builder.build --xo XO --work DIR --site DIR [options]

It reads index.xolang.org's feed from the position in --state (or the
versions named with --module), fetches each with the released xo through
XO_PROXY, checked against the checksum log XO_SUMDB by xo itself, finds its
license (no recognized license, no docs), runs `xo doc --json` for each
package with no network, and writes:

    site/<path>@<version>/index.html          the module's root package
    site/<path>@<version>/<pkg>/index.html    its other packages
    site/<path>/index.html                    a redirect to the latest version
    site/<path>/versions.html                 its versions
    site/std/<name>@<xo version>/index.html   std (--std)
    site/index.html, site/catalog.json, site/search/index.json

The catalog (what earlier runs built) comes from --catalog, normally the
published site's catalog.json, so a run renders only new versions but its
version lists and search index cover everything. The new position goes to
--state's position.json only with --advance.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

from . import license as lic
from . import paths
from . import render
from . import xotool

FEED_MAX = 2000
USER_AGENT = "xo-pkgsite-builder (+https://github.com/xo-lang/pkgsite)"


def http_get(url, timeout=60, limit=64 << 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("%s: answer over %d bytes" % (url, limit))
    return data


def read_feed(source, since):
    """(path, version, timestamp) from the index feed after since, in feed
    order. source is a URL or a file of JSON lines."""
    if source.startswith(("https://", "http://")):
        url = source + ("&" if "?" in source else "?") + urllib.parse.urlencode({"since": since})
        text = http_get(url).decode("utf-8")
    else:
        with open(source, encoding="utf-8") as f:
            text = f.read()
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        p, v, ts = rec.get("Path", ""), rec.get("Version", ""), rec.get("Timestamp", "")
        if not paths.valid_path(p) or not paths.valid_version(v):
            print("feed: skipping %r %r" % (p, v), file=sys.stderr)
            continue
        if since and ts and ts < since:
            continue
        out.append((p, v, ts))
        if len(out) >= FEED_MAX:
            break
    return out


def load_catalog(source):
    empty = {"schema": 1, "modules": {}}
    if not source:
        return empty
    try:
        if source.startswith(("https://", "http://")):
            data = json.loads(http_get(source).decode("utf-8"))
        elif os.path.exists(source):
            with open(source, encoding="utf-8") as f:
                data = json.load(f)
        else:
            return empty
    except Exception as e:  # a missing or unreadable catalog starts empty
        print("catalog: %s: %s (starting empty)" % (source, e), file=sys.stderr)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        return empty
    return data


def write(site, rel, text):
    p = os.path.join(site, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def build_version(tool, site, catalog, path, version):
    """Renders one module version; returns its catalog entry update."""
    mod = catalog["modules"].setdefault(path, {"versions": [], "builds": {}})
    try:
        d = tool.fetch(path, version)
    except Exception as e:
        print("fetch %s@%s: %s" % (path, version, e), file=sys.stderr)
        return False
    found = lic.detect(d)
    ok = lic.redistributable(found)
    if version not in mod["versions"]:
        mod["versions"].append(version)
    build = {"license": [s for _, s in found], "docs": ok, "packages": []}
    mod["builds"][version] = build
    latest = paths.latest(mod["versions"])
    if not ok:
        write(site, render.href(path, version)[1:], render.page(
            "%s@%s" % (path, version), render.no_license_body(path, version, found)))
        return True
    pkgs = xotool.packages(d)
    docs = {}
    walked = None
    try:
        walked = tool.doc_walk(d, path)
    except Exception as e:
        print("doc %s@%s ./...: %s (one package at a time)" % (path, version, e), file=sys.stderr)
    if walked is not None:
        # the packages the toolchain walks, as the builder finds them
        docs = {rel: ent for rel, ent in walked.items() if rel in pkgs}
    else:
        for rel in pkgs:
            try:
                entries = tool.doc(d, rel)
            except Exception as e:
                print("doc %s@%s %s: %s" % (path, version, rel or ".", e), file=sys.stderr)
                continue
            for ent in entries:
                docs[rel] = ent
    build["packages"] = sorted(docs)
    symbols = {}

    def srcfn(pos):
        if not pos or not pos.get("file"):
            return ""
        return paths.source_url(path, version, pos["file"], pos.get("line", 0))

    for rel, ent in docs.items():
        imp = path + ("/" + rel if rel else "")
        body = [render.module_header(path, version, latest, found)]
        if rel:
            body.insert(0, "<p class=\"meta\"><a href=\"%s\">%s</a></p>" % (
                render.esc(render.href(path, version)), render.esc(path)))
            body[1] = body[1].replace("<h1>%s</h1>" % render.esc(path), "<h1>%s</h1>" % render.esc(imp), 1)
        elif len(docs) > 1:
            body.append("<h2 id=\"packages\">Packages</h2><ul class=\"idx\">%s</ul>" % "".join(
                "<li><a href=\"%s\">%s</a></li>" % (render.esc(render.href(path, version, r)), render.esc(r))
                for r in sorted(docs) if r))
        body.append(render.package_body(ent, srcfn))
        write(site, render.href(path, version, rel)[1:], render.page("%s@%s" % (imp, version), "\n".join(body)))
        symbols[imp] = _symbol_names(ent)
    if "" not in docs:
        # a module whose root holds no package still gets a page
        body = [render.module_header(path, version, latest, found),
                "<h2 id=\"packages\">Packages</h2><ul class=\"idx\">%s</ul>" % "".join(
                    "<li><a href=\"%s\">%s</a></li>" % (render.esc(render.href(path, version, r)), render.esc(r))
                    for r in sorted(docs))]
        write(site, render.href(path, version)[1:], render.page("%s@%s" % (path, version), "\n".join(body)))
    build["symbols"] = symbols
    return True


def _symbol_names(ent):
    out = [c["name"] for c in ent.get("constants") or []]
    for t in ent.get("types") or []:
        out.append(t["name"])
        out += [m["name"] for m in t.get("methods") or []]
    out += [f["name"] for f in ent.get("functions") or []]
    return sorted(out)


def build_std(tool, site, catalog):
    ver = tool.version()
    if not ver:
        raise RuntimeError("xo version: no answer")
    v = "v" + ver
    std = catalog.setdefault("std", {})
    std["version"] = v
    std["modules"] = []
    for m in tool.std_list():
        name = m.get("module", "")
        if not name.startswith("std/"):
            continue
        try:
            entries = tool.std_doc(name)
        except Exception as e:
            print("doc %s: %s" % (name, e), file=sys.stderr)
            continue
        if not entries:
            continue

        def srcfn(pos):
            if not pos or not pos.get("file"):
                return ""
            return "https://github.com/xo-lang/xo/blob/%s/%s#L%d" % (v, pos["file"], pos.get("line", 0))

        body = ("<h1>%s</h1><p class=\"meta\"><span>Xo %s</span></p>%s%s" % (
            render.esc(name), render.esc(ver), render.doc_html(m.get("summary", "")),
            render.package_body(entries[0], srcfn)))
        write(site, render.href(name, v)[1:], render.page("%s (Xo %s)" % (name, ver), body))
        write(site, render.href(name)[1:], render.redirect(render.href(name, v)))
        std["modules"].append({"path": name, "summary": m.get("summary", ""), "symbols": _symbol_names(entries[0])})


def finish(site, catalog, touched):
    for path in sorted(touched):
        mod = catalog["modules"][path]
        latest = paths.latest(mod["versions"])
        write(site, path + "/index.html", render.redirect(render.href(path, latest)))
        write(site, path + "/versions.html", render.page("%s versions" % path, render.versions_body(path, mod["versions"])))
    # the home page and the search index cover the whole catalog
    items = []
    search = []
    for path in sorted(catalog["modules"]):
        mod = catalog["modules"][path]
        latest = paths.latest(mod["versions"])
        if not latest:
            continue
        items.append("<li><a href=\"%s\">%s</a> <span class=\"meta\">%s</span></li>" % (
            render.esc(render.href(path, latest)), render.esc(path), render.esc(latest)))
        b = mod.get("builds", {}).get(latest, {})
        for imp, syms in sorted((b.get("symbols") or {}).items()):
            search.append({"path": imp, "module": path, "version": latest, "symbols": syms})
    std = catalog.get("std", {})
    std_items = "".join("<li><a href=\"%s\">%s</a> <span class=\"meta\">%s</span></li>" % (
        render.esc(render.href(m["path"], std["version"])), render.esc(m["path"]), render.esc(m.get("summary", "")))
        for m in std.get("modules", []))
    for m in std.get("modules", []):
        search.append({"path": m["path"], "module": m["path"], "version": std["version"], "symbols": m.get("symbols", [])})
    body = "<h1>Xo packages</h1>"
    if std_items:
        body += "<h2 id=\"std\">Standard library (Xo %s)</h2><ul>%s</ul>" % (render.esc(std["version"][1:]), std_items)
    body += "<h2 id=\"modules\">Modules</h2><ul>%s</ul>" % ("".join(items) or "<li>none yet</li>")
    write(site, "index.html", render.page("pkg.xolang.org", body, "Documentation for Xo's standard library and published modules."))
    write(site, "catalog.json", json.dumps(catalog, sort_keys=True, separators=(",", ":")))
    write(site, "search/index.json", json.dumps({"schema": 1, "packages": search}, sort_keys=True, separators=(",", ":")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xo", required=True, help="the released xo binary")
    ap.add_argument("--work", required=True, help="scratch directory (module cache, xo's HOME)")
    ap.add_argument("--site", required=True, help="output directory")
    ap.add_argument("--state", default="state", help="directory of position.json")
    ap.add_argument("--feed", default="https://index.xolang.org/index", help="index feed URL, a JSON lines file, or none")
    ap.add_argument("--catalog", default="", help="catalog.json of earlier runs (URL or file); empty starts fresh")
    ap.add_argument("--proxy", default="https://proxy.xolang.org", help="XO_PROXY for fetching")
    ap.add_argument("--sumdb", default=os.environ.get("XO_SUMDB", ""), help="XO_SUMDB: <name>+<key id>+<public key>")
    ap.add_argument("--no-verify", action="store_true", help="fetch without the checksum log (local tests only)")
    ap.add_argument("--sandbox", choices=["none", "unshare"], default="none", help="run xo doc with no network (unshare)")
    ap.add_argument("--module", action="append", default=[], help="path@version to build instead of the feed")
    ap.add_argument("--std", action="store_true", help="render the xo's std")
    ap.add_argument("--advance", action="store_true", help="write the new feed position to --state")
    a = ap.parse_args(argv)

    fetching = not (a.std and not a.module and a.feed == "none")
    if fetching and not a.sumdb and not a.no_verify:
        ap.error("--sumdb (or XO_SUMDB) is required: versions are checked against the checksum log; --no-verify is for local tests")
    if a.sumdb and a.sumdb.strip() in ("off", ""):
        ap.error("--sumdb off: use --no-verify for local tests")
    tool = xotool.Tool(a.xo, a.work, a.proxy, "off" if a.no_verify else a.sumdb, a.sandbox)
    catalog = load_catalog(a.catalog)
    os.makedirs(a.site, exist_ok=True)
    pos_file = os.path.join(a.state, "position.json")
    pos = {}
    if os.path.exists(pos_file):
        with open(pos_file, encoding="utf-8") as f:
            pos = json.load(f)
    since = pos.get("since", "1970-01-01T00:00:00Z")

    if a.module:
        todo = []
        for m in a.module:
            p, _, v = m.partition("@")
            if not paths.valid_path(p) or not paths.valid_version(v):
                ap.error("--module %r: want <path>@<version>" % m)
            todo.append((p, v, ""))
    elif a.std or a.feed == "none":
        todo = []
    else:
        todo = read_feed(a.feed, since)

    failed = 0
    touched = set()
    last = since
    for p, v, ts in todo:
        built = catalog["modules"].get(p, {}).get("builds", {}).get(v)
        if built is None:
            if build_version(tool, a.site, catalog, p, v):
                touched.add(p)
            else:
                failed += 1
        if ts and ts > last:
            last = ts
    if a.std:
        build_std(tool, a.site, catalog)
    finish(a.site, catalog, touched)
    if a.advance and not a.module:
        os.makedirs(a.state, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(pos_file, "w", encoding="utf-8") as f:
            json.dump({"since": last, "heartbeat": now}, f, indent=2, sort_keys=True)
            f.write("\n")
    print("built %d version(s), %d failed, position %s" % (len(touched), failed, last))
    return 1 if failed and failed == len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())

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
    site/_doc/<path>/@v/<version>.json        its doc record (stage a; see --rebuild)
    site/index.html, site/catalog.json, site/search/index.json

The catalog (what earlier runs built) comes from --catalog, normally the
published site's catalog.json, so a run renders only new versions but its
version lists and search index cover everything. The new position goes to
--state's position.json only with --advance.
"""

import argparse
import datetime
import fnmatch
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


# A version that fails this many runs in a row is skipped, so one bad
# version cannot hold the feed position forever.
MAX_FAILURES = 3


def run_todo(todo, since, build_one, max_builds, failures):
    """Builds the feed entries in order. build_one(path, version) returns
    True (built), False (failed) or None (already built). At most
    max_builds builds run (0: no limit); the position then stops at the
    last entry taken, and the feed's since is inclusive, so the next run
    starts there and the catalog skips what is built. A failed version
    holds the position at its timestamp, so the next run retries it,
    until it has failed MAX_FAILURES runs; failures counts them by
    path@version."""
    failures = dict(failures)
    touched, gave_up = set(), []
    built = failed = 0
    last, hold, left = since, None, 0
    for i, (p, v, ts) in enumerate(todo):
        if max_builds and built + failed >= max_builds:
            left = len(todo) - i
            break
        ok = build_one(p, v)
        key = p + "@" + v
        if ok is True:
            built += 1
            touched.add(p)
            failures.pop(key, None)
        elif ok is False:
            failed += 1
            n = failures.get(key, 0) + 1
            if n >= MAX_FAILURES:
                failures.pop(key, None)
                gave_up.append(key)
            else:
                failures[key] = n
                if hold is None and ts:
                    hold = ts
        if ts and ts > last:
            last = ts
    position = hold if hold is not None and hold < last else last
    return {"touched": touched, "built": built, "failed": failed, "left": left, "position": position, "failures": failures, "gave_up": gave_up}


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


# RENDERER is the page renderer's version: bump it with any change to how
# a stored doc JSON becomes HTML (render.py, the page layout here), so a
# rebuild (--rebuild ... --stale) renders again exactly the pages an older
# renderer made. Catalog builds with no "renderer" are version 0.
RENDERER = 1
# DOC_SCHEMA is the stored doc JSON's own format (stage a's output).
DOC_SCHEMA = 1


def doc_rel(path, version):
    """Where stage (a) stores a version's doc JSON in the site."""
    return "_doc/%s/@v/%s.json" % (path, version)


def gather(tool, path, version):
    """Stage (a): fetches one module version (checked against the checksum
    log by xo), finds its license and, when redistributable, runs `xo doc
    --json` over its packages. Returns the doc record stage (b) renders
    from, or None when the fetch failed. No HTML here."""
    try:
        d = tool.fetch(path, version)
    except Exception as e:
        print("fetch %s@%s: %s" % (path, version, e), file=sys.stderr)
        return None
    found = lic.detect(d)
    rec = {"schema": DOC_SCHEMA, "path": path, "version": version, "xo": render.BUILD.get("xo", ""),
           "license": [[f, s] for f, s in found], "docs": {}}
    if not lic.redistributable(found):
        return rec
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
    rec["docs"] = docs
    return rec


def check_doc(rec, path, version):
    """A stored doc record, checked: it is for path@version and in a
    schema this builder reads. Raises ValueError otherwise."""
    if not isinstance(rec, dict) or rec.get("schema") != DOC_SCHEMA:
        raise ValueError("%s@%s: doc JSON schema %r, want %d" % (path, version, rec.get("schema") if isinstance(rec, dict) else None, DOC_SCHEMA))
    if rec.get("path") != path or rec.get("version") != version:
        raise ValueError("%s@%s: doc JSON is for %s@%s" % (path, version, rec.get("path"), rec.get("version")))
    if not isinstance(rec.get("docs"), dict) or not isinstance(rec.get("license"), list):
        raise ValueError("%s@%s: doc JSON lacks docs or license" % (path, version))
    return rec


def render_version(site, catalog, rec):
    """Stage (b): one version's pages from its doc record, and its catalog
    build entry (with the xo that made the docs and RENDERER). Reads no
    module source and runs no xo."""
    path, version = rec["path"], rec["version"]
    found = [(f, s) for f, s in rec["license"]]
    ok = lic.redistributable(found)
    mod = catalog["modules"].setdefault(path, {"versions": [], "builds": {}})
    if version not in mod["versions"]:
        mod["versions"].append(version)
    build = {"license": [s for _, s in found], "docs": ok, "packages": [], "xo": rec.get("xo", ""), "renderer": RENDERER}
    mod["builds"][version] = build
    latest = paths.latest(mod["versions"])
    saved = dict(render.BUILD)
    if rec.get("xo"):
        # "Generated ... with Xo X": the xo that ran `xo doc`, not this run's
        render.BUILD["xo"] = rec["xo"]
    try:
        _render_pages(site, path, version, latest, found, ok, rec["docs"], build)
    finally:
        render.BUILD.clear()
        render.BUILD.update(saved)


def _render_pages(site, path, version, latest, found, ok, docs, build):
    foot = module_footer(path, version, found)
    if not ok:
        write(site, render.href(path, version)[1:], render.page(
            "%s@%s" % (path, version), render.no_license_body(path, version, found), foot=foot))
        return
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
        write(site, render.href(path, version, rel)[1:], render.page("%s@%s" % (imp, version), "\n".join(body), foot=foot))
        symbols[imp] = _symbol_names(ent)
    if "" not in docs:
        # a module whose root holds no package still gets a page
        body = [render.module_header(path, version, latest, found),
                "<h2 id=\"packages\">Packages</h2><ul class=\"idx\">%s</ul>" % "".join(
                    "<li><a href=\"%s\">%s</a></li>" % (render.esc(render.href(path, version, r)), render.esc(r))
                    for r in sorted(docs))]
        write(site, render.href(path, version)[1:], render.page("%s@%s" % (path, version), "\n".join(body), foot=foot))
    build["symbols"] = symbols


def build_version(tool, site, catalog, path, version):
    """Both stages for one version: the doc JSON stored at doc_rel next to
    the pages, then the pages. Returns False when the fetch failed."""
    rec = gather(tool, path, version)
    if rec is None:
        return False
    write(site, doc_rel(path, version), json.dumps(rec, sort_keys=True, separators=(",", ":")))
    render_version(site, catalog, rec)
    return True


# The SDK repositories a --rebuild may name by their short name.
SDKS = ("aws", "azure", "gcp", "openai")


def select_versions(catalog, selector, stage, stale, xo=""):
    """The (path, version) pairs a rebuild takes from the catalog, sorted:
    selector is "all", an SDK's short name (SDKS: its repository's modules)
    or a module path pattern (fnmatch, `*` crosses `/`). With stale, only
    builds an older renderer made (render) or, for a full rebuild, also
    those whose docs an older xo than xo made."""
    if selector == "all":
        match = lambda p: True
    elif selector in SDKS:
        root = "github.com/xo-lang/" + selector
        match = lambda p: p == root or p.startswith(root + "/")
    else:
        match = lambda p: fnmatch.fnmatchcase(p, selector)
    out = []
    for path in sorted(catalog.get("modules", {})):
        if not match(path):
            continue
        builds = catalog["modules"][path].get("builds", {})
        for v in sorted(builds, key=paths.version_key):
            b = builds[v] or {}
            if stale:
                old = b.get("renderer", 0) < RENDERER
                if stage == "full" and xo and b.get("xo") != xo:
                    old = True
                if not old:
                    continue
            out.append((path, v))
    return out


def shard_of(items, spec):
    """items[i::n] for spec "I/N" (0 <= I < N), all of them for ""."""
    if not spec:
        return items
    i, _, n = spec.partition("/")
    i, n = int(i), int(n)
    if not 0 <= i < n:
        raise ValueError("--shard %r: want I/N with 0 <= I < N" % spec)
    return items[i::n]


def load_doc(source, path, version):
    """A version's stored doc JSON from source: the published site's base
    URL or a site directory."""
    rel = doc_rel(path, version)
    if source.startswith(("https://", "http://")):
        rec = json.loads(http_get(source.rstrip("/") + "/" + urllib.parse.quote(rel)).decode("utf-8"))
    else:
        with open(os.path.join(source, *rel.split("/")), encoding="utf-8") as f:
            rec = json.load(f)
    return check_doc(rec, path, version)


PARTS = "_parts"


def rebuild(todo, stage, site, catalog, tool=None, docs=""):
    """Rebuilds the versions todo: stage "full" runs both stages (fetch and
    xo doc, then render), "render" only stage (b) from each version's
    stored doc JSON at docs. Returns (catalog part, failed): the part holds
    the rebuilt versions' catalog entries only, for finish_parts."""
    part = {"schema": 1, "modules": {}}
    failed = []
    for path, version in todo:
        try:
            if stage == "full":
                ok = build_version(tool, site, catalog, path, version)
            else:
                render_version(site, catalog, load_doc(docs, path, version))
                ok = True
        except Exception as e:
            print("rebuild %s@%s: %s" % (path, version, e), file=sys.stderr)
            ok = False
        if not ok:
            failed.append(path + "@" + version)
            continue
        m = part["modules"].setdefault(path, {"versions": [], "builds": {}})
        m["versions"].append(version)
        m["builds"][version] = catalog["modules"][path]["builds"][version]
    return part, failed


def write_part(site, name, part):
    write(site, "%s/%s.json" % (PARTS, name), json.dumps(part, sort_keys=True, separators=(",", ":")))


def finish_parts(site, catalog):
    """Folds every shard's catalog part (site/_parts/*.json) into catalog,
    removes the parts and writes the catalog wide pages (finish). Returns
    the modules touched."""
    d = os.path.join(site, PARTS)
    touched = set()
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            part = json.load(f)
        for path, m in part.get("modules", {}).items():
            mod = catalog["modules"].setdefault(path, {"versions": [], "builds": {}})
            for v in m.get("versions", []):
                if v not in mod["versions"]:
                    mod["versions"].append(v)
            mod["builds"].update(m.get("builds", {}))
            touched.add(path)
        os.remove(os.path.join(d, name))
    if os.path.isdir(d):
        os.rmdir(d)
    finish(site, catalog, touched)
    return touched


def module_footer(path, version, found):
    """A module version's footer: its repository, license, build and, for
    a port, the repository's trademark line."""
    note = ""
    if found:
        note = "License: " + ", ".join(s if s != "unknown" else "not recognized" for _, s in found) + "."
    return render.footer(render.repo_url(path), note, render.generated_line("%s@%s" % (path, version)), render.port_notice(path))


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

        para = render.std_paragraph(tool.std_source(name), name)
        if not para:
            # xo's own summary (cut at 100 characters), unless it only
            # names a spec section
            s = m.get("summary", "")
            para = "" if s.startswith("see ") or s.endswith("...") else s
        summary = render.first_sentence(para)
        body = ("<h1>%s</h1><p class=\"meta\"><span>Xo %s</span></p>%s%s" % (
            render.esc(name), render.esc(ver), render.doc_html(para),
            render.package_body(entries[0], srcfn)))
        foot = render.footer("https://github.com/xo-lang/xo/tree/%s/std" % v,
                             "Xo's standard library is licensed under MIT No Attribution (MIT-0).",
                             render.generated_line("Xo %s" % v))
        write(site, render.href(name, v)[1:], render.page("%s (Xo %s)" % (name, ver), body, summary, foot=foot))
        write(site, render.href(name)[1:], render.redirect(render.href(name, v)))
        std["modules"].append({"path": name, "summary": summary, "symbols": _symbol_names(entries[0])})


# The index's search box: hidden until the script runs, so with scripts
# off the page is the full list. The script reads search/index.json and
# ranks a package's name over its symbols' names over its summary.
SEARCH_BOX = (
    "<div class=\"search\" id=\"search\" hidden><input id=\"q\" type=\"search\" autocomplete=\"off\" spellcheck=\"false\" "
    "placeholder=\"Search packages and symbols\" aria-label=\"Search packages and symbols\">"
    "<p class=\"meta hint\">Press <code>/</code> to search, <code>Enter</code> opens the first result.</p></div>"
    "<ul id=\"results\" hidden></ul>")

SEARCH_SCRIPT = """<script>
(function(){
var data=null,box,q,res,all;
function href(e){var rel=e.path===e.module?"":e.path.slice(e.module.length+1);return "/"+e.module+"@"+e.version+(rel?"/"+rel:"")+"/index.html";}
function last(p){var i=p.lastIndexOf("/");return i<0?p:p.slice(i+1);}
function rank(t0){
  // tiers: a package named t, a package path with t, a symbol named t
  // (or a method t), a symbol or one of its dotted parts starting with t,
  // a symbol with t, a summary with t; an exact case match first in each
  var out=[],t=t0.toLowerCase();
  function add(tier,exact,len,e,s){out.push([tier*2+(exact?0:1),len,e,s]);}
  data.forEach(function(e){
    var p=e.path.toLowerCase(),n=last(p);
    if(n===t)add(0,last(e.path)===t0,n.length,e,null);else if(p.indexOf(t)>=0)add(1,e.path.indexOf(t0)>=0,p.length,e,null);
    (e.symbols||[]).forEach(function(s){
      var l=s.toLowerCase(),parts=l.split(".");
      if(l===t||parts[parts.length-1]===t)add(2,s===t0||s.endsWith("."+t0),s.length,e,s);
      else if(parts.some(function(x){return x.indexOf(t)===0;}))add(3,s.indexOf(t0)>=0,s.length,e,s);
      else if(l.indexOf(t)>=0)add(4,s.indexOf(t0)>=0,s.length,e,s);
    });
    if((e.summary||"").toLowerCase().indexOf(t)>=0)add(5,false,p.length,e,null);
  });
  out.sort(function(a,b){return a[0]-b[0]||a[1]-b[1]||(a[2].path<b[2].path?-1:a[2].path>b[2].path?1:0);});
  var seen={},keep=[];
  out.forEach(function(r){var k=r[2].path+"#"+(r[3]||"");if(!seen[k]&&keep.length<50){seen[k]=1;keep.push(r);}});
  return keep;
}
function show(){
  var t=q.value.trim();
  res.textContent="";
  if(!t||!data){res.hidden=true;all.hidden=false;return;}
  var rs=rank(t);all.hidden=true;res.hidden=false;
  if(!rs.length){var li=document.createElement("li");li.className="meta";li.textContent="No package or symbol matches.";res.appendChild(li);return;}
  rs.forEach(function(r){
    var e=r[2],li=document.createElement("li"),a=document.createElement("a"),k=document.createElement("span");
    a.href=href(e)+(r[3]?"#"+encodeURIComponent(r[3]):"");
    a.textContent=r[3]?last(e.path)+"."+r[3]:e.path;
    k.className="kind";k.textContent=r[3]?e.path:(r[0]>=10?"summary":"package");
    li.appendChild(a);li.appendChild(k);
    if(!r[3]&&e.summary){var m=document.createElement("span");m.className="meta";m.style.display="block";e.summary.split("`").forEach(function(x,i,all){if(i%2&&i<all.length-1){var c=document.createElement("code");c.textContent=x;m.appendChild(c);}else m.appendChild(document.createTextNode(i%2?"`"+x:x));});li.appendChild(m);}
    res.appendChild(li);
  });
}
document.addEventListener("DOMContentLoaded",function(){
  box=document.getElementById("search");q=document.getElementById("q");res=document.getElementById("results");all=document.getElementById("all");
  if(!box||!window.fetch)return;
  var u=new URLSearchParams(location.search).get("q");if(u)q.value=u;fetch("/search/index.json").then(function(r){return r.json();}).then(function(j){data=j.packages||[];box.hidden=false;show();});
  q.addEventListener("input",show);
  q.addEventListener("keydown",function(ev){if(ev.key==="Enter"){var a=res.querySelector("a");if(a){ev.preventDefault();location.href=a.href;}}else if(ev.key==="Escape"){q.value="";show();}});
  document.addEventListener("keydown",function(ev){if(ev.key==="/"&&document.activeElement!==q&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey){var t=ev.target.tagName;if(t!=="INPUT"&&t!=="TEXTAREA"){ev.preventDefault();q.focus();}}});
});
})();
</script>"""


def finish(site, catalog, touched):
    for path in sorted(touched):
        mod = catalog["modules"][path]
        latest = paths.latest(mod["versions"])
        write(site, path + "/index.html", render.redirect(render.href(path, latest)))
        write(site, path + "/versions.html", render.page("%s versions" % path, render.versions_body(path, mod["versions"]),
                                                         foot=render.footer(render.repo_url(path), notice=render.port_notice(path))))
    # the home page and the search index cover the whole catalog
    items = []
    search = []
    for path in sorted(catalog["modules"]):
        mod = catalog["modules"][path]
        latest = paths.latest(mod["versions"])
        if not latest:
            continue
        items.append("<li><a href=\"%s\">%s</a><span class=\"meta\">%s</span></li>" % (
            render.esc(render.href(path, latest)), render.esc(path), render.esc(latest)))
        b = mod.get("builds", {}).get(latest, {})
        for imp, syms in sorted((b.get("symbols") or {}).items()):
            search.append({"path": imp, "module": path, "version": latest, "summary": "", "symbols": syms})
    std = catalog.get("std", {})
    std_items = "".join("<li><a href=\"%s\">%s</a><span class=\"meta\">%s</span></li>" % (
        render.esc(render.href(m["path"], std["version"])), render.esc(m["path"]), render.inline_code(m.get("summary", "")))
        for m in std.get("modules", []))
    for m in std.get("modules", []):
        search.append({"path": m["path"], "module": m["path"], "version": std["version"], "summary": m.get("summary", ""), "symbols": m.get("symbols", [])})
    body = "<h1>Xo packages</h1>" + SEARCH_BOX + "<div id=\"all\">"
    if std_items:
        body += "<h2 id=\"std\">Standard library (Xo %s)</h2><ul class=\"mods\">%s</ul>" % (render.esc(std["version"][1:]), std_items)
    body += "<h2 id=\"modules\">Modules</h2><ul class=\"mods\">%s</ul></div>" % ("".join(items) or "<li>none yet</li>")
    write(site, "index.html", render.page("pkg.xolang.org", body, "Documentation for Xo's standard library and published modules.", head=SEARCH_SCRIPT, dated=True))
    write(site, "catalog.json", json.dumps(catalog, sort_keys=True, separators=(",", ":")))
    write(site, "search/index.json", json.dumps({"schema": 1, "packages": search}, sort_keys=True, separators=(",", ":")))


def build_date():
    return os.environ.get("PKGSITE_BUILD_DATE") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def main_rebuild(ap, a):
    """--rebuild (one shard of it) and --finish-parts: never the feed, its
    position or std."""
    if a.module or a.std or a.advance or a.max:
        ap.error("--rebuild and --finish-parts take no --module, --std, --advance or --max")
    if a.rebuild and a.finish_parts:
        ap.error("--rebuild and --finish-parts are separate jobs")
    render.BUILD["date"] = build_date()
    catalog = load_catalog(a.catalog)
    os.makedirs(a.site, exist_ok=True)
    if a.finish_parts:
        touched = finish_parts(a.site, catalog)
        print("finished %d module(s); catalog has %d" % (len(touched), len(catalog["modules"])))
        return 0
    if not catalog["modules"]:
        ap.error("--rebuild: the catalog (--catalog) is empty or missing")
    tool = None
    if a.stage == "full":
        if not a.xo or not a.work:
            ap.error("--stage full needs --xo and --work")
        if not a.sumdb and not a.no_verify:
            ap.error("--sumdb (or XO_SUMDB) is required for --stage full")
        tool = xotool.Tool(a.xo, a.work, a.proxy, "off" if a.no_verify else a.sumdb, a.sandbox)
        render.BUILD["xo"] = tool.version()
    try:
        todo = shard_of(select_versions(catalog, a.rebuild, a.stage, a.stale, render.BUILD.get("xo", "")), a.shard)
    except ValueError as e:
        ap.error(str(e))
    part, failed = rebuild(todo, a.stage, a.site, catalog, tool, a.docs)
    write_part(a.site, "shard-" + (a.shard.replace("/", "-of-") or "all"), part)
    for key in failed[:20]:
        print("::warning::rebuild %s failed" % key)
    print("rebuilt %d of %d version(s) (%s, stage %s%s), %d failed" % (
        len(todo) - len(failed), len(todo), a.rebuild, a.stage, ", shard " + a.shard if a.shard else "", len(failed)))
    return 1 if todo and len(failed) == len(todo) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xo", default="", help="the released xo binary (not needed for --stage render or --finish-parts)")
    ap.add_argument("--work", default="", help="scratch directory (module cache, xo's HOME)")
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
    ap.add_argument("--max", type=int, default=0, help="build at most this many versions this run (0: no limit); the position stops at the last one taken")
    ap.add_argument("--rebuild", default="", metavar="SELECTOR",
                    help="rebuild versions the catalog already has: all, an SDK (%s) or a module path pattern; never moves the feed position" % ", ".join(SDKS))
    ap.add_argument("--stage", choices=["render", "full"], default="render",
                    help="with --rebuild: render (HTML from the stored doc JSON, no xo) or full (fetch, xo doc, render)")
    ap.add_argument("--stale", action="store_true", help="with --rebuild: only versions an older renderer (or, full, an older xo) made")
    ap.add_argument("--shard", default="", metavar="I/N", help="with --rebuild: this job's share, every Nth version from the Ith")
    ap.add_argument("--docs", default="https://pkg.xolang.org", help="with --stage render: where the stored doc JSON is (site URL or directory)")
    ap.add_argument("--finish-parts", action="store_true",
                    help="fold the shards' catalog parts in --site into --catalog and write the catalog wide pages")
    a = ap.parse_args(argv)
    if a.rebuild or a.finish_parts:
        return main_rebuild(ap, a)
    if not a.xo or not a.work:
        ap.error("--xo and --work are required")

    fetching = not (a.std and not a.module and a.feed == "none")
    if fetching and not a.sumdb and not a.no_verify:
        ap.error("--sumdb (or XO_SUMDB) is required: versions are checked against the checksum log; --no-verify is for local tests")
    if a.sumdb and a.sumdb.strip() in ("off", ""):
        ap.error("--sumdb off: use --no-verify for local tests")
    tool = xotool.Tool(a.xo, a.work, a.proxy, "off" if a.no_verify else a.sumdb, a.sandbox)
    render.BUILD["xo"] = tool.version()
    render.BUILD["date"] = build_date()
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

    def build_one(p, v):
        if catalog["modules"].get(p, {}).get("builds", {}).get(v) is not None:
            return None
        return build_version(tool, a.site, catalog, p, v)

    r = run_todo(todo, since, build_one, a.max, pos.get("failures", {}))
    touched, failed, last = r["touched"], r["failed"], r["position"]
    if a.std:
        build_std(tool, a.site, catalog)
    finish(a.site, catalog, touched)
    if a.advance and not a.module:
        os.makedirs(a.state, exist_ok=True)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(pos_file, "w", encoding="utf-8") as f:
            state = {"since": last, "heartbeat": now}
            if r["failures"]:
                state["failures"] = r["failures"]
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
    for key in r["gave_up"]:
        print("::warning::%s failed %d times; skipped" % (key, MAX_FAILURES))
    print("built %d version(s) of %d module(s), %d failed, %d left for the next run, position %s" % (r["built"], len(touched), failed, r["left"], last))
    return 1 if failed and failed == len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())

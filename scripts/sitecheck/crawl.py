"""crawl.py BASE_URL SITE_DIR: fetch every HTML page of SITE_DIR over BASE_URL,
then every local link (href, src, meta refresh) on it; report non-200
answers, missing #anchors, duplicate ids and external link hosts."""
import collections, html.parser, json, os, sys, urllib.error, urllib.parse, urllib.request

base, site = sys.argv[1].rstrip("/"), sys.argv[2]

class P(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.ids = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a: self.ids.append(a["id"])
        for k in ("href", "src"):
            if a.get(k) is not None: self.links.append(a[k])
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "refresh":
            c = a.get("content", "")
            if "url=" in c: self.links.append(c.split("url=", 1)[1].strip())

def get(path):
    try:
        with urllib.request.urlopen(base + urllib.parse.quote(path, safe="/@#%"), timeout=30) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""

pages = {}
for root, _, files in os.walk(site):
    for f in files:
        if f.endswith(".html"):
            pages["/" + os.path.relpath(os.path.join(root, f), site).replace(os.sep, "/")] = None
parsed, ids_of, status = {}, {}, {}
problems = collections.defaultdict(list)
ext = collections.Counter()
def page(path):
    if path not in parsed:
        st, ct, body = get(path)
        status[path] = st
        p = P(); p.feed(body.decode("utf-8", "replace")); parsed[path] = p
        ids_of[path] = set(p.ids)
        dup = [i for i, n in collections.Counter(p.ids).items() if n > 1]
        if dup: problems["duplicate ids"].append("%s: %s" % (path, dup[:5]))
        if st != 200: problems["page not 200"].append("%s %d" % (path, st))
        elif "text/html" not in ct: problems["page content type"].append("%s %s" % (path, ct))
    return parsed[path]
nlinks = 0
for path in sorted(pages):
    p = page(path)
    for href in p.links:
        nlinks += 1
        u = urllib.parse.urlsplit(href)
        if u.scheme in ("http", "https"):
            ext[u.netloc] += 1; continue
        if u.scheme or href.startswith("//"):
            problems["odd link"].append("%s -> %s" % (path, href)); continue
        target = urllib.parse.unquote(u.path) if u.path else path
        if not target.startswith("/"):
            problems["relative link"].append("%s -> %s" % (path, href)); continue
        if target.endswith(".html"):
            page(target)
            if status[target] != 200:
                problems["broken link"].append("%s -> %s (%d)" % (path, href, status[target])); continue
            if u.fragment and urllib.parse.unquote(u.fragment) not in ids_of[target]:
                problems["missing anchor"].append("%s -> %s" % (path, href))
        else:
            if target not in status:
                status[target] = get(target)[0]
            if status[target] != 200:
                problems["broken link"].append("%s -> %s (%d)" % (path, href, status[target]))
for j in ("/catalog.json", "/search/index.json"):
    st, ct, body = get(j)
    try: json.loads(body); ok = st == 200
    except ValueError: ok = False
    if not ok: problems["json"].append("%s %d %s" % (j, st, ct))
print(json.dumps({"pages": len(pages), "fetched": len(status), "local_links": nlinks - sum(ext.values()),
                  "external_links": dict(ext), "problems": {k: (len(v), v[:8]) for k, v in problems.items()}}, indent=1))

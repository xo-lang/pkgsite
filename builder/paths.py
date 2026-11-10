"""Module paths, versions and source links (decisions 0086, 0126, 0589)."""

import re

_SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
# A module path: slash separated elements of letters, digits and . _ ~ -,
# the first with a dot (a host). No element is empty, "." or "..".
_ELEM = re.compile(r"^[A-Za-z0-9._~-]+$")


def valid_path(path):
    elems = path.split("/")
    if len(elems) < 2 or "." not in elems[0]:
        return False
    return all(_ELEM.match(e) and e not in (".", "..") for e in elems)


def valid_version(v):
    return bool(_SEMVER.match(v))


def escape(path):
    """The module proxy's case escaping (Go's module.EscapePath): an upper
    case letter is "!" and its lower case."""
    return "".join("!" + c.lower() if "A" <= c <= "Z" else c for c in path)


def _prerelease_key(pre):
    out = []
    for part in pre.split("."):
        out.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return out


def version_key(v):
    """A sort key: semver order, a prerelease before its release."""
    m = _SEMVER.match(v)
    if not m:
        return ((-1, -1, -1), 0, [])
    nums = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    pre = m.group(4)
    return (nums, 1 if pre is None else 0, _prerelease_key(pre) if pre else [])


def is_prerelease(v):
    m = _SEMVER.match(v)
    return bool(m and m.group(4))


def latest(versions):
    """The highest release, else the highest prerelease (Go's rule)."""
    rel = [v for v in versions if not is_prerelease(v)]
    pool = rel or list(versions)
    return max(pool, key=version_key) if pool else ""


def location(path):
    """(repository path, subdirectory) for a module path on a known host,
    or None: github.com, gitlab.com and bitbucket.org repositories are the
    first three elements (core 4.2). A major version suffix (/vN) is part
    of the subdirectory only when the repository holds it as a directory,
    which the builder cannot know; Xo tags a /vN module as <dir>/vN.x.y
    (decision 0086), so it is dropped from the directory here."""
    elems = path.split("/")
    if elems[0] not in ("github.com", "gitlab.com", "bitbucket.org") or len(elems) < 3:
        return None
    sub = elems[3:]
    if sub and re.match(r"^v[2-9][0-9]*$", sub[-1]):
        sub = sub[:-1]
    return "/".join(elems[:3]), "/".join(sub)


def source_url(path, version, file, line=0):
    """A link to file (relative to the module root) at the version's tag,
    or "" when the host is unknown."""
    loc = location(path)
    if loc is None:
        return ""
    repo, sub = loc
    tag = (sub + "/" if sub else "") + version
    rel = (sub + "/" if sub else "") + file
    host = repo.split("/")[0]
    if host == "github.com":
        url = "https://%s/blob/%s/%s" % (repo, tag, rel)
        return url + ("#L%d" % line if line else "")
    if host == "gitlab.com":
        url = "https://%s/-/blob/%s/%s" % (repo, tag, rel)
        return url + ("#L%d" % line if line else "")
    url = "https://%s/src/%s/%s" % (repo, tag, rel)
    return url + ("#lines-%d" % line if line else "")

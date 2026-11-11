"""Running the released xo: fetching a version (verified against the checksum
log) and extracting its docs with `xo doc --json`, which parses and checks
only and never runs a module's code (decision 0589)."""

import json
import os
import shutil
import subprocess

from . import paths

DOC_TIMEOUT = 300
GET_TIMEOUT = 900


class Tool:
    def __init__(self, xo, work, proxy, sumdb, sandbox="none"):
        self.xo = os.path.abspath(xo)
        self.work = os.path.abspath(work)
        self.proxy = proxy
        self.sumdb = sumdb
        self.sandbox = sandbox
        self.home = os.path.join(self.work, "home")
        self.modcache = os.path.join(self.work, "modcache")
        os.makedirs(self.home, exist_ok=True)
        self.netns = []
        if sandbox == "unshare":
            self.netns = no_network_prefix()

    def env(self, offline):
        e = {
            "HOME": self.home,
            "TMPDIR": self.home,
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "XO_MODCACHE": self.modcache,
            "XO_PROXY": self.proxy,
            "XO_SUMDB": self.sumdb,
            "XO_NOPROXY": "",
            "XO_NOSUMDB": "",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if offline:
            e["XO_OFFLINE"] = "1"
        return e

    def run(self, args, cwd, offline, timeout):
        cmd = [self.xo] + args
        env = self.env(offline)
        if offline and self.netns:
            # no network at all for the parse; sudo drops the environment,
            # so it is passed again inside
            cmd = self.netns + ["env", "-i"] + ["%s=%s" % kv for kv in sorted(env.items())] + cmd
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout)

    def version(self):
        r = subprocess.run([self.xo, "version"], env=self.env(True), capture_output=True, timeout=60)
        # "xo 0.46.0 linux/amd64"
        parts = r.stdout.decode().split()
        return parts[1] if len(parts) > 1 else ""

    def fetch(self, path, version):
        """The version's directory in the module cache, fetched through
        XO_PROXY and checked against XO_SUMDB by xo itself. Raises
        RuntimeError with xo's message."""
        if not paths.valid_path(path) or not paths.valid_version(version):
            raise RuntimeError("not a module path and version: %r %r" % (path, version))
        d = os.path.join(self.modcache, paths.escape(path) + "@" + version)
        if os.path.isfile(os.path.join(d, "xo.mod")):
            return d
        get = os.path.join(self.work, "get")
        shutil.rmtree(get, ignore_errors=True)
        os.makedirs(get)
        with open(os.path.join(get, "xo.mod"), "w") as f:
            f.write("module pkgsite.invalid/get\nedition preview\n")
        r = self.run(["get", path + "@" + version], get, False, GET_TIMEOUT)
        if not os.path.isfile(os.path.join(d, "xo.mod")):
            raise RuntimeError("xo get %s@%s: %s" % (path, version, _tail(r)))
        return d

    def doc(self, module_dir, rel):
        """The `xo doc --json` entries of the package in module_dir/rel."""
        arg = "./" + rel if rel else "."
        r = self.run(["doc", "--json", arg], module_dir, True, DOC_TIMEOUT)
        return _json(r, "xo doc %s" % arg)

    def doc_walk(self, module_dir, path):
        """{package dir relative to the module: entry} from one
        `xo doc --json ./...` over the module (xo with the DIR/... fix,
        xo-lang/xo 12ac410e0), or None when this xo reads `./...` as a
        declaration name (0.45.0 and older): the caller then runs `doc`
        per package."""
        try:
            entries = self.run_json(["doc", "--json", "./..."], module_dir)
        except RuntimeError as e:
            if "no declaration named ./..." in str(e):
                return None
            raise
        out = {}
        for ent in entries:
            imp = ent.get("module", "")
            if imp == path:
                out[""] = ent
            elif imp.startswith(path + "/"):
                out[imp[len(path) + 1:]] = ent
        return out

    def run_json(self, args, cwd):
        r = self.run(args, cwd, True, DOC_TIMEOUT)
        return _json(r, "xo " + " ".join(args))

    def std_list(self):
        r = self.run(["doc", "--json", "std"], self.home, True, DOC_TIMEOUT)
        return _json(r, "xo doc std")

    def std_doc(self, name):
        r = self.run(["doc", "--json", name], self.home, True, DOC_TIMEOUT)
        return _json(r, "xo doc %s" % name)


# The two ways to a process with no network, tried in order:
#   - an unprivileged user and network namespace (Ubuntu 24.04 forbids it
#     unless kernel.apparmor_restrict_unprivileged_userns is 0);
#   - root's `unshare --net`, then setpriv back to this user, so xo never
#     runs as root (GitHub's runners have passwordless sudo).
def _candidates():
    uid, gid = os.getuid(), os.getgid()
    return [
        ["unshare", "--user", "--map-root-user", "--net", "--"],
        ["sudo", "-n", "unshare", "--net", "--", "setpriv", "--reuid=%d" % uid, "--regid=%d" % gid,
         "--clear-groups", "--"],
    ]


# A probe that passes only when the process has no route anywhere: no IPv4
# route and no IPv6 route but loopback's, read from /proc/net (the process's
# own network namespace). Not /sys/class/net: sysfs shows the namespace it
# was mounted in, so inside `sudo unshare --net` it still listed the
# runner's eth0 and the probe failed with no message (run 42940459718,
# 2026-11-11). Not "only lo listed" either: a new namespace also lists the
# kernel's fallback tunnel devices (tunl0, gre0, sit0 and others, down),
# whenever their modules are loaded. A failing probe names the route's device.
_PROBE = ["awk", 'FILENAME ~ /ipv6_route$/ { d = $NF } FILENAME !~ /ipv6_route$/ { if (FNR == 1) next; d = $1 } '
          'd != "lo" { print "a route through " d " in the namespace" > "/dev/stderr"; bad = 1 } END { exit bad }',
          "/proc/net/route", "/proc/net/ipv6_route"]


def no_network_prefix(candidates=None, runner=subprocess.run):
    """The first command prefix that runs a process with no network, as this
    user; RuntimeError when none works (the build fails closed)."""
    errs = []
    for pre in candidates if candidates is not None else _candidates():
        try:
            r = runner(pre + _PROBE, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            errs.append("%s: %s" % (pre[0], e))
            continue
        if r.returncode == 0:
            return pre
        errs.append("%s: exit %d %s" % (" ".join(pre[:3]), r.returncode, (r.stderr or b"").decode("utf-8", "replace").strip()[:200]))
    raise RuntimeError("no way to run xo doc without network: " + "; ".join(errs))


def _tail(r):
    text = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return " / ".join(text[-3:]) or "exit %d" % r.returncode


def _json(r, what):
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise RuntimeError("%s: %s" % (what, _tail(r)))
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError("%s: %s" % (what, data["error"]))
    if not isinstance(data, list):
        raise RuntimeError("%s: unexpected output" % what)
    return data


def packages(module_dir):
    """The directories of module_dir holding a package (a .xo file that is
    not a test), relative and sorted ("" is the root). testdata, hidden and
    _ directories and nested modules (a directory with its own xo.mod) are
    left out, as the toolchain does."""
    out = []
    for root, dirs, files in os.walk(module_dir):
        rel = os.path.relpath(root, module_dir)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        keep = []
        for d in sorted(dirs):
            if d.startswith((".", "_")) or d == "testdata":
                continue
            if os.path.isfile(os.path.join(root, d, "xo.mod")):
                continue
            if os.path.islink(os.path.join(root, d)):
                continue
            keep.append(d)
        dirs[:] = keep
        if any(f.endswith(".xo") and not f.endswith("_test.xo") for f in files):
            out.append(rel)
    return sorted(out)

"""publish-r2.sh with DRY_RUN=1: the upload order, content types, cache
headers and the file name guard, with no credentials and no network."""

import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "publish-r2.sh")


def run(site, **env):
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DRY_RUN": "1"}
    e.update(env)
    return subprocess.run(["sh", SCRIPT, site], env=e, capture_output=True, text=True)


def make(root, files):
    for f in files:
        p = os.path.join(root, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("x")


class PublishTest(unittest.TestCase):
    def test_order_and_headers(self):
        with tempfile.TemporaryDirectory() as d:
            make(d, ["catalog.json", "index.html", "search/index.json",
                     "example.com/m@v1.0.0/index.html", "example.com/m@v1.0.0/sub/index.html",
                     "example.com/m/index.html", "example.com/m/versions.html",
                     "std/charset@0.46.0/index.html"])
            r = run(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            puts = [l.split("\t") for l in r.stdout.splitlines() if l.startswith("put ")]
            keys = [p[0][4:] for p in puts]
            self.assertEqual(keys[-3:], ["search/index.json", "index.html", "catalog.json"])
            self.assertEqual(len(keys), 8)
            h = {p[0][4:]: (p[1], p[2]) for p in puts}
            self.assertEqual(h["example.com/m@v1.0.0/index.html"], ("text/html; charset=utf-8", "public, max-age=300"))
            self.assertEqual(h["std/charset@0.46.0/index.html"][1], "public, max-age=300")
            self.assertEqual(h["example.com/m/versions.html"][1], "public, max-age=300")
            self.assertEqual(h["catalog.json"], ("application/json", "public, max-age=300"))
            self.assertIn("8 file(s) to xo-pkgsite", r.stdout)

    def test_refuses_odd_names_and_non_sites(self):
        with tempfile.TemporaryDirectory() as d:
            make(d, ["catalog.json", "bad name.html"])
            r = run(d)
            self.assertEqual(r.returncode, 2)
            self.assertIn("unexpected file name", r.stderr)
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
            self.assertEqual(r.returncode, 2)
            self.assertIn("catalog.json is missing", r.stderr)

    def test_needs_credentials_and_an_r2_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            make(d, ["catalog.json"])
            r = run(d, DRY_RUN="0")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("R2_ACCESS_KEY_ID", r.stderr)
            r = run(d, DRY_RUN="0", R2_ACCESS_KEY_ID="k", R2_SECRET_ACCESS_KEY="s", R2_ENDPOINT="https://s3.example.com")
            self.assertEqual(r.returncode, 2)
            self.assertIn("r2.cloudflarestorage.com", r.stderr)


FAKE_AWS = """#!/bin/sh
# records each put-object as KEY<TAB>CONTENT-TYPE<TAB>CACHE; fails for $FAIL_KEY
key="" ct="" cc=""
while [ $# -gt 0 ]; do
  case $1 in --key) key=$2; shift ;; --content-type) ct=$2; shift ;; --cache-control) cc=$2; shift ;; esac
  shift
done
[ -n "$FAIL_KEY" ] && [ "$key" = "$FAIL_KEY" ] && exit 1
printf '%s\\t%s\\t%s\\n' "$key" "$ct" "$cc" >> "$AWS_LOG"
"""


class ParallelPublishTest(unittest.TestCase):
    """The real upload path (no DRY_RUN) with a fake aws: pages go
    PUBLISH_JOBS at a time, every one before the last three files, and a
    failed page stops the publish before catalog.json."""

    FILES = ["catalog.json", "index.html", "search/index.json", "_doc/example.com/m/@v/v1.0.0.json"] + [
        "example.com/m@v1.%d.0/index.html" % i for i in range(40)]

    def publish(self, d, fail=""):
        bin_ = os.path.join(d, "bin")
        os.makedirs(bin_)
        with open(os.path.join(bin_, "aws"), "w") as f:
            f.write(FAKE_AWS)
        os.chmod(os.path.join(bin_, "aws"), 0o755)
        site = os.path.join(d, "site")
        make(site, self.FILES)
        log = os.path.join(d, "log")
        r = run(site, DRY_RUN="0", PATH=bin_ + ":" + os.environ.get("PATH", "/usr/bin:/bin"), AWS_LOG=log, FAIL_KEY=fail,
                R2_ACCESS_KEY_ID="k", R2_SECRET_ACCESS_KEY="s", R2_ENDPOINT="https://acct.r2.cloudflarestorage.com",
                PUBLISH_JOBS="8")
        rows = []
        if os.path.exists(log):
            with open(log) as f:
                rows = [l.rstrip("\n").split("\t") for l in f]
        return r, rows

    def test_all_pages_then_the_last_three(self):
        with tempfile.TemporaryDirectory() as d:
            r, rows = self.publish(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            keys = [k for k, _, _ in rows]
            self.assertEqual(sorted(keys), sorted(self.FILES))
            self.assertEqual(keys[-3:], ["search/index.json", "index.html", "catalog.json"])
            h = {k: (t, c) for k, t, c in rows}
            self.assertEqual(h["example.com/m@v1.7.0/index.html"], ("text/html; charset=utf-8", "public, max-age=300"))
            self.assertEqual(h["_doc/example.com/m/@v/v1.0.0.json"][0], "application/json")
            self.assertIn("%d file(s) to xo-pkgsite" % len(self.FILES), r.stdout)

    def test_a_failed_page_stops_before_the_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            r, rows = self.publish(d, fail="example.com/m@v1.3.0/index.html")
            self.assertNotEqual(r.returncode, 0)
            keys = [k for k, _, _ in rows]
            self.assertNotIn("catalog.json", keys)
            self.assertNotIn("index.html", keys)


if __name__ == "__main__":
    unittest.main()

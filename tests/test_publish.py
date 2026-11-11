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
            self.assertEqual(h["example.com/m@v1.0.0/index.html"], ("text/html; charset=utf-8", "public, max-age=86400"))
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


if __name__ == "__main__":
    unittest.main()

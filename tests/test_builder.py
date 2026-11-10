"""Unit tests of the builder that need no xo and no network:
python3 -E -s -m unittest discover -s tests -t ."""

import json
import os
import tempfile
import unittest

from builder import build, license as lic, paths, render, xotool

MIT = """MIT License

Copyright (c) 2026 Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
"""


class LicenseTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(lic.classify(MIT), "MIT")
        self.assertEqual(lic.classify("All rights reserved."), "unknown")
        apache = "Apache License\nVersion 2.0, January 2004\nTERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n"
        self.assertEqual(lic.classify(apache), "Apache-2.0")

    def test_detect(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(lic.detect(d), [])
            self.assertFalse(lic.redistributable(lic.detect(d)))
            with open(os.path.join(d, "LICENSE"), "w") as f:
                f.write(MIT)
            with open(os.path.join(d, "COPYING.txt"), "w") as f:
                f.write("custom terms")
            with open(os.path.join(d, "README.md"), "w") as f:
                f.write(MIT)
            found = lic.detect(d)
            self.assertEqual(found, [("COPYING.txt", "unknown"), ("LICENSE", "MIT")])
            self.assertTrue(lic.redistributable(found))


class PathsTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(paths.valid_path("github.com/xo-lang/aws/service/sts"))
        for bad in ["std/charset", "github.com/../x", "github.com//x", "github.com/a b", "x"]:
            self.assertFalse(paths.valid_path(bad), bad)
        self.assertTrue(paths.valid_version("v1.2.3-rc.1"))
        self.assertFalse(paths.valid_version("1.2.3"))

    def test_escape(self):
        self.assertEqual(paths.escape("github.com/Azure/x"), "github.com/!azure/x")

    def test_latest(self):
        self.assertEqual(paths.latest(["v0.9.0", "v0.10.0", "v1.0.0-rc.1"]), "v0.10.0")
        self.assertEqual(paths.latest(["v1.0.0-rc.1", "v1.0.0-rc.2"]), "v1.0.0-rc.2")
        self.assertEqual(sorted(["v1.0.0", "v1.0.0-rc.10", "v1.0.0-rc.2"], key=paths.version_key),
                         ["v1.0.0-rc.2", "v1.0.0-rc.10", "v1.0.0"])

    def test_source_url(self):
        self.assertEqual(paths.source_url("github.com/xo-lang/aws/service/sts", "v0.1.0", "client.xo", 15),
                         "https://github.com/xo-lang/aws/blob/service/sts/v0.1.0/service/sts/client.xo#L15")
        self.assertEqual(paths.source_url("github.com/xo-lang/aws", "v0.1.0", "aws.xo"),
                         "https://github.com/xo-lang/aws/blob/v0.1.0/aws.xo")
        self.assertEqual(paths.source_url("github.com/acme/tools/cli/v2", "v2.0.0", "c.xo", 1),
                         "https://github.com/acme/tools/blob/cli/v2.0.0/cli/c.xo#L1")
        self.assertEqual(paths.source_url("example.com/x", "v1.0.0", "a.xo"), "")


class RenderTest(unittest.TestCase):
    def test_escapes_everything(self):
        evil = '<script>alert(1)</script> `<b>` "q"'
        out = render.doc_html(evil)
        self.assertNotIn("<script>", out)
        self.assertNotIn("<b>", out)
        self.assertIn("<code>&lt;b&gt;</code>", out)
        pkg = {"functions": [{"name": "f\"><x", "signature": "fn f() -> <T>", "doc": evil, "pos": {"file": "a.xo", "line": 1}}]}
        body = render.package_body(pkg, lambda pos: 'javascript:"x"')
        self.assertNotIn("<x", body.replace("&lt;x", ""))
        self.assertNotIn('"x"', body)

    def test_doc_blocks(self):
        out = render.doc_html("First line\ncontinues.\n\n```\nlet x = 1\n```\n\n- one\n- two `t`\n\n    indented()\n")
        self.assertIn("<p>First line continues.</p>", out)
        self.assertIn("<pre>let x = 1</pre>", out)
        self.assertIn("<li>two <code>t</code></li>", out)
        self.assertIn("<pre>indented()</pre>", out)

    def test_anchors_exact_names(self):
        pkg = {"types": [{"name": "Client", "signature": "pub struct Client {}", "methods": [
            {"name": "Client.get", "signature": "pub fn (c: Client) get()"}]}],
            "constants": [{"name": "MAX", "signature": "pub const MAX: Int = 1"}]}
        body = render.package_body(pkg, lambda pos: "")
        for name in ["Client", "Client.get", "MAX"]:
            self.assertIn('id="%s"' % name, body)
            self.assertIn('href="#%s"' % name, body)

    def test_href(self):
        self.assertEqual(render.href("github.com/a/b", "v1.0.0", "x/y"), "/github.com/a/b@v1.0.0/x/y/index.html")
        self.assertEqual(render.href("std/charset"), "/std/charset/index.html")


class PackagesTest(unittest.TestCase):
    def test_packages(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ["xo.mod", "a.xo", "x/x.xo", "x/x_test.xo", "t/t_test.xo", "testdata/d.xo",
                      ".hid/h.xo", "_skip/s.xo", "nested/xo.mod", "nested/n.xo", "deep/er/e.xo"]:
                p = os.path.join(d, f)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").close()
            self.assertEqual(xotool.packages(d), ["", "deep/er", "x"])


class FeedTest(unittest.TestCase):
    def test_feed_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "feed.jsonl")
            with open(p, "w") as f:
                for rec in [{"Path": "github.com/a/b", "Version": "v1.0.0", "Timestamp": "2026-11-10T00:00:00Z"},
                            {"Path": "../evil", "Version": "v1.0.0", "Timestamp": "2026-11-10T00:00:01Z"},
                            {"Path": "github.com/a/c", "Version": "latest", "Timestamp": "2026-11-10T00:00:02Z"},
                            {"Path": "github.com/a/d", "Version": "v0.1.0", "Timestamp": "2026-11-09T00:00:00Z"}]:
                    f.write(json.dumps(rec) + "\n")
            got = build.read_feed(p, "2026-11-09T12:00:00Z")
            self.assertEqual(got, [("github.com/a/b", "v1.0.0", "2026-11-10T00:00:00Z")])

    def test_catalog_missing(self):
        self.assertEqual(build.load_catalog("/nonexistent/catalog.json")["modules"], {})


if __name__ == "__main__":
    unittest.main()

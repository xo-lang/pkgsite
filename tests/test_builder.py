"""Unit tests of the builder that need no xo and no network:
python3 -E -s -m unittest discover -s tests -t ."""

import json
import os
import shutil
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

    def test_pages_have_a_viewport(self):
        # a page without one renders 980 px wide on a phone (sitecheck, 2026-11-10)
        for html in [render.page("t", "b"), render.redirect("/x/index.html")]:
            self.assertIn('name="viewport"', html)

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


class SandboxTest(unittest.TestCase):
    class R:
        def __init__(self, code):
            self.returncode = code
            self.stderr = b"denied"

    def test_first_that_works(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd[0])
            return self.R(1 if cmd[0] == "a" else 0)
        self.assertEqual(xotool.no_network_prefix([["a"], ["b", "x"]], runner), ["b", "x"])
        self.assertEqual(calls, ["a", "b"])

    def test_fails_closed(self):
        def runner(cmd, **kw):
            if cmd[0] == "missing":
                raise OSError("not found")
            return self.R(1)
        with self.assertRaises(RuntimeError):
            xotool.no_network_prefix([["missing"], ["a"]], runner)

    def _probe(self, route, ipv6):
        # the probe itself, over route tables of its own
        import subprocess
        import tempfile
        d = tempfile.mkdtemp()
        try:
            names = []
            for name, text in (("route", route), ("ipv6_route", ipv6)):
                names.append(os.path.join(d, name))
                with open(names[-1], "w") as f:
                    f.write(text)
            return subprocess.run(xotool._PROBE[:2] + names, capture_output=True)
        finally:
            shutil.rmtree(d)

    HEAD = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    LO6 = "00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000001 00000000 80200001 lo\n"

    def test_probe_rejects_an_ipv4_route(self):
        r = self._probe(self.HEAD + "eth0\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n", "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"through eth0", r.stderr)

    def test_probe_rejects_an_ipv6_route(self):
        r = self._probe(self.HEAD, self.LO6 + self.LO6.replace(" lo\n", " eth0\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(b"through eth0", r.stderr)

    def test_probe_accepts_loopback_alone(self):
        r = self._probe(self.HEAD, self.LO6)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._probe(self.HEAD, "")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_probe_reads_the_process_namespace(self):
        self.assertEqual(xotool._PROBE[2:], ["/proc/net/route", "/proc/net/ipv6_route"])


class DocWalkTest(unittest.TestCase):
    class Fake(xotool.Tool):
        def __init__(self, answer):
            self.answer = answer

        def run_json(self, args, cwd):
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    def test_maps_packages(self):
        t = self.Fake([{"module": "github.com/a/m"}, {"module": "github.com/a/m/x/y"}, {"module": "github.com/a/other"}])
        self.assertEqual(sorted(t.doc_walk("/d", "github.com/a/m")), ["", "x/y"])

    def test_old_xo_falls_back(self):
        t = self.Fake(RuntimeError("xo doc --json ./...: no declaration named ./..."))
        self.assertIsNone(t.doc_walk("/d", "github.com/a/m"))

    def test_other_errors_raise(self):
        t = self.Fake(RuntimeError("xo doc --json ./...: something else"))
        with self.assertRaises(RuntimeError):
            t.doc_walk("/d", "github.com/a/m")


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


class RunTodoTest(unittest.TestCase):
    TODO = [("a.org/m", "v1.0.0", "2026-11-12T01:00:00Z"), ("a.org/m", "v1.1.0", "2026-11-12T01:00:01Z"),
            ("a.org/n", "v1.0.0", "2026-11-12T01:00:02Z"), ("a.org/o", "v1.0.0", "2026-11-12T01:00:03Z")]

    def run_with(self, results, max_builds=0, failures=None):
        calls = []

        def one(p, v):
            calls.append(p + "@" + v)
            return results.get(p + "@" + v, True)
        r = build.run_todo(self.TODO, "2026-11-12T00:00:00Z", one, max_builds, failures or {})
        return r, calls

    def test_all_built(self):
        r, calls = self.run_with({})
        self.assertEqual(len(calls), 4)
        self.assertEqual((r["built"], r["failed"], r["left"]), (4, 0, 0))
        self.assertEqual(r["position"], "2026-11-12T01:00:03Z")
        self.assertEqual(r["touched"], {"a.org/m", "a.org/n", "a.org/o"})

    def test_max_stops_at_last_taken(self):
        r, calls = self.run_with({}, max_builds=2)
        self.assertEqual(calls, ["a.org/m@v1.0.0", "a.org/m@v1.1.0"])
        self.assertEqual((r["built"], r["left"]), (2, 2))
        self.assertEqual(r["position"], "2026-11-12T01:00:01Z")

    def test_already_built_does_not_count(self):
        r, calls = self.run_with({"a.org/m@v1.0.0": None, "a.org/m@v1.1.0": None}, max_builds=2)
        self.assertEqual(r["built"], 2)
        self.assertEqual(r["position"], "2026-11-12T01:00:03Z")

    def test_failure_holds_position(self):
        r, _ = self.run_with({"a.org/m@v1.1.0": False})
        self.assertEqual((r["built"], r["failed"]), (3, 1))
        self.assertEqual(r["position"], "2026-11-12T01:00:01Z")
        self.assertEqual(r["failures"], {"a.org/m@v1.1.0": 1})

    def test_success_clears_failure(self):
        r, _ = self.run_with({}, failures={"a.org/m@v1.1.0": 2})
        self.assertEqual(r["failures"], {})

    def test_gives_up_after_max_failures(self):
        r, _ = self.run_with({"a.org/m@v1.1.0": False}, failures={"a.org/m@v1.1.0": build.MAX_FAILURES - 1})
        self.assertEqual(r["gave_up"], ["a.org/m@v1.1.0"])
        self.assertEqual(r["failures"], {})
        self.assertEqual(r["position"], "2026-11-12T01:00:03Z")

"""The position file check the heartbeat job runs, and fetch asking the
proxy again after a 429."""

import os
import subprocess
import tempfile
import unittest

from builder import position, xotool


class PositionTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(position.valid({"since": "2026-11-12T13:31:40Z", "heartbeat": "2026-11-12T15:53:10Z"}))
        # what run 43251730335 wrote: a failure count is part of the position
        self.assertTrue(position.valid({"since": "2026-11-12T13:31:40Z", "heartbeat": "2026-11-12T15:53:10Z",
                                        "failures": {"github.com/xo-lang/gcp/ondemandscanning/apiv1beta1@v0.1.0": 1}}))
        self.assertTrue(position.valid({}))

    def test_invalid(self):
        for d in ([], {"since": "yesterday"}, {"extra": 1}, {"since": 5},
                  {"failures": []}, {"failures": {"a b@v1.0.0": 1}}, {"failures": {"x@v1.0.0": 0}},
                  {"failures": {"x@v1.0.0": True}}, {"failures": {"x@v1.0.0": "1"}}, {"failures": {"x": 1}},
                  {"failures": {"x@v1.0.0\n": 1}}):
            self.assertFalse(position.valid(d), d)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "p.json")
            script = os.path.join(os.path.dirname(position.__file__), "position.py")
            for body, rc in (('{"since":"2026-11-12T13:31:40Z","failures":{"x.org/m@v1.0.0":2}}', 0), ('{"x":1}', 1)):
                with open(p, "w") as f:
                    f.write(body)
                self.assertEqual(subprocess.run(["python3", "-I", script, p]).returncode, rc)


class FetchRetryTest(unittest.TestCase):
    def tool(self, t, outcomes):
        tool = xotool.Tool("/bin/true", t, "https://proxy.invalid", "off")
        waits, calls = [], []
        tool.sleep = waits.append
        d = os.path.join(tool.modcache, "x.org/m@v1.0.0")

        def run(args, cwd, offline, timeout):
            calls.append(args)
            ok, err = outcomes[len(calls) - 1]
            if ok:
                os.makedirs(d, exist_ok=True)
                open(os.path.join(d, "xo.mod"), "w").close()
            return subprocess.CompletedProcess(args, 0 if ok else 1, b"", err)
        tool.run = run
        return tool, waits, calls, d

    def test_429_then_ok(self):
        with tempfile.TemporaryDirectory() as t:
            tool, waits, calls, d = self.tool(t, [(False, b"error XO1302: 429 Too Many Requests: <!doctype html>\nnote: proxy"), (True, b"")])
            self.assertEqual(tool.fetch("x.org/m", "v1.0.0"), d)
            self.assertEqual(waits, [15])
            self.assertEqual(len(calls), 2)

    def test_429_gives_up(self):
        with tempfile.TemporaryDirectory() as t:
            tool, waits, calls, _ = self.tool(t, [(False, b"429 Too Many Requests")] * 3)
            with self.assertRaises(RuntimeError):
                tool.fetch("x.org/m", "v1.0.0")
            self.assertEqual(waits, [15, 60])
            self.assertEqual(len(calls), 3)

    def test_other_errors_not_retried(self):
        with tempfile.TemporaryDirectory() as t:
            tool, waits, calls, _ = self.tool(t, [(False, b"404 Not Found")])
            with self.assertRaises(RuntimeError):
                tool.fetch("x.org/m", "v1.0.0")
            self.assertEqual((waits, len(calls)), ([], 1))


if __name__ == "__main__":
    unittest.main()

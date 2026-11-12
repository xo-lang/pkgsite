"""load_doc reads a stored doc JSON again after a dropped connection or a
body cut short, and not after a 404."""

import http.client
import io
import json
import unittest
import urllib.error

from builder import build

REC = {"schema": 1, "path": "x.org/m", "version": "v1.0.0"}


class DocRetryTest(unittest.TestCase):
    def setUp(self):
        self.get, self.sleep, self.check = build.http_get, build.SLEEP, build.check_doc
        self.waits = []
        build.SLEEP = self.waits.append
        build.check_doc = lambda rec, path, version: rec

    def tearDown(self):
        build.http_get, build.SLEEP, build.check_doc = self.get, self.sleep, self.check

    def answers(self, *xs):
        it = iter(xs)

        def get(url, **kw):
            x = next(it)
            if isinstance(x, Exception):
                raise x
            return x
        build.http_get = get

    def test_dropped_then_cut_then_whole(self):
        body = json.dumps(REC).encode()
        self.answers(http.client.RemoteDisconnected("Remote end closed connection without response"), body[:10], body)
        self.assertEqual(build.load_doc("https://pkg.example", "x.org/m", "v1.0.0"), REC)
        self.assertEqual(self.waits, [2, 10])

    def test_gives_up(self):
        self.answers(*([b"{"] * 3))
        with self.assertRaises(ValueError):
            build.load_doc("https://pkg.example", "x.org/m", "v1.0.0")
        self.assertEqual(self.waits, [2, 10])

    def test_404_not_retried(self):
        self.answers(urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO()))
        with self.assertRaises(urllib.error.HTTPError):
            build.load_doc("https://pkg.example", "x.org/m", "v1.0.0")
        self.assertEqual(self.waits, [])


if __name__ == "__main__":
    unittest.main()

"""The builder's two stages and the rebuild path (fetch and xo doc are
faked): python3 -E -s -m unittest discover -s tests -t ."""

import json
import os
import tempfile
import unittest

from builder import build, render

from tests.test_builder import MIT

ROOT = "github.com/xo-lang/aws/service/s3"


def doc(name, summary="does a thing"):
    return {"module": name, "doc": "Package doc.", "functions": [{"name": "Get", "signature": "fn get() -> Int", "doc": summary}]}


class FakeTool:
    """fetch writes a module directory (licensed unless told otherwise);
    doc_walk answers its packages; version is the xo version."""

    def __init__(self, base, licensed=True, fail=(), xo="0.49.1"):
        self.base, self.licensed, self.fail, self.xo = base, licensed, set(fail), xo
        self.fetched = []

    def version(self):
        return self.xo

    def fetch(self, path, version):
        if path + "@" + version in self.fail:
            raise RuntimeError("not found")
        self.fetched.append(path + "@" + version)
        d = os.path.join(self.base, path.replace("/", "_") + "@" + version)
        os.makedirs(os.path.join(d, "sub"), exist_ok=True)
        if self.licensed:
            with open(os.path.join(d, "LICENSE"), "w") as f:
                f.write(MIT)
        for rel in ("", "sub"):
            with open(os.path.join(d, rel, "a.xo"), "w") as f:
                f.write("pub fn get() -> Int { 1 }\n")
        return d

    def doc_walk(self, d, path):
        return {"": doc(path), "sub": doc(path + "/sub", "the sub one")}


def read(site, rel):
    with open(os.path.join(site, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


class StagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = os.path.join(self.tmp.name, "site")
        self.tool = FakeTool(os.path.join(self.tmp.name, "mods"))
        render.BUILD.update({"xo": "0.49.1", "date": "2026-11-12"})

    def tearDown(self):
        self.tmp.cleanup()
        render.BUILD.update({"xo": "", "date": ""})

    def test_full_build_stores_doc_json_and_records_versions(self):
        cat = {"schema": 1, "modules": {}}
        self.assertTrue(build.build_version(self.tool, self.site, cat, ROOT, "v0.1.0"))
        rec = json.loads(read(self.site, build.doc_rel(ROOT, "v0.1.0")))
        self.assertEqual((rec["schema"], rec["path"], rec["version"], rec["xo"]), (build.DOC_SCHEMA, ROOT, "v0.1.0", "0.49.1"))
        self.assertEqual(rec["license"], [["LICENSE", "MIT"]])
        self.assertEqual(sorted(rec["docs"]), ["", "sub"])
        b = cat["modules"][ROOT]["builds"]["v0.1.0"]
        self.assertEqual((b["xo"], b["renderer"], b["packages"], b["docs"]), ("0.49.1", build.RENDERER, ["", "sub"], True))
        self.assertIn("the sub one", read(self.site, ROOT + "@v0.1.0/sub/index.html"))

    def test_render_only_matches_full_build(self):
        cat = {"schema": 1, "modules": {}}
        build.build_version(self.tool, self.site, cat, ROOT, "v0.1.0")
        pages = {rel: read(self.site, rel) for rel in (ROOT + "@v0.1.0/index.html", ROOT + "@v0.1.0/sub/index.html")}
        for rel in pages:
            os.remove(os.path.join(self.site, *rel.split("/")))
        cat2 = {"schema": 1, "modules": {}}
        render.BUILD["xo"] = ""  # stage (b) runs no xo: the record says which made the docs
        build.render_version(self.site, cat2, build.load_doc(self.site, ROOT, "v0.1.0"))
        for rel, html in pages.items():
            self.assertEqual(read(self.site, rel), html, rel)
        self.assertEqual(cat2["modules"][ROOT]["builds"]["v0.1.0"], cat["modules"][ROOT]["builds"]["v0.1.0"])
        self.assertEqual(render.BUILD["xo"], "", "render_version restores BUILD")

    def test_unlicensed_stores_no_docs(self):
        tool = FakeTool(os.path.join(self.tmp.name, "mods"), licensed=False)
        cat = {"schema": 1, "modules": {}}
        build.build_version(tool, self.site, cat, ROOT, "v0.1.0")
        rec = json.loads(read(self.site, build.doc_rel(ROOT, "v0.1.0")))
        self.assertEqual(rec["docs"], {})
        self.assertFalse(cat["modules"][ROOT]["builds"]["v0.1.0"]["docs"])
        self.assertFalse(os.path.exists(os.path.join(self.site, *(ROOT + "@v0.1.0/sub/index.html").split("/"))))

    def test_fetch_failure_writes_nothing(self):
        tool = FakeTool(os.path.join(self.tmp.name, "mods"), fail={ROOT + "@v0.1.0"})
        cat = {"schema": 1, "modules": {}}
        self.assertFalse(build.build_version(tool, self.site, cat, ROOT, "v0.1.0"))
        self.assertEqual(cat["modules"], {})
        self.assertFalse(os.path.exists(os.path.join(self.site, "_doc")))

    def test_check_doc_rejects_wrong_records(self):
        good = {"schema": build.DOC_SCHEMA, "path": ROOT, "version": "v0.1.0", "license": [], "docs": {}}
        self.assertIs(build.check_doc(good, ROOT, "v0.1.0"), good)
        for bad in (dict(good, schema=99), dict(good, version="v0.2.0"), dict(good, path="a.org/x"),
                    {k: v for k, v in good.items() if k != "docs"}, [], None):
            with self.assertRaises(ValueError):
                build.check_doc(bad, ROOT, "v0.1.0")


def catalog_of(entries):
    """{path: {version: build}} as a catalog."""
    return {"schema": 1, "modules": {p: {"versions": sorted(bs), "builds": bs} for p, bs in entries.items()}}


class SelectTest(unittest.TestCase):
    CAT = catalog_of({
        "github.com/xo-lang/aws": {"v0.1.0": {"renderer": build.RENDERER, "xo": "0.49.1"}},
        "github.com/xo-lang/aws/service/s3": {"v0.10.0": {"xo": "0.49.1"}, "v0.2.0": {"renderer": build.RENDERER, "xo": "0.48.0"}},
        "github.com/xo-lang/awsx": {"v0.1.0": {}},
        "github.com/xo-lang/gcp/bigquery/apiv2": {"v0.1.0": {"renderer": build.RENDERER, "xo": "0.49.1"}},
    })

    def test_all_sorted_by_version(self):
        got = build.select_versions(self.CAT, "all", "render", False)
        self.assertEqual(got[1:3], [("github.com/xo-lang/aws/service/s3", "v0.2.0"), ("github.com/xo-lang/aws/service/s3", "v0.10.0")])
        self.assertEqual(len(got), 5)

    def test_sdk_is_its_repository_not_a_prefix(self):
        got = {p for p, _ in build.select_versions(self.CAT, "aws", "render", False)}
        self.assertEqual(got, {"github.com/xo-lang/aws", "github.com/xo-lang/aws/service/s3"})

    def test_pattern(self):
        got = build.select_versions(self.CAT, "github.com/xo-lang/gcp/*", "render", False)
        self.assertEqual(got, [("github.com/xo-lang/gcp/bigquery/apiv2", "v0.1.0")])

    def test_stale_render_is_an_older_renderer(self):
        got = build.select_versions(self.CAT, "all", "render", True)
        self.assertEqual(got, [("github.com/xo-lang/aws/service/s3", "v0.10.0"), ("github.com/xo-lang/awsx", "v0.1.0")])

    def test_stale_full_is_also_an_older_xo(self):
        got = build.select_versions(self.CAT, "all", "full", True, xo="0.49.1")
        self.assertIn(("github.com/xo-lang/aws/service/s3", "v0.2.0"), got)
        self.assertNotIn(("github.com/xo-lang/aws", "v0.1.0"), got)

    def test_shards_cover_everything_once(self):
        items = list(range(23))
        shards = [build.shard_of(items, "%d/5" % i) for i in range(5)]
        self.assertEqual(sorted(x for s in shards for x in s), items)
        self.assertEqual(build.shard_of(items, ""), items)
        for bad in ("5/5", "-1/5", "x/5"):
            with self.assertRaises(ValueError):
                build.shard_of(items, bad)


class RebuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pub = os.path.join(self.tmp.name, "published")
        self.tool = FakeTool(os.path.join(self.tmp.name, "mods"))
        render.BUILD.update({"xo": "0.49.1", "date": "2026-11-12"})
        # a published site: two versions built with both stages, one old
        # version built before doc JSON was stored
        self.cat = {"schema": 1, "modules": {}}
        for v in ("v0.1.0", "v0.2.0"):
            build.build_version(self.tool, self.pub, self.cat, ROOT, v)
        self.cat["modules"][ROOT]["versions"].append("v0.0.9")
        self.cat["modules"][ROOT]["builds"]["v0.0.9"] = {"docs": True, "license": ["MIT"], "packages": [""]}
        build.finish(self.pub, self.cat, {ROOT})
        self.catfile = os.path.join(self.pub, "catalog.json")

    def tearDown(self):
        self.tmp.cleanup()
        render.BUILD.update({"xo": "", "date": ""})

    def shard_run(self, site, i, n, stage="render", stale=False):
        cat = build.load_catalog(self.catfile)
        todo = build.shard_of(build.select_versions(cat, "aws", stage, stale, "0.49.1"), "%d/%d" % (i, n))
        part, failed = build.rebuild(todo, stage, site, cat, self.tool, self.pub)
        build.write_part(site, "shard-%d-of-%d" % (i, n), part)
        return failed

    def test_render_shards_then_finish(self):
        site = os.path.join(self.tmp.name, "site")
        # the published entry an older renderer made: the parts replace it
        with open(self.catfile) as f:
            pub = json.load(f)
        pub["modules"][ROOT]["builds"]["v0.1.0"]["renderer"] = 0
        with open(self.catfile, "w") as f:
            json.dump(pub, f)
        before = len(self.tool.fetched)
        failed = self.shard_run(site, 0, 2) + self.shard_run(site, 1, 2)
        self.assertEqual(failed, [ROOT + "@v0.0.9"], "a version with no stored doc JSON needs a full rebuild")
        self.assertEqual(len(self.tool.fetched), before, "render only fetches nothing")
        cat = build.load_catalog(self.catfile)
        touched = build.finish_parts(site, cat)
        self.assertEqual(touched, {ROOT})
        self.assertFalse(os.path.exists(os.path.join(site, build.PARTS)))
        out = json.loads(read(site, "catalog.json"))
        b = out["modules"][ROOT]["builds"]
        self.assertEqual(sorted(b), ["v0.0.9", "v0.1.0", "v0.2.0"], "the parts merge into the whole catalog")
        self.assertEqual(b["v0.1.0"]["renderer"], build.RENDERER)
        self.assertNotIn("renderer", b["v0.0.9"])
        self.assertIn("v0.2.0", read(site, ROOT + "/versions.html"))
        self.assertTrue(os.path.exists(os.path.join(site, *(ROOT + "@v0.2.0/sub/index.html").split("/"))))

    def test_full_stale_rebuild_fixes_the_old_version(self):
        site = os.path.join(self.tmp.name, "site")
        failed = self.shard_run(site, 0, 1, stage="full", stale=True)
        self.assertEqual(failed, [])
        self.assertEqual(self.tool.fetched[-1], ROOT + "@v0.0.9", "only the stale version is fetched")
        self.assertTrue(os.path.exists(os.path.join(site, *build.doc_rel(ROOT, "v0.0.9").split("/"))))

    def test_cli_never_touches_the_position(self):
        state = os.path.join(self.tmp.name, "state")
        os.makedirs(state)
        pos = os.path.join(state, "position.json")
        with open(pos, "w") as f:
            f.write('{"since": "2026-11-12T00:00:00Z"}\n')
        site = os.path.join(self.tmp.name, "site")
        rc = build.main(["--site", site, "--state", state, "--catalog", self.catfile, "--rebuild", "aws",
                         "--docs", self.pub, "--shard", "0/1"])
        self.assertEqual(rc, 0)
        with open(pos) as f:
            self.assertEqual(json.load(f), {"since": "2026-11-12T00:00:00Z"})
        self.assertTrue(os.path.exists(os.path.join(site, build.PARTS, "shard-0-of-1.json")))
        self.assertFalse(os.path.exists(os.path.join(site, "catalog.json")), "a shard writes no catalog")
        for bad in (["--advance"], ["--module", ROOT + "@v0.1.0"], ["--std"], ["--max", "3"], ["--finish-parts"]):
            with self.assertRaises(SystemExit):
                build.main(["--site", site, "--catalog", self.catfile, "--rebuild", "aws"] + bad)
        with self.assertRaises(SystemExit):
            build.main(["--site", site, "--catalog", self.catfile, "--rebuild", "aws", "--stage", "full"])


if __name__ == "__main__":
    unittest.main()

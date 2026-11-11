"""Every std module's summary, from the declaration files of an xo
release: XO_STD_DIR (its lib/xo/std); skipped when it is not set. The
workflow runs this after installing xo."""
import os
import re
import unittest

from builder import render

STD = os.environ.get("XO_STD_DIR", "")


@unittest.skipUnless(STD and os.path.isdir(STD), "XO_STD_DIR is not set")
class EveryStdModuleTest(unittest.TestCase):
    def test_summaries(self):
        names = sorted(f[:-3] for f in os.listdir(STD) if f.endswith(".xo") and not f.endswith("_test.xo"))
        self.assertGreater(len(names), 50)
        bad = []
        for n in names:
            with open(os.path.join(STD, n + ".xo"), encoding="utf-8") as f:
                p = render.std_paragraph(f.read(), "std/" + n)
            s = render.first_sentence(p)
            why = []
            if not s.strip():
                why.append("empty")
            if re.search(r"\bPure\.|Declaration file|Notes for this file|std/prelude\.xo|encoding rules", s):
                why.append("boilerplate")
            if re.match(r"std/\w+\s*[(:]", s) or re.search(r"\((?:decision|spec/)", s):
                why.append("reference")
            if s.endswith("..."):
                why.append("cut")
            if s[:1].islower() and not re.match(r"[a-z]+[A-Z/.']", s.split(" ")[0]):
                why.append("lower case start")
            if why:
                bad.append("std/%s: %s: %r" % (n, ", ".join(why), s[:120]))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

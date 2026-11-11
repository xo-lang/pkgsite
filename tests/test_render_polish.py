import unittest

from builder import render


BCRYPT = """// std/bcrypt (spec/std.md 53). Declaration file. golang.org/x/crypto/bcrypt:
// password hashes in the bcrypt format, `hash` and `compare`. Passwords
// are bytes.

const MIN_COST: Int = 4
"""

HTTP = """// std/http (spec/std.md 4). Declaration file; encoding rules are listed at
// the top of std/prelude.xo. Notes for this file:
//
// - Router is opaque.
"""

ADLER = """// std/adler32 (spec/std.md 60). Declaration file. Go's hash/adler32: the
// checksum of zlib (RFC 1950).
"""


class StdParagraphTest(unittest.TestCase):
    def test_port_prefix_moves_to_the_end_of_the_first_sentence(self):
        p = render.std_paragraph(BCRYPT, "std/bcrypt")
        self.assertEqual(p, "Password hashes in the bcrypt format, `hash` and `compare` (port of golang.org/x/crypto/bcrypt). Passwords are bytes.")
        self.assertEqual(render.first_sentence(p), "Password hashes in the bcrypt format, `hash` and `compare` (port of golang.org/x/crypto/bcrypt).")

    def test_gos_prefix(self):
        self.assertEqual(render.std_paragraph(ADLER, "std/adler32"), "The checksum of zlib (RFC 1950) (port of Go's hash/adler32).")

    def test_notes_only_header_falls_back(self):
        self.assertEqual(render.std_paragraph(HTTP, "std/http"), render.STD_FALLBACK["std/http"])
        self.assertEqual(render.std_paragraph(HTTP, "std/other"), "")

    def test_reference_in_the_opening_and_pure(self):
        # the opening's parenthesis is a decision; "Pure." and a later
        # "(decision 0087)." are not the summary
        src = ("// std/timego (decision 0537): Go's time layouts for code ported from Go: Go's own\n"
               "// layout scanner over core time's civil functions. The core API is unchanged (decision 0087).\n"
               "// Declaration file. Pure.\nuse std/time\n")
        self.assertEqual(render.std_paragraph(src, "std/timego"),
                         "Go's time layouts for code ported from Go: Go's own layout scanner over core time's civil functions.")

    def test_first_sentence_keeps_abbreviations_and_whole_text(self):
        self.assertEqual(render.first_sentence("Uses e.g. this. Then more."), "Uses e.g. this.")
        self.assertEqual(render.first_sentence("no end"), "no end")


class InlineCodeTest(unittest.TestCase):
    def test_code_spans(self):
        self.assertEqual(render.inline_code("`hash` and <b>"), "<code>hash</code> and &lt;b&gt;")
        self.assertEqual(render.inline_code("odd ` tick"), "odd ` tick")


class FooterTest(unittest.TestCase):
    def test_port_notice(self):
        self.assertIn("OpenAI is a trademark", render.port_notice("github.com/xo-lang/openai/azure"))
        self.assertIn("Amazon.com", render.port_notice("github.com/xo-lang/aws"))
        self.assertEqual(render.port_notice("github.com/xo-lang/awsx"), "")
        self.assertEqual(render.port_notice("example.com/m"), "")

    def test_repo_url(self):
        self.assertEqual(render.repo_url("github.com/xo-lang/openai/azure"), "https://github.com/xo-lang/openai")
        self.assertEqual(render.repo_url("example.com/m"), "")

    def test_footer_escapes_and_links(self):
        f = render.footer("https://github.com/a/b", "License: MIT.", "Generated <x>.", "")
        self.assertIn('href="https://xolang.dev/"', f)
        self.assertIn('>GitHub a/b</a>', f)
        self.assertNotIn('github.com/xo-lang/xo"', f)
        self.assertIn('>GitHub xo-lang/xo</a>', render.footer("https://github.com/xo-lang/xo/tree/v0.46.0/std"))
        self.assertIn('href="https://github.com/xo-lang/xo"', render.footer())
        self.assertIn("Generated &lt;x&gt;.", f)

    def test_every_page_has_a_footer_and_one_container(self):
        html = render.page("t", "b")
        self.assertIn("<footer>", html)
        self.assertIn('<main class="wrap">', html)
        self.assertIn('<header class="top"><div class="wrap">', html)


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import unittest

from helpers import VALID_SVG, RepoTestCase, make_png

import check_assets
from check_assets import check_assets as run_check
from findings import ERROR, WARNING


def summary(findings):
    return sorted((f.path, f.level) for f in findings)


class SvgTests(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.write("README.md", "assets/a.svg assets/b.svg\n")

    def test_valid_svg_is_ok(self):
        self.write("assets/a.svg", VALID_SVG)
        self.assertEqual(run_check(self.root), [])

    def test_malformed_svg_is_error(self):
        self.write("assets/a.svg", "<svg><rect></svg>")
        self.assertEqual(summary(run_check(self.root)), [("assets/a.svg", ERROR)])

    def test_xml_that_is_not_svg_is_error(self):
        self.write("assets/a.svg", "<html><body/></html>")
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.svg", ERROR)])
        self.assertIn("html", findings[0].message)

    def test_script_element_warns(self):
        self.write("assets/a.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        self.assertEqual(summary(run_check(self.root)), [("assets/a.svg", WARNING)])

    def test_event_handler_warns(self):
        self.write("assets/a.svg", '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
        self.assertEqual(summary(run_check(self.root)), [("assets/a.svg", WARNING)])

    def test_unrelated_attribute_starting_with_on_is_not_flagged_as_handler_only_if_it_is(self):
        # "onload" es un manejador; "opacity" no empieza por "on" y no debe avisar.
        self.write("assets/a.svg", '<svg xmlns="http://www.w3.org/2000/svg"><rect opacity="0.5"/></svg>')
        self.assertEqual(run_check(self.root), [])

    def test_entity_declaration_is_not_parsed_and_warns(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>'
        self.write("assets/a.svg", bomb)
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.svg", WARNING)])
        self.assertIn("ENTITY", findings[0].message)

    def test_uppercase_extension_is_checked(self):
        self.write("assets/a.SVG", "<svg>")
        self.write("README.md", "a.svg\n")
        self.assertEqual(summary(run_check(self.root)), [("assets/a.SVG", ERROR)])

    def test_empty_file_is_error(self):
        self.write("assets/a.svg", b"")
        self.assertEqual(summary(run_check(self.root)), [("assets/a.svg", ERROR)])


class RasterTests(RepoTestCase):
    def test_valid_png_is_ok(self):
        self.write("assets/a.png", make_png(4, 4))
        self.write("README.md", "a.png\n")
        self.assertEqual(run_check(self.root), [])

    def test_png_truncated_in_the_middle_is_error(self):
        self.write("assets/a.png", make_png(4, 4)[:-20])
        self.write("README.md", "a.png\n")
        self.assertEqual(summary(run_check(self.root)), [("assets/a.png", ERROR)])

    def test_png_missing_iend_is_error(self):
        data = make_png(4, 4)
        self.write("assets/a.png", data[: -12])  # quita justo el bloque IEND (12 bytes)
        self.write("README.md", "a.png\n")
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.png", ERROR)])
        self.assertIn("IEND", findings[0].message)

    def test_text_file_named_png_is_error(self):
        self.write("assets/a.png", "esto no es una imagen")
        self.write("README.md", "a.png\n")
        self.assertEqual(summary(run_check(self.root)), [("assets/a.png", ERROR)])

    def test_git_lfs_pointer_is_error(self):
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12345\n"
        self.write("assets/a.png", pointer)
        self.write("README.md", "a.png\n")
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.png", ERROR)])
        self.assertIn("LFS", findings[0].message)

    def test_jpeg_with_png_extension_warns(self):
        self.write("assets/a.png", b"\xff\xd8\xff\xe0" + b"\x00" * 32)
        self.write("README.md", "a.png\n")
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.png", WARNING)])
        self.assertIn("jpeg", findings[0].message)

    def test_gif_and_webp_signatures(self):
        self.write("assets/a.gif", b"GIF89a" + b"\x00" * 16)
        self.write("assets/b.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8)
        self.write("README.md", "a.gif b.webp\n")
        self.assertEqual(run_check(self.root), [])

    def test_oversized_image_warns(self):
        self.write("assets/a.png", make_png(2, 2))
        self.write("README.md", "a.png\n")
        findings = run_check(self.root, max_size=10)
        self.assertEqual(summary(findings), [("assets/a.png", WARNING)])
        self.assertIn("pesa", findings[0].message)


class FolderTests(RepoTestCase):
    def test_missing_assets_folder_returns_nothing(self):
        self.write("README.md", "hola\n")
        self.assertEqual(run_check(self.root), [])

    def test_unreferenced_asset_warns(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "sin imágenes\n")
        findings = run_check(self.root)
        self.assertEqual(summary(findings), [("assets/a.svg", WARNING)])
        self.assertIn("README.md", findings[0].message)

    def test_reference_with_url_encoding_counts_as_mentioned(self):
        self.write("assets/mi imagen.svg", VALID_SVG)
        self.write("README.md", "![x](assets/mi%20imagen.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_mention_is_case_insensitive(self):
        self.write("assets/Logo.SVG", VALID_SVG)
        self.write("README.md", "![x](assets/logo.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_missing_readme_skips_the_mention_check(self):
        self.write("assets/a.svg", VALID_SVG)
        self.assertEqual(run_check(self.root), [])

    def test_other_file_types_are_ignored(self):
        self.write("assets/notas.txt", "cualquier cosa")
        self.write("assets/datos.json", "{")
        self.write("README.md", "hola\n")
        self.assertEqual(run_check(self.root), [])

    def test_nested_folders_are_walked(self):
        self.write("assets/iconos/a.svg", "<svg>")
        self.write("README.md", "a.svg\n")
        self.assertEqual(summary(run_check(self.root)), [("assets/iconos/a.svg", ERROR)])


class MainTests(RepoTestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_assets.main([*argv, "--root", str(self.root)])
        return code, out.getvalue()

    def test_no_assets_folder_is_not_a_failure(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("no existe", out)

    def test_exit_0_when_everything_is_fine(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "a.svg\n")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("0 errores", out)

    def test_exit_1_on_error(self):
        self.write("assets/a.svg", "<svg>")
        self.write("README.md", "a.svg\n")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("assets/a.svg: error:", out)

    def test_warnings_pass_unless_strict(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "sin menciones\n")
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--strict")[0], 1)


if __name__ == "__main__":
    unittest.main()

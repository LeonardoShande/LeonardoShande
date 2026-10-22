import contextlib
import io
import unittest

from helpers import VALID_SVG, RepoTestCase

import check_readme
from check_readme import check_readme as run_check
from findings import ERROR, WARNING

REPO = "LeonardoShande/LeonardoShande"


def levels(findings):
    return sorted((f.level, f.line) for f in findings)


class RelativePathTests(RepoTestCase):
    def test_existing_image_is_ok(self):
        self.write("assets/logo.svg", VALID_SVG)
        self.write("README.md", "![Logo](assets/logo.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_missing_image_is_error_with_line_number(self):
        self.write("README.md", "# Hola\n\n![Logo](assets/no-existe.svg)\n")
        findings = run_check(self.root)
        self.assertEqual(levels(findings), [(ERROR, 3)])
        self.assertIn("assets/no-existe.svg", findings[0].message)

    def test_dot_slash_and_leading_slash_paths(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "![a](./assets/a.svg) ![b](/assets/a.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_url_encoded_path_is_decoded(self):
        self.write("assets/mi imagen.svg", VALID_SVG)
        self.write("README.md", "![x](assets/mi%20imagen.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_angle_bracket_destination_with_spaces(self):
        self.write("assets/mi imagen.svg", VALID_SVG)
        self.write("README.md", "![x](<assets/mi imagen.svg>)\n")
        self.assertEqual(run_check(self.root), [])

    def test_query_and_fragment_are_ignored(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "![x](assets/a.svg?raw=true#frag)\n")
        self.assertEqual(run_check(self.root), [])

    def test_link_title_is_ignored(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", '![x](assets/a.svg "Título de la imagen")\n')
        self.assertEqual(run_check(self.root), [])

    def test_link_to_missing_markdown_file(self):
        self.write("README.md", "[ver](docs/guia.md)\n")
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 1)])

    def test_directory_link_is_ok(self):
        (self.root / "assets").mkdir()
        self.write("README.md", "[carpeta](assets)\n")
        self.assertEqual(run_check(self.root), [])

    def test_path_outside_repo_is_only_a_warning(self):
        self.write("README.md", "[incidencias](../../issues)\n")
        self.assertEqual(levels(run_check(self.root)), [(WARNING, 1)])

    def test_anchor_mailto_and_other_schemes_are_ignored(self):
        self.write(
            "README.md",
            "[a](#seccion) [b](mailto:yo@correo.com) [c](tel:+51999999999) [d](data:image/png;base64,AAAA)\n",
        )
        self.assertEqual(run_check(self.root), [])

    def test_linked_image_checks_both_destinations(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "[![Terminal](assets/a.svg)](assets/otra.svg)\n")
        findings = run_check(self.root)
        self.assertEqual(levels(findings), [(ERROR, 1)])
        self.assertIn("otra.svg", findings[0].message)

    def test_reference_style_definition(self):
        self.write("README.md", "![x][img]\n\n[img]: assets/falta.png\n")
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 3)])

    def test_footnote_and_plain_bracket_lines_are_not_links(self):
        self.write("README.md", "Texto[^1]\n\n[^1]: Una nota.\n[ES]: Hola\n")
        self.assertEqual(run_check(self.root), [])


class HtmlTests(RepoTestCase):
    def test_img_src_missing(self):
        self.write("README.md", '<img src="assets/falta.png" alt="x">\n')
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 1)])

    def test_single_quoted_attribute_and_anchor_href(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "<a href='assets/a.svg'><img src='assets/a.svg' alt='x'></a>\n")
        self.assertEqual(run_check(self.root), [])

    def test_srcset_checks_every_candidate(self):
        self.write("assets/a.png", b"x")
        self.write("README.md", '<img alt="x" srcset="assets/a.png 1x, assets/b.png 2x">\n')
        findings = run_check(self.root)
        self.assertEqual(levels(findings), [(ERROR, 1)])
        self.assertIn("b.png", findings[0].message)

    def test_picture_source_srcset(self):
        self.write("README.md", '<picture><source srcset="assets/dark.png"><img alt="x" src="https://example.com/a.png"></picture>\n')
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 1)])


class IgnoredContentTests(RepoTestCase):
    def test_fenced_code_block_is_ignored(self):
        self.write("README.md", "```md\n![x](assets/falta.png)\n```\n")
        self.assertEqual(run_check(self.root), [])

    def test_tilde_fence_and_longer_fence(self):
        self.write("README.md", "~~~\n![x](assets/falta.png)\n~~~\n\n````\n```\n![y](assets/falta2.png)\n```\n````\n")
        self.assertEqual(run_check(self.root), [])

    def test_inline_code_is_ignored(self):
        self.write("README.md", "Escribe `![x](assets/falta.png)` para insertar una imagen.\n")
        self.assertEqual(run_check(self.root), [])

    def test_html_comment_is_ignored(self):
        self.write("README.md", "<!--\n![x](assets/falta.png)\n-->\n![y](assets/tambien-falta.png)\n")
        # Solo cuenta la línea 4, la de fuera del comentario.
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 4)])

    def test_line_numbers_survive_stripping(self):
        self.write("README.md", "```\ncodigo\n```\n`a`\n\n![x](assets/falta.png)\n")
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 6)])


class GithubUrlTests(RepoTestCase):
    def test_raw_url_to_this_repo_existing(self):
        self.write("assets/terminal.svg", VALID_SVG)
        url = f"https://github.com/{REPO}/raw/main/assets/terminal.svg"
        self.write("README.md", f"![x]({url})\n")
        self.assertEqual(run_check(self.root, repo=REPO), [])

    def test_raw_url_to_this_repo_missing(self):
        url = f"https://github.com/{REPO}/raw/main/assets/falta.svg"
        self.write("README.md", f"![x]({url})\n")
        findings = run_check(self.root, repo=REPO)
        self.assertEqual(levels(findings), [(ERROR, 1)])
        self.assertIn("assets/falta.svg", findings[0].message)

    def test_blob_and_raw_githubusercontent_variants(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write(
            "README.md",
            f"[a](https://github.com/{REPO}/blob/main/assets/a.svg) "
            f"![b](https://raw.githubusercontent.com/{REPO}/main/assets/a.svg)\n",
        )
        self.assertEqual(run_check(self.root, repo=REPO), [])

    def test_branch_name_with_slash(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", f"![a](https://github.com/{REPO}/raw/feature/x/assets/a.svg)\n")
        self.assertEqual(run_check(self.root, repo=REPO), [])

    def test_owner_and_repo_are_case_insensitive(self):
        self.write("README.md", "![a](https://github.com/leonardoshande/LEONARDOSHANDE/raw/main/assets/falta.svg)\n")
        self.assertEqual(levels(run_check(self.root, repo=REPO)), [(ERROR, 1)])

    def test_other_repositories_are_ignored(self):
        self.write("README.md", "![a](https://github.com/otro/repo/raw/main/assets/falta.svg)\n")
        self.assertEqual(run_check(self.root, repo=REPO), [])

    def test_unrelated_github_pages_are_ignored(self):
        self.write("README.md", f"[issues](https://github.com/{REPO}/issues) [perfil](https://github.com/LeonardoShande)\n")
        self.assertEqual(run_check(self.root, repo=REPO), [])

    def test_without_repo_absolute_urls_are_not_checked(self):
        self.write("README.md", f"![a](https://github.com/{REPO}/raw/main/assets/falta.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_external_urls_are_not_checked_here(self):
        self.write("README.md", "![a](https://example.com/falta.png) [b](http://example.com)\n")
        self.assertEqual(run_check(self.root, repo=REPO), [])


class AltTextTests(RepoTestCase):
    def test_markdown_image_without_alt_warns(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "![](assets/a.svg)\n")
        self.assertEqual(levels(run_check(self.root)), [(WARNING, 1)])

    def test_html_image_without_alt_warns(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", '<img src="assets/a.svg">\n')
        self.assertEqual(levels(run_check(self.root)), [(WARNING, 1)])

    def test_html_image_with_alt_is_ok(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", '<img src="assets/a.svg" alt="Logo">\n')
        self.assertEqual(run_check(self.root), [])


class EdgeCaseTests(RepoTestCase):
    def test_empty_readme_is_error(self):
        self.write("README.md", "  \n\n")
        self.assertEqual(levels(run_check(self.root)), [(ERROR, 1)])

    def test_utf8_bom_is_handled(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", b"\xef\xbb\xbf![x](assets/a.svg)\n")
        self.assertEqual(run_check(self.root), [])

    def test_readme_in_subfolder_resolves_relative_to_it(self):
        self.write("docs/img/a.svg", VALID_SVG)
        self.write("docs/LEEME.md", "![x](img/a.svg)\n")
        self.assertEqual(run_check(self.root, "docs/LEEME.md"), [])

    def test_same_problem_is_reported_once_per_line(self):
        self.write("README.md", "![x](assets/falta.png)\n")
        self.assertEqual(len(run_check(self.root)), 1)


class MainTests(RepoTestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_readme.main([*argv, "--root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_exit_0_when_everything_is_fine(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "![x](assets/a.svg)\n")
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("0 errores", out)

    def test_exit_1_on_error(self):
        self.write("README.md", "![x](assets/falta.png)\n")
        code, out, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("README.md:1: error:", out)

    def test_exit_2_when_readme_is_missing(self):
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("README.md", err)

    def test_warnings_pass_unless_strict(self):
        self.write("assets/a.svg", VALID_SVG)
        self.write("README.md", "![](assets/a.svg)\n")
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--strict")[0], 1)

    def test_repo_flag_enables_absolute_url_checks(self):
        self.write("README.md", f"![x](https://github.com/{REPO}/raw/main/assets/falta.svg)\n")
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--repo", REPO)[0], 1)


if __name__ == "__main__":
    unittest.main()

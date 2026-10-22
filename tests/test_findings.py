import contextlib
import io
import os
import unittest
from unittest import mock

from helpers import SCRIPTS_DIR  # noqa: F401  (añade scripts/ al sys.path)

from findings import ERROR, WARNING, Finding, report


class FindingFormatTests(unittest.TestCase):
    def test_text_with_and_without_line(self):
        self.assertEqual(Finding("README.md", 3, ERROR, "mal").as_text(), "README.md:3: error: mal")
        self.assertEqual(Finding("assets/a.png", 0, WARNING, "ojo").as_text(), "assets/a.png: aviso: ojo")

    def test_github_annotation_levels_and_location(self):
        self.assertEqual(Finding("README.md", 3, ERROR, "mal").as_github_annotation(), "::error file=README.md,line=3::mal")
        self.assertEqual(Finding("a.png", 0, WARNING, "ojo").as_github_annotation(), "::warning file=a.png::ojo")

    def test_github_annotation_escapes_special_characters(self):
        annotation = Finding("a.md", 1, ERROR, "100%\nlisto").as_github_annotation()
        self.assertEqual(annotation, "::error file=a.md,line=1::100%25%0Alisto")


class ReportTests(unittest.TestCase):
    def run_report(self, findings, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            code = report(findings, "etiqueta", **kwargs)
        return code, out.getvalue()

    def test_no_findings(self):
        code, out = self.run_report([])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "etiqueta: 0 errores, 0 avisos")

    def test_singular_forms(self):
        _, out = self.run_report([Finding("a", 1, ERROR, "x"), Finding("b", 1, WARNING, "y")])
        self.assertIn("1 error, 1 aviso", out)

    def test_warnings_only_pass_unless_strict(self):
        warnings = [Finding("a", 1, WARNING, "x")]
        self.assertEqual(self.run_report(warnings)[0], 0)
        self.assertEqual(self.run_report(warnings, strict=True)[0], 1)

    def test_errors_fail(self):
        self.assertEqual(self.run_report([Finding("a", 1, ERROR, "x")])[0], 1)

    def test_output_is_sorted_by_file_and_line(self):
        _, out = self.run_report([Finding("b.md", 1, ERROR, "x"), Finding("a.md", 9, ERROR, "x"), Finding("a.md", 2, ERROR, "x")])
        lines = [line for line in out.splitlines() if "error:" in line]
        self.assertEqual(lines, ["a.md:2: error: x", "a.md:9: error: x", "b.md:1: error: x"])

    def test_inside_github_actions_prints_annotations(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            report([Finding("README.md", 2, ERROR, "mal")], "etiqueta")
        self.assertIn("::error file=README.md,line=2::mal", out.getvalue())


if __name__ == "__main__":
    unittest.main()

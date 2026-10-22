"""Comprobaciones de seguridad y coherencia de los workflows de .github/.

Necesita PyYAML; si no está instalado los tests se saltan (la sintaxis de los workflows
ya la revisa actionlint en el job «workflows» de ci.yml).
"""

import re
import unittest

from helpers import REPO_ROOT

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # En YAML 1.1 la clave `on` se lee como el booleano True.
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    return data


@unittest.skipIf(yaml is None, "PyYAML no está instalado")
class WorkflowTests(unittest.TestCase):
    def test_there_are_workflows(self):
        self.assertTrue(WORKFLOWS, "no hay archivos en .github/workflows")

    def test_each_workflow_has_name_trigger_and_jobs(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                data = load(path)
                self.assertIsInstance(data.get("name"), str)
                self.assertTrue(data.get("on"), "falta el bloque `on`")
                self.assertTrue(data.get("jobs"), "falta el bloque `jobs`")

    def test_permissions_are_declared_and_read_only(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                data = load(path)
                self.assertEqual(data.get("permissions"), {"contents": "read"})

    def test_every_job_has_a_timeout(self):
        for path in WORKFLOWS:
            for name, job in load(path)["jobs"].items():
                with self.subTest(workflow=path.name, job=name):
                    self.assertIn("timeout-minutes", job)

    def test_actions_use_a_pinned_version(self):
        for path in WORKFLOWS:
            for reference in USES.findall(path.read_text(encoding="utf-8")):
                with self.subTest(workflow=path.name, uses=reference):
                    self.assertNotIn(reference.rsplit("@", 1)[-1] if "@" in reference else reference.rsplit(":", 1)[-1], {"latest", "main", "master"})
                    self.assertTrue("@" in reference or reference.startswith("docker://"), "falta la versión (@vX)")

    def test_checkout_does_not_persist_credentials(self):
        for path in WORKFLOWS:
            for name, job in load(path)["jobs"].items():
                for step in job.get("steps", []):
                    if str(step.get("uses", "")).startswith("actions/checkout"):
                        with self.subTest(workflow=path.name, job=name):
                            self.assertIs(step.get("with", {}).get("persist-credentials"), False)

    def test_scripts_called_by_ci_exist(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for script in re.findall(r"python (scripts/\S+\.py)", text):
            with self.subTest(script=script):
                self.assertTrue((REPO_ROOT / script).is_file())

    def test_lychee_config_referenced_by_links_workflow_exists(self):
        text = (REPO_ROOT / ".github" / "workflows" / "links.yml").read_text(encoding="utf-8")
        for config in re.findall(r"--config (\S+)", text):
            with self.subTest(config=config):
                self.assertTrue((REPO_ROOT / config).is_file())

    def test_dependabot_config_is_valid(self):
        data = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        ecosystems = {update["package-ecosystem"] for update in data["updates"]}
        self.assertIn("github-actions", ecosystems)


if __name__ == "__main__":
    unittest.main()

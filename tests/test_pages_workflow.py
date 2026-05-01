import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "pages.yml"
)


class PagesWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def step_block(self, step_name):
        step_header = f"      - name: {step_name}\n"
        start = self.workflow.find(step_header)
        if start == -1:
            self.fail(f"Step not found: {step_name}")

        next_step = self.workflow.find("\n      - name: ", start + len(step_header))
        if next_step == -1:
            return self.workflow[start:]
        return self.workflow[start:next_step]

    def test_pages_artifact_is_built_from_site_directory(self):
        prepare = self.step_block("Prepare Pages artifact")

        self.assertIn("mkdir -p /tmp/atman-pages/docs/architecture", prepare)
        self.assertIn("cp -R docs/site/. /tmp/atman-pages/", prepare)
        self.assertIn("cp docs/CNAME /tmp/atman-pages/CNAME", prepare)

    def test_pages_artifact_contains_documents_used_by_site(self):
        prepare = self.step_block("Prepare Pages artifact")

        self.assertIn(
            "cp README.md README.en.md MANIFEST.md MANIFEST.en.md /tmp/atman-pages/",
            prepare,
        )
        self.assertIn(
            "cp docs/architecture/SYSTEM.md docs/architecture/SYSTEM.en.md /tmp/atman-pages/docs/architecture/",
            prepare,
        )

    def test_pages_upload_uses_prepared_artifact_directory(self):
        upload = self.step_block("Upload landing artifact")

        self.assertIn("uses: actions/upload-pages-artifact@v3", upload)
        self.assertIn("path: /tmp/atman-pages", upload)
        self.assertNotIn("path: .", upload)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "cursor-issue-intake.yml"
)


class CursorIssueIntakeWorkflowTest(unittest.TestCase):
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

    def test_checkout_does_not_persist_default_credentials(self):
        checkout = self.step_block("Checkout repository")

        self.assertIn("uses: actions/checkout@v4", checkout)
        self.assertIn("with:", checkout)
        self.assertIn("persist-credentials: false", checkout)

    def test_commit_push_step_configures_tokenized_origin_before_push(self):
        push = self.step_block("Commit and push changes")

        self.assertIn("GH_TOKEN: ${{ github.token }}", push)
        self.assertIn("GITHUB_REPOSITORY: ${{ github.repository }}", push)
        self.assertRegex(
            push,
            r"git remote set-url origin "
            r'"https://x-access-token:\$\{GH_TOKEN\}@github\.com/\$\{GITHUB_REPOSITORY\}\.git"',
        )
        self.assertLess(
            push.index("git remote set-url origin"),
            push.index('git push -u origin "$branch_name"'),
        )

    def test_cursor_api_key_is_scoped_to_agent_step_only(self):
        agent = self.step_block("Run Cursor Agent")

        self.assertIn("CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}", agent)
        self.assertEqual(
            self.workflow.count("CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}"),
            1,
        )


if __name__ == "__main__":
    unittest.main()

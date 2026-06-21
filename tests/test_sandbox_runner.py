import unittest
from pathlib import Path

from sandbox_runner import run_sandbox_validation, run_self_test, sample_rule


class SandboxRunnerTest(unittest.TestCase):
    def test_sandbox_self_test_passes_without_docker(self):
        result = run_self_test(strict_no_secrets=False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["sandbox"], "rule-engine")
        self.assertFalse(result["network_required"])
        self.assertEqual(result["engine"]["events"], 1)

    def test_sandbox_validation_runs_sample_rule(self):
        result = run_sandbox_validation(sample_rule(), ["AAPL", "GLD", "SPY"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["events"]), 1)
        self.assertLess(result["portfolio"]["AAPL_shares"], 10)
        self.assertGreater(result["portfolio"]["GLD_shares"], 0)

    def test_docker_sandbox_files_have_security_flags(self):
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
        workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

        self.assertIn("USER app", dockerfile)
        self.assertIn("--strict-no-secrets", dockerfile)
        self.assertIn("network_mode: \"none\"", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertIn(".env.*", dockerignore)
        self.assertIn("backtesting.db", dockerignore)
        self.assertIn("docker build -t backtesting-rule-sandbox", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("--read-only", workflow)


if __name__ == "__main__":
    unittest.main()

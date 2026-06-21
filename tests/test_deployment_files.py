import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFilesTest(unittest.TestCase):
    def test_railway_config_has_start_and_healthcheck(self):
        config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))

        self.assertEqual(config["build"]["builder"], "NIXPACKS")
        self.assertIn("uvicorn api:app", config["deploy"]["startCommand"])
        self.assertIn("--port $PORT", config["deploy"]["startCommand"])
        self.assertEqual(config["deploy"]["healthcheckPath"], "/health")

    def test_env_example_contains_only_placeholders(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME", env_example)
        self.assertIn("SECRET_KEY=change-me-to-a-long-random-string", env_example)
        self.assertIn("TAVILY_API_KEY=", env_example)
        self.assertNotIn("tvly-", env_example)

    def test_gitignore_excludes_local_database_files(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("backtesting.db", gitignore)
        self.assertIn("*.sqlite3", gitignore)

    def test_secret_scan_pattern_does_not_flag_risk_off_text(self):
        openai_pattern = re.compile(r"(?<![A-Za-z0-9_])" + "sk" + r"-(?:proj-)?[A-Za-z0-9_-]{20,}")

        self.assertIsNone(openai_pattern.search("Risk-Off-Marktrotation"))
        self.assertIsNotNone(openai_pattern.search("sk-" + "a" * 30))


if __name__ == "__main__":
    unittest.main()

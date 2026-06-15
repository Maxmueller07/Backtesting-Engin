import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api


class AgentApiTest(unittest.TestCase):
    def setUp(self):
        api.AGENT_CALLS.clear()
        self.client = TestClient(api.app)

    def tearDown(self):
        api.app.dependency_overrides.clear()
        api.AGENT_CALLS.clear()

    def authenticate(self):
        api.app.dependency_overrides[api.get_current_user] = lambda: {"user_id": 1, "username": "tester"}

    @patch("api.run_agent_analysis")
    def test_agent_analyze_endpoint_returns_agent_result(self, run_agent_analysis):
        self.authenticate()
        run_agent_analysis.return_value = {
            "symbol": "MSFT",
            "name": "Microsoft",
            "summary": "Analyse fertig",
            "sections": [],
            "data_source": "yfinance",
        }

        response = self.client.post(
            "/agent/analyze",
            json={
                "symbol": "msft",
                "name": "Microsoft",
                "template": {
                    "management": True,
                    "balance_sheet": False,
                    "industry_analysis": True,
                    "moat": False,
                },
                "instructions": {
                    "management": "CEO",
                    "balance_sheet": "ROE ROCE",
                    "industry_analysis": "Wettbewerber",
                    "moat": "Marke",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["symbol"], "MSFT")
        run_agent_analysis.assert_called_once_with(
            symbol="MSFT",
            name="Microsoft",
            template={
                "management": True,
                "balance_sheet": False,
                "industry_analysis": True,
                "moat": False,
            },
            instructions={
                "management": "CEO",
                "balance_sheet": "ROE ROCE",
                "industry_analysis": "Wettbewerber",
                "moat": "Marke",
            },
        )

    def test_agent_analyze_requires_login(self):
        response = self.client.post("/agent/analyze", json={"symbol": "MSFT"})
        self.assertIn(response.status_code, (401, 403))

    def test_agent_analyze_rejects_empty_symbol(self):
        self.authenticate()
        response = self.client.post("/agent/analyze", json={"symbol": "   "})
        self.assertEqual(response.status_code, 400)

    def test_agent_analyze_rejects_oversized_instruction(self):
        self.authenticate()
        response = self.client.post(
            "/agent/analyze",
            json={
                "symbol": "MSFT",
                "instructions": {"management": "x" * 501},
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

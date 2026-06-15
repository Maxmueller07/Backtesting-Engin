import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api


class DashboardApiTest(unittest.TestCase):
    def setUp(self):
        api.app.dependency_overrides[api.get_current_user] = lambda: {"user_id": 7, "username": "tester"}
        self.client = TestClient(api.app)

    def tearDown(self):
        api.app.dependency_overrides.clear()

    @patch("api.save_portfolio", return_value=123)
    def test_portfolio_save_accepts_base_and_asset_currency(self, save_portfolio):
        response = self.client.post("/portfolios", json={
            "name": "FX Portfolio",
            "startkapital": 5000,
            "basiswaehrung": "EUR",
            "assets": [
                {"name": "Apple", "symbol": "AAPL", "anteil": 60, "waehrung": "USD", "steuer_typ": "aktie", "regeln": {}},
                {"name": "Rheinmetall", "symbol": "RHM.DE", "anteil": 40, "waehrung": "AUTO", "steuer_typ": "aktie", "regeln": {}},
            ],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["portfolio_id"], 123)
        self.assertEqual(save_portfolio.call_args.kwargs["basiswaehrung"], "EUR")
        saved_assets = save_portfolio.call_args.args[3]
        self.assertEqual(saved_assets[0]["waehrung"], "USD")
        self.assertEqual(saved_assets[0]["steuer_typ"], "aktie")
        self.assertEqual(saved_assets[1]["waehrung"], "AUTO")

    @patch("api.build_portfolio_dashboard", return_value={"id": 1, "name": "Demo", "basiswaehrung": "EUR"})
    @patch("api.get_portfolios", return_value=[{"id": 1, "name": "Demo", "assets": []}])
    def test_dashboard_endpoint_returns_saved_portfolio_dashboards(self, get_portfolios, build_dashboard):
        response = self.client.get("/dashboard/portfolios")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["portfolios"][0]["name"], "Demo")
        get_portfolios.assert_called_once_with(7)
        build_dashboard.assert_called_once()


if __name__ == "__main__":
    unittest.main()

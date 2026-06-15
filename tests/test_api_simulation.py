import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api


class FakeHistory:
    def to_dict(self):
        return {
            "Gesamtwert": {"2024-01-01": 1000, "2024-01-02": 1010},
            "AAPL_wert": {"2024-01-01": 1000, "2024-01-02": 1010},
        }


class SimulationApiTest(unittest.TestCase):
    def setUp(self):
        api.PUBLIC_SIMULATION_CALLS.clear()
        self.client = TestClient(api.app)
        self.config = {
            "startkapital": 1000,
            "startdatum": "2024-01-01",
            "enddatum": "2024-01-03",
            "basiswaehrung": "EUR",
            "intervall": 30,
            "sp_start": 0,
            "sparplan_dynamisierung": 5,
            "sparplan_limit": 1000,
            "aktive_regeln": [],
            "assets": [
                {"name": "Apple", "symbol": "AAPL", "anteil": 100, "waehrung": "USD", "steuer_typ": "aktie", "regeln": {}}
            ],
            "schwellwert_config": {
                "schwelle": 5000,
                "von": "AAPL",
                "zu": "AAPL",
                "prozent": 10,
            },
            "stop_loss_config": {
                "ausstieg_prozent": 12,
                "wiedereinstieg_prozent": 3,
            },
            "transaktionskosten_config": {
                "aktiv": True,
                "ordergebuehr_fix": 1,
                "ordergebuehr_prozent": 0.1,
                "mindestgebuehr": 0,
                "maximalgebuehr": 0,
            },
            "steuer_config": {
                "aktiv": True,
                "land": "DE",
                "jahreseinkommen": 45000,
                "automatisch_aus_einkommen": True,
                "sparer_pauschbetrag": 1000,
                "kapitalertragsteuer": 25,
                "solidaritaetszuschlag": 5.5,
                "kirchensteuer": 0,
                "tax_loss_harvesting": True,
                "harvesting_schwelle_prozent": 5,
            },
        }

    @patch("api.simuliere")
    def test_public_simulation_does_not_require_login(self, simuliere):
        simuliere.return_value = {
            "gesamtwert": 1010,
            "gesamt_eingezahlt": 1000,
            "gewinn": 10,
            "gesamt_rendite": 1.0,
            "jaehrliche_rendite": 1.0,
            "sharpe_ratio": 1.0,
            "volatilitaet": 1.0,
            "einzel_werte": {"AAPL": 1010},
            "historie": FakeHistory(),
            "basiswaehrung": "EUR",
            "waehrungen": {"AAPL": {"asset_currency": "USD", "basis_currency": "EUR"}},
        }

        response = self.client.post("/simuliere/public", json=self.config)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["historie"]["Gesamtwert"]["2024-01-02"], 1010)
        self.assertEqual(
            simuliere.call_args.kwargs["schwellwert_config"],
            {"schwelle": 5000.0, "von": "AAPL", "zu": "AAPL", "prozent": 10.0},
        )
        self.assertEqual(
            simuliere.call_args.kwargs["stop_loss_config"],
            {"ausstieg_prozent": 12.0, "wiedereinstieg_prozent": 3.0},
        )
        self.assertEqual(simuliere.call_args.kwargs["sparplan_dynamisierung"], 0.05)
        self.assertEqual(simuliere.call_args.kwargs["sparplan_limit"], 1000)
        self.assertEqual(simuliere.call_args.kwargs["basiswaehrung"], "EUR")
        self.assertTrue(simuliere.call_args.kwargs["transaktionskosten_config"]["aktiv"])
        self.assertTrue(simuliere.call_args.kwargs["steuer_config"]["tax_loss_harvesting"])
        self.assertEqual(simuliere.call_args.kwargs["steuer_config"]["jahreseinkommen"], 45000.0)

    def test_private_simulation_stays_protected_without_token(self):
        response = self.client.post("/simuliere", json=self.config)
        self.assertIn(response.status_code, (401, 403))

    def test_invalid_simulation_values_are_rejected(self):
        invalid = {**self.config, "intervall": 0}
        response = self.client.post("/simuliere/public", json=invalid)
        self.assertEqual(response.status_code, 422)

    @patch("api.simuliere")
    def test_public_simulation_is_rate_limited(self, simuliere):
        old_limit = api.PUBLIC_SIMULATION_RATE_LIMIT
        api.PUBLIC_SIMULATION_RATE_LIMIT = 1
        simuliere.return_value = {
            "gesamtwert": 1010,
            "gesamt_eingezahlt": 1000,
            "gewinn": 10,
            "gesamt_rendite": 1.0,
            "jaehrliche_rendite": 1.0,
            "sharpe_ratio": 1.0,
            "volatilitaet": 1.0,
            "einzel_werte": {"AAPL": 1010},
            "historie": FakeHistory(),
            "basiswaehrung": "EUR",
            "waehrungen": {"AAPL": {"asset_currency": "USD", "basis_currency": "EUR"}},
        }

        try:
            first = self.client.post("/simuliere/public", json=self.config)
            second = self.client.post("/simuliere/public", json=self.config)
        finally:
            api.PUBLIC_SIMULATION_RATE_LIMIT = old_limit
            api.PUBLIC_SIMULATION_CALLS.clear()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


if __name__ == "__main__":
    unittest.main()

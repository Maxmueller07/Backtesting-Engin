import unittest

from fastapi.testclient import TestClient

import api
from ticker_resolver import resolve_ticker_candidates


class TickerResolverTest(unittest.TestCase):
    def test_known_german_company_resolves_to_yfinance_suffix(self):
        candidates = resolve_ticker_candidates("rheinmetall")

        self.assertEqual(candidates[0]["symbol"], "RHM.DE")
        self.assertEqual(candidates[0]["waehrung"], "EUR")
        self.assertEqual(candidates[0]["steuer_typ"], "aktie")

    def test_crypto_shortcut_resolves_to_yfinance_pair(self):
        candidates = resolve_ticker_candidates("btc")

        self.assertEqual(candidates[0]["symbol"], "BTC-USD")
        self.assertEqual(candidates[0]["steuer_typ"], "crypto")

    def test_unknown_symbol_returns_suffix_candidates(self):
        candidates = resolve_ticker_candidates("abc", market="DE")

        self.assertEqual(candidates[0]["symbol"], "ABC.DE")
        self.assertIn("ABC.F", [candidate["symbol"] for candidate in candidates])

    def test_ticker_resolve_endpoint(self):
        client = TestClient(api.app)

        response = client.get("/ticker/resolve", params={"q": "apple"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidates"][0]["symbol"], "AAPL")


if __name__ == "__main__":
    unittest.main()

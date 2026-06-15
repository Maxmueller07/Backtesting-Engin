import unittest

from tax_engine import TradeLedger, estimate_personal_marginal_tax_rate


class TaxEngineIncomeTest(unittest.TestCase):
    def test_personal_income_rate_is_used_when_lower_than_flat_tax(self):
        low_income = TradeLedger(tax_config={
            "aktiv": True,
            "jahreseinkommen": 10000,
            "automatisch_aus_einkommen": True,
            "kapitalertragsteuer": 25,
            "solidaritaetszuschlag": 5.5,
        })
        average_income = TradeLedger(tax_config={
            "aktiv": True,
            "jahreseinkommen": 45000,
            "automatisch_aus_einkommen": True,
            "kapitalertragsteuer": 25,
            "solidaritaetszuschlag": 5.5,
        })

        self.assertEqual(estimate_personal_marginal_tax_rate(10000), 0)
        self.assertEqual(low_income.effective_tax_rate(), 0)
        self.assertAlmostEqual(average_income.summary()["verwendeter_kapitalsteuersatz"], 25.0)
        self.assertAlmostEqual(average_income.effective_tax_rate() * 100, 26.375)


if __name__ == "__main__":
    unittest.main()

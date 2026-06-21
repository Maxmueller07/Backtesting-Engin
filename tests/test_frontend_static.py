from pathlib import Path
import unittest


class FrontendStaticTest(unittest.TestCase):
    def test_simulation_uses_public_endpoint_without_valid_token(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("localStorage.getItem('token')", html)
        self.assertIn("'/simuliere/public'", html)
        self.assertIn("res.status === 401", html)
        self.assertIn("localStorage.removeItem('token')", html)
        self.assertIn("function apiErrorMessage", html)
        self.assertIn("await res.json()", html)
        self.assertIn("throw new Error(apiErrorMessage(res.status, errorData))", html)

    def test_risk_and_savings_controls_are_present(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("id=\"backtest-name\"", html)
        self.assertIn("name: rawName || 'Backtest'", html)
        self.assertIn("id=\"sp-dynamisierung\"", html)
        self.assertIn("id=\"sp-limit\"", html)
        self.assertIn("id=\"stop-ausstieg\"", html)
        self.assertIn("id=\"stop-wiedereinstieg\"", html)
        self.assertIn("stop_loss_config", html)
        self.assertIn("id=\"basiswaehrung\"", html)
        self.assertIn("id=\"new-currency\"", html)
        self.assertIn("waehrung:a.waehrung || 'AUTO'", html)
        self.assertIn("id=\"costs-active\"", html)
        self.assertIn("id=\"tax-active\"", html)
        self.assertIn("id=\"sw-costs-active\"", html)
        self.assertIn("id=\"sw-tax-active\"", html)
        self.assertIn("id=\"tax-income\"", html)
        self.assertIn("estimatePersonalTaxRate", html)
        self.assertIn("updateDerivedTaxRate", html)
        self.assertIn("id=\"tax-loss-harvesting\"", html)
        self.assertIn("transaktionskosten_config", html)
        self.assertIn("steuer_config", html)
        self.assertIn("automatisch_aus_einkommen", html)
        self.assertIn("resolveNewTicker", html)

    def test_login_goes_to_dashboard_and_dashboard_can_open_backtest(self):
        login = Path("login.html").read_text(encoding="utf-8")
        dashboard = Path("dashboard.html").read_text(encoding="utf-8")

        self.assertIn("dashboard.html", login)
        self.assertIn("/dashboard/portfolios", dashboard)
        self.assertIn("dashboardPortfolio", dashboard)
        self.assertIn("allocation-chart", dashboard)
        self.assertIn("history-chart", dashboard)
        self.assertIn("Portfolio backtesten", dashboard)
        self.assertIn("openBacktest", dashboard)

    def test_dashboard_can_compare_two_portfolios(self):
        dashboard = Path("dashboard.html").read_text(encoding="utf-8")

        self.assertIn("id=\"compare-a\"", dashboard)
        self.assertIn("id=\"compare-b\"", dashboard)
        self.assertIn("id=\"compare-msg\"", dashboard)
        self.assertIn("compareSelectedPortfolios", dashboard)
        self.assertIn("renderCompareView", dashboard)
        self.assertIn("compare-history-chart", dashboard)
        self.assertIn("compare-allocation-chart", dashboard)
        self.assertIn("prefillCompare", dashboard)
        self.assertIn("sameId", dashboard)
        self.assertIn("showCompareMessage", dashboard)
        self.assertNotIn("button.disabled = dashboards.length < 2", dashboard)

    def test_agent_frontend_sends_token_and_sanitizes_source_links(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("Authorization: `Bearer ${token}`", html)
        self.assertIn("function safeUrl(value)", html)
        self.assertIn("['http:', 'https:'].includes(url.protocol)", html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("${escapeHtml(a.symbol)}", html)
        self.assertIn("${escapeHtml(a.name)}", html)

    def test_backtest_sidebar_is_resizable_and_charts_resize(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("--sidebar-width", html)
        self.assertIn("id=\"sidebar-resizer\"", html)
        self.assertIn("function initSidebarResize()", html)
        self.assertIn("setSidebarWidth(width", html)
        self.assertIn("resizeChartsSoon", html)
        self.assertIn("chart.resize()", html)
        self.assertIn("backtestSidebarWidth", html)

    def test_backtesting_page_can_compare_two_configs(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("Backtest Vergleich", html)
        self.assertIn("id=\"compare-a-status\"", html)
        self.assertIn("id=\"compare-b-status\"", html)
        self.assertIn("id=\"compare-a-name\"", html)
        self.assertIn("id=\"compare-b-name\"", html)
        self.assertIn("storeCompareSlot('a')", html)
        self.assertIn("storeCompareSlot('b')", html)
        self.assertIn("runBacktestComparison", html)
        self.assertIn("buildSimulationConfig", html)
        self.assertIn("postSimulationConfig", html)
        self.assertIn("chart-compare-value", html)
        self.assertIn("chart-compare-return", html)
        self.assertIn("config.name || 'Backtest'", html)
        self.assertIn("slotNameInput?.value.trim()", html)

    def test_ai_rule_builder_frontend_is_wired(self):
        html = Path("index.html").read_text(encoding="utf-8")

        self.assertIn("AI Rule Builder", html)
        self.assertIn("id=\"rule-builder-text\"", html)
        self.assertIn("function buildAiRule()", html)
        self.assertIn("/rules/build", html)
        self.assertIn("Authorization:`Bearer ${token}`", html)
        self.assertIn("custom_regeln: cloneData(customRegeln)", html)
        self.assertIn("function addPendingCustomRule()", html)
        self.assertIn("function renderCustomRules()", html)
        self.assertIn(".map(a => (a.symbol || '').trim().toUpperCase())", html)
        self.assertIn("id=\"rule-new-asset-mode\"", html)
        self.assertIn("new_asset_mode: newAssetMode", html)
        self.assertIn("pendingNewAssets", html)
        self.assertIn("pendingCustomRules", html)
        self.assertIn("rule_count: pendingCustomRules.length", html)
        self.assertIn("function addResolvedRuleAssets", html)
        self.assertIn("requires_asset_approval", html)


if __name__ == "__main__":
    unittest.main()

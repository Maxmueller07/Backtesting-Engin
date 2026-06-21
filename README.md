# Backtesting-Engin

Python/FastAPI backtesting engine with a static HTML frontend, yfinance market data, portfolio dashboard, taxes, transaction costs and AI-assisted analysis.

## AI Rule Builder

The AI Rule Builder converts natural-language backtesting ideas into a safe structured JSON rule. It does not execute AI-generated Python code.

The rule builder now runs as a LangGraph agent:

```text
normalize
-> finance_relevance
-> rule_builder
-> rule_validator
-> rule_auditor
-> example_generator
-> final_response
```

Implementation files:

- `rule_agent_graph.py`
- `rule_agent_nodes.py`
- `ai_rule_builder.py`
- `custom_rule_engine.py`

Example input:

```text
Buy gold when the market rotation score is above 70. Use 20% of my Apple position.
```

Example output:

```json
{
  "id": "rule_market_rotation_score_aapl_gld",
  "name": "Transfer 20% AAPL to GLD",
  "condition": {
    "indicator": "market_rotation_score",
    "operator": ">",
    "value": 70,
    "params": {
      "equity_proxy": "SPY",
      "defensive_proxy": "GLD",
      "window": 90
    }
  },
  "actions": [
    {
      "type": "transfer_position_percent",
      "from_asset": "AAPL",
      "to_asset": "GLD",
      "percent": 20
    }
  ]
}
```

Supported actions:

- `transfer_position_percent`
- `sell_position_percent`
- `buy_with_cash_percent`

Supported indicators:

- `price_above_moving_average`
- `price_below_moving_average`
- `relative_strength`
- `drawdown`
- `volatility`
- `market_rotation_score`

The backend validates every rule before simulation. Rule execution has no file access, no network access, no shell commands, no imports, no `eval` and no `exec`.

## Self-Healing Rule Builder

The normal rule text field can now recover from missing but safe price indicators. The flow is:

```text
natural language rule
-> normal /rules/build
-> unsupported indicator detected
-> CapabilityGapDetector
-> IndicatorSynthesizer
-> Formula Indicator DSL
-> FormulaSecurityAuditor
-> IndicatorTestRunner
-> IndicatorRegistry.register_dynamic_indicator(...)
-> retry original rule
-> final validated custom rule
```

The generated indicator is a JSON Formula DSL definition, not Python code. The backtest runtime never calls Gemini/OpenAI and never synthesizes indicators during simulation. Dynamic indicators are usable only after security audit and deterministic tests pass.

Auto-synthesized indicators currently include:

- `entropy`
- `rsi`
- `macd`
- `correlation` / `rolling_correlation`
- `beta`
- `z_score`
- `moving_average_slope`
- `momentum` / `rolling_return`
- `rolling_volatility`
- `rolling_max_drawdown`

Example:

```text
If the 14-day RSI of AAPL is below 30, use 25% of my cash to buy AAPL.
```

If `rsi` is not registered yet, `/rules/build` creates a safe RSI formula indicator, audits it, tests it, registers it, retries the original text and returns:

```json
{
  "status": "ok",
  "auto_extensions": [
    {
      "name": "rsi",
      "type": "formula_indicator",
      "status": "approved",
      "tests_passed": true,
      "security_passed": true,
      "lookahead_safe": true
    }
  ],
  "auto_extension_trace": {
    "missing_indicator": "rsi",
    "synthesis_attempted": true,
    "formula_created": true,
    "security_passed": true,
    "tests_passed": true,
    "registered": true,
    "original_rule_retried": true
  }
}
```

External-data indicators such as news sentiment, earnings surprises, analyst ratings, macro data, broker/order-flow data or social sentiment return `needs_manual_review` because they cannot be safely generated from historical price data alone.

Implementation entry points:

- `indicator_registry.py`
- `indicator_formula_dsl.py`
- `capability_gap_detector.py`
- `indicator_synthesizer.py`
- `extension_security.py`
- `indicator_test_runner.py`

`main.py` stays focused on the backtest loop; it is not filled with new indicator-specific logic.

## Docker Sandbox

The repository includes a Docker sandbox smoke test for the AI Rule Builder and custom rule engine.

Files:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `sandbox_runner.py`

Run locally without Docker:

```bash
python sandbox_runner.py --self-test
```

Run with Docker:

```bash
docker build -t backtesting-rule-sandbox .
docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges backtesting-rule-sandbox
```

Or with Docker Compose:

```bash
docker compose run --rm rule-sandbox
```

The Docker sandbox excludes `.env`, `.env.txt`, local databases and cache files. The CI run starts the sandbox with no network and no secret environment variables.

## API

Build a rule:

```bash
curl -X POST http://127.0.0.1:8000/rules/build \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "natural_language_rule": "Buy gold when the market rotation score is above 70. Use 20% of my Apple position.",
    "portfolio_symbols": ["AAPL", "GLD", "SPY"],
    "base_currency": "EUR"
  }'
```

Validate a rule:

```bash
curl -X POST http://127.0.0.1:8000/rules/validate \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"portfolio_symbols":["AAPL","GLD","SPY"],"rule":{...}}'
```

Use rules in a simulation by adding `custom_regeln` to the simulation payload.

## Environment

No API key is committed. For full LLM rule generation set one of:

```env
OPENAI_API_KEY=
RULE_BUILDER_API_KEY=
RULE_BUILDER_MODEL=gpt-4.1-mini
```

For OpenAI:

```env
RULE_BUILDER_PROVIDER=openai
RULE_BUILDER_API_KEY=<openai-api-key>
RULE_BUILDER_MODEL=gpt-4.1-mini
```

For Gemini:

```env
RULE_BUILDER_PROVIDER=gemini
GOOGLE_API_KEY=<gemini-api-key>
RULE_BUILDER_MODEL=gemini-3.1-flash-lite
```

Simple known rule patterns work deterministically without an API key for local testing.

## Tests

```bash
python -m unittest discover -s tests -v
```

CI also runs:

- tracked secret/local-file check
- secret-pattern scan
- full unittest suite
- Docker sandbox build
- Docker sandbox smoke test

## Disclaimer

This project provides historical backtesting and educational analysis only. It does not provide investment advice. Generated rules are not trading recommendations. No real orders are placed.
